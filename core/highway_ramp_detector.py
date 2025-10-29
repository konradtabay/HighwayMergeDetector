#!/usr/bin/env python3
"""
Highway Ramp Detection System
=============================

Merge points are detected using a weighted analysis:
- Road geometry (bearing change detection)
- OpenStreetMap ramp proximity 
- OpenStreetMap road network type
-Magnitude of max and min speeds

Author: Konrad Tabay
Version: 1.0.0
"""

import csv
import math
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import json
import urllib.request
import urllib.parse
import time
import numpy as np
from scipy.signal import savgol_filter
import requests
import os

# Try to load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, continue without it


# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """Central configuration for the detection system"""
    
    # Directories
    INPUT_DIR = Path("input")
    OUTPUT_DIR = Path("output")
    DATA_DIR = Path("data")
    
    # On-ramp detection thresholds
    ONRAMP_MIN_SPEED_INCREASE = 30  # km/h
    ONRAMP_START_SPEED_MAX = 40     # km/h Must be going num or below to consider an on-ramp
    ONRAMP_END_SPEED_MIN = 60       # km/h
    ONRAMP_MIN_BEARING_CHANGE = 30  # degrees
    ONRAMP_OSM_PROXIMITY = 0.3      # km
    ONRAMP_MIN_BEARING_NO_OSM = 50  # degrees (stricter if no OSM)

    # Off-ramp detection thresholds
    OFFRAMP_MIN_SPEED_DECREASE = 30 # km/h (must be significant deceleration)
    OFFRAMP_START_SPEED_MIN = 80    # km/h (MUST be from highway speed)
    OFFRAMP_END_SPEED_MAX = 60      # km/h (exit to ramp speed, not stopped)
    OFFRAMP_MIN_BEARING_CHANGE = 15 # degrees
    OFFRAMP_OSM_PROXIMITY = 0.15    # km (REQUIRED for off-ramps)
    
    # Analysis window
    ANALYSIS_WINDOW = 40  # Number of GPS points to analyze (doubled for longer merge segments)
    DEDUPLICATION_WINDOW = 100  # Points within this are considered same ramp
    
    # Google Directions API validation
    GOOGLE_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')  # Set via environment variable
    ENABLE_GOOGLE_VALIDATION = bool(GOOGLE_API_KEY)  # Auto-enabled if API key is available
    GOOGLE_VALIDATION_TIMEOUT = 10  # seconds
    GOOGLE_DISTANCE_TOLERANCE = 0.2  # 20% tolerance for distance comparison


# ============================================================================
# GPS SIGNAL PROCESSING
# ============================================================================

class GPSFilter:
    """GPS signal processing utilities for noise reduction while preserving derivatives"""
    
    @staticmethod
    def savgol_filter_gps(gps_points: List[Dict], window_length: int = 11, polyorder: int = 3) -> List[Dict]:
        """
        Apply Savitzky-Golay filter to GPS coordinates while preserving speed/acceleration characteristics
        
        Args:
            gps_points: List of GPS points with 'latitude', 'longitude', 'timestamp', 'speed_kmh'
            window_length: Window size for filtering (must be odd)
            polyorder: Polynomial order for fitting
            
        Returns:
            Filtered GPS points with same structure
        """
        if len(gps_points) < window_length:
            return gps_points  # Not enough points to filter
        
        # Extract coordinates
        lats = np.array([p['latitude'] for p in gps_points])
        lons = np.array([p['longitude'] for p in gps_points])
        
        # Apply Savitzky-Golay filter
        filtered_lats = savgol_filter(lats, window_length, polyorder)
        filtered_lons = savgol_filter(lons, window_length, polyorder)
        
        # Reconstruct GPS points with filtered coordinates but preserve original speed
        filtered_points = []
        for i, original_point in enumerate(gps_points):
            filtered_point = original_point.copy()
            filtered_point['latitude'] = float(filtered_lats[i])
            filtered_point['longitude'] = float(filtered_lons[i])
            # Preserve original speed and timestamp
            filtered_points.append(filtered_point)
        
        return filtered_points
    
    @staticmethod
    def remove_gps_outliers(gps_points: List[Dict], max_speed_kmh: float = 200) -> List[Dict]:
        """
        Remove obvious GPS outliers based on unrealistic speeds
        
        Args:
            gps_points: List of GPS points
            max_speed_kmh: Maximum realistic speed threshold
            
        Returns:
            GPS points with outliers removed
        """
        if len(gps_points) < 2:
            return gps_points
        
        filtered_points = [gps_points[0]]  # Keep first point
        
        for i in range(1, len(gps_points)):
            prev_point = gps_points[i-1]
            curr_point = gps_points[i]
            
            # Calculate time difference
            time_diff = (curr_point['timestamp'] - prev_point['timestamp']).total_seconds()
            if time_diff <= 0:
                continue  # Skip invalid timestamps
            
            # Calculate distance and speed
            distance = haversine_distance(
                prev_point['latitude'], prev_point['longitude'],
                curr_point['latitude'], curr_point['longitude']
            )
            speed_kmh = (distance / time_diff) * 3600  # Convert to km/h
            
            # Keep point if speed is realistic
            if speed_kmh <= max_speed_kmh:
                filtered_points.append(curr_point)
        
        return filtered_points
    
    @staticmethod
    def process_gps_track(gps_points: List[Dict]) -> List[Dict]:
        """
        Complete GPS processing pipeline: outlier removal + Savitzky-Golay filtering
        
        Args:
            gps_points: Raw GPS points
            
        Returns:
            Cleaned and filtered GPS points
        """
        # Step 1: Remove obvious outliers
        cleaned_points = GPSFilter.remove_gps_outliers(gps_points)
        
        # Step 2: Apply Savitzky-Golay filter if enough points
        if len(cleaned_points) >= 11:
            filtered_points = GPSFilter.savgol_filter_gps(cleaned_points, window_length=11, polyorder=3)
        else:
            filtered_points = cleaned_points
        
        return filtered_points



class GoogleDirectionsValidator:
    """Validate merge detections using Google Directions API"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api/directions/json"
    
    def _expand_offramp_window(self, merge_data: Dict, route: List[Dict]) -> Dict:
        """Expand off-ramp window to capture more context for Google validation"""
        # Use ±20 samples around the original detection
        # This provides enough context for Google to detect ramp maneuvers
        window_expansion = 20
        
        original_start = merge_data['segment_start']
        original_end = merge_data['segment_end']
        
        # Expand window
        expanded_start = max(0, original_start - window_expansion)
        expanded_end = min(len(route), original_end + window_expansion)
        
        # Create new merge data with expanded coordinates
        expanded_merge = merge_data.copy()
        expanded_merge['segment_start'] = expanded_start
        expanded_merge['segment_end'] = expanded_end
        expanded_merge['start_lat'] = route[expanded_start]['lat']
        expanded_merge['start_lon'] = route[expanded_start]['lon']
        expanded_merge['end_lat'] = route[expanded_end-1]['lat']
        expanded_merge['end_lon'] = route[expanded_end-1]['lon']
        
        return expanded_merge
    
    def validate_merge_instance(self, merge_data: Dict, route: List[Dict]) -> Dict:
        """Validate a single merge instance using Google Directions"""
        
        # For off-ramps, use a wider window to capture more context
        # This helps Google detect ramp maneuvers that might be missed in short segments
        merge_type = merge_data.get('merge_type', '')
        if merge_type == 'off_ramp':
            merge_data = self._expand_offramp_window(merge_data, route)
        
        # Extract start and end points from merge data
        start_point = f"{merge_data['start_lat']},{merge_data['start_lon']}"
        end_point = f"{merge_data['end_lat']},{merge_data['end_lon']}"
        
        # Query Google Directions API
        directions_response = self._query_directions(start_point, end_point)
        
        if not directions_response:
            return {'valid': False, 'reason': 'API request failed', 'rejected': True}
        
        # Extract route information
        route_info = self._extract_route_info(directions_response)
        
        if not route_info['distance']:
            return {'valid': False, 'reason': 'No route found', 'rejected': True}
        
        # Calculate actual GPS segment distance (not straight-line)
        detected_distance = self._calculate_merge_distance(merge_data, route)
        
        # Compare with 3x tolerance (much more lenient)
        distance_ratio = abs(route_info['distance'] - detected_distance) / detected_distance if detected_distance > 0 else 1.0
        distance_valid = distance_ratio <= 3.0  # 3x tolerance instead of 20%
        
        # Check if route uses highway ramps using maneuver types
        uses_ramps = self._check_highway_ramps(route_info['steps'])
        
        # For off-ramps: fallback to OSM proximity if Google doesn't detect ramp
        # Very close OSM proximity (< 20m) is reliable evidence for off-ramps
        # Google might not detect ramp maneuvers for very short segments
        merge_type = merge_data.get('merge_type', '')
        osm_distance_m = merge_data.get('osm_distance_m', 9999)
        has_close_osm_proximity = osm_distance_m < 20 and merge_type == 'off_ramp'
        
        # Primary requirement: MUST use ramps (or have close OSM proximity for off-ramps)
        # Distance must not be massively off (reject if > 10x difference)
        massive_reroute = distance_ratio > 10.0
        is_valid = (uses_ramps or has_close_osm_proximity) and not massive_reroute
        
        return {
            'valid': is_valid,
            'distance_valid': distance_valid,
            'uses_ramps': uses_ramps,
            'detected_distance': detected_distance,
            'google_distance': route_info['distance'],
            'distance_ratio': distance_ratio,
            'route_steps': len(route_info['steps']),
            'rejected': not is_valid,
            'has_osm_fallback': has_close_osm_proximity,
            'reason': self._get_validation_reason(is_valid, distance_valid, uses_ramps, distance_ratio, has_close_osm_proximity)
        }
    
    def _query_directions(self, start: str, end: str) -> Optional[Dict]:
        """Query Google Directions API"""
        params = {
            'origin': start,
            'destination': end,
            'key': self.api_key,
            'mode': 'driving'
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  ✗ Google Directions API error: {e}")
            return None
    
    def _extract_route_info(self, directions_response: Dict) -> Dict:
        """Extract distance and route steps from Google response"""
        if not directions_response.get('routes'):
            return {'distance': 0, 'steps': []}
        
        route = directions_response['routes'][0]
        leg = route['legs'][0]
        
        return {
            'distance': leg['distance']['value'],  # meters
            'steps': leg['steps']
        }
    
    def _calculate_merge_distance(self, merge_data: Dict, route: List[Dict]) -> float:
        """Calculate actual distance of the GPS segment"""
        # Get the GPS points for this segment
        start_idx = merge_data['segment_start']
        end_idx = merge_data['segment_end']
        
        total_distance = 0.0
        for i in range(start_idx, min(end_idx, len(route) - 1)):
            segment_dist = haversine_distance(
                route[i]['lat'], route[i]['lon'],
                route[i+1]['lat'], route[i+1]['lon']
            ) * 1000  # Convert to meters
            total_distance += segment_dist
        
        return total_distance
    
    def _check_highway_ramps(self, steps: List[Dict]) -> bool:
        """Check if route steps indicate highway ramp usage using maneuver types"""
        ramp_maneuvers = [
            'ramp-right', 'ramp-left', 'merge', 'fork-right', 'fork-left',
            'exit-right', 'exit-left'
        ]
        
        # First check for explicit maneuver types (most reliable)
        for step in steps:
            maneuver = step.get('maneuver', '')
            if maneuver in ramp_maneuvers:
                return True
        
        # Fallback: Check HTML instructions for ramp keywords
        # This helps catch cases where Google doesn't set maneuver field
        # (common for very short routes or when already on ramp)
        ramp_keywords = ['ramp', 'merge', 'exit', 'off-ramp', 'on-ramp', 'merge onto']
        for step in steps:
            html_instruction = step.get('html_instructions', '').lower()
            if any(keyword in html_instruction for keyword in ramp_keywords):
                return True
        
        return False
    
    def _get_validation_reason(self, is_valid: bool, distance_valid: bool, uses_ramps: bool, distance_ratio: float, has_osm_fallback: bool = False) -> str:
        """Generate human-readable validation reason"""
        if is_valid:
            if uses_ramps:
                if distance_valid:
                    return f"Valid: uses ramps, distance ratio {distance_ratio:.2f}"
                else:
                    return f"Valid: uses ramps (distance ratio {distance_ratio:.2f}, above 3x tolerance but acceptable)"
            elif has_osm_fallback:
                return f"Valid: off-ramp with close OSM proximity (< 20m), distance ratio {distance_ratio:.2f}"
        else:
            if not uses_ramps and not has_osm_fallback:
                return f"Rejected: no ramp maneuvers detected in Google route"
            elif distance_ratio > 10.0:
                return f"Rejected: massive reroute detected (distance ratio {distance_ratio:.2f} > 10x)"
            else:
                return f"Rejected: no ramps and distance mismatch"


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS coordinates in kilometers"""
    R = 6371  # Earth's radius in km
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat, dlon = lat2_rad - lat1_rad, lon2_rad - lon1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def calculate_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate bearing between two GPS coordinates in degrees"""
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlon = lon2_rad - lon1_rad
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360


def setup_directories():
    """Create necessary directories if they don't exist"""
    Config.INPUT_DIR.mkdir(exist_ok=True)
    Config.OUTPUT_DIR.mkdir(exist_ok=True)
    Config.DATA_DIR.mkdir(exist_ok=True)


# ============================================================================
# DATA LOADING
# ============================================================================

class GPXConverter:
    """Convert GPX files to CSV format with calculated speeds"""
    
    @staticmethod
    def convert(gpx_file: Path, csv_file: Path) -> int:
        """Convert GPX to CSV and return number of points"""
        print(f"  Converting {gpx_file.name} to CSV...")
        
        tree = ET.parse(gpx_file)
        root = tree.getroot()
        
        namespaces = {
            'gpx': 'http://www.topografix.com/GPX/1/1',
            'gpxx': 'http://www.garmin.com/xmlschemas/GpxExtensions/v3',
        }
        
        track_points = root.findall('.//gpx:trkpt', namespaces)
        
        # Extract data
        points_data = []
        for point in track_points:
            lat = float(point.get('lat'))
            lon = float(point.get('lon'))
            
            time_elem = point.find('gpx:time', namespaces)
            if time_elem is not None:
                dt = datetime.fromisoformat(time_elem.text.replace('Z', '+00:00'))
                timestamp = int(dt.timestamp())
            else:
                timestamp = int(datetime.now().timestamp())
            
            # Try to get speed from GPX
            speed_elem = point.find('.//gpxx:speed', namespaces)
            speed_kmh = float(speed_elem.text) * 3.6 if speed_elem is not None else None
            
            points_data.append({
                'lat': lat,
                'lon': lon,
                'timestamp': timestamp,
                'speed_kmh': speed_kmh
            })
        
        # Calculate speeds if not in GPX
        for i, point in enumerate(points_data):
            if point['speed_kmh'] is None:
                if i > 0:
                    prev = points_data[i-1]
                    distance_km = haversine_distance(prev['lat'], prev['lon'], point['lat'], point['lon'])
                    time_diff = point['timestamp'] - prev['timestamp']
                    point['speed_kmh'] = (distance_km / time_diff) * 3600 if time_diff > 0 else 0.0
                else:
                    point['speed_kmh'] = 0.0
        
        # Write CSV
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['sample_order', 'timestamp', 'latitude', 'longitude', 'speed_kmh'])
            writer.writeheader()
            for i, point in enumerate(points_data, 1):
                writer.writerow({
                    'sample_order': i,
                    'timestamp': point['timestamp'],
                    'latitude': point['lat'],
                    'longitude': point['lon'],
                    'speed_kmh': round(point['speed_kmh'], 1)
                })
        
        print(f"  ✓ Converted {len(points_data)} GPS points")
        return len(points_data)


class OSMQuery:
    """Query OpenStreetMap Overpass API for highway ramps"""
    
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    
    @staticmethod
    def get_route_bounds(route: List[Dict]) -> Tuple[float, float, float, float]:
        """Calculate bounding box of route with smart buffer based on route length"""
        if not route:
            return (0, 0, 0, 0)
        
        # Get route start and end points
        start = route[0]
        end = route[-1]
        
        # Calculate distance between start and end (Haversine)
        from math import radians, sin, cos, sqrt, atan2
        R = 6371  # Earth radius in km
        lat1, lon1 = radians(start['lat']), radians(start['lon'])
        lat2, lon2 = radians(end['lat']), radians(end['lon'])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        distance_km = 2 * R * atan2(sqrt(a), sqrt(1-a))
        
        # Create rectangle around entire route with buffer based on route length
        # Minimum 1km, maximum 10km buffer, or 30% of route distance
        buffer_km = min(max(distance_km * 0.3, 1.0), 10.0)
        buffer_deg = buffer_km / 111.0  # ~111km per degree latitude
        
        lats = [p['lat'] for p in route]
        lons = [p['lon'] for p in route]
        
        return (
            min(lats) - buffer_deg,
            min(lons) - buffer_deg,
            max(lats) + buffer_deg,
            max(lons) + buffer_deg
        )
    
    @staticmethod
    def query_osm_ramps(bbox: Tuple[float, float, float, float]) -> List[Dict]:
        """Query OSM Overpass API for highway ramps in bounding box"""
        min_lat, min_lon, max_lat, max_lon = bbox
        
        # Overpass QL query for highway ramps AND road network
        # This includes motorways, trunk roads, primary roads, and their links
        query = f"""
        [out:json][timeout:30];
        (
          way["highway"="motorway_link"]({min_lat},{min_lon},{max_lat},{max_lon});
          way["highway"="trunk_link"]({min_lat},{min_lon},{max_lat},{max_lon});
          node["highway"="motorway_junction"]({min_lat},{min_lon},{max_lat},{max_lon});
          way["highway"="motorway"]({min_lat},{min_lon},{max_lat},{max_lon});
          way["highway"="trunk"]({min_lat},{min_lon},{max_lat},{max_lon});
          way["highway"="primary"]({min_lat},{min_lon},{max_lat},{max_lon});
          way["highway"="secondary"]({min_lat},{min_lon},{max_lat},{max_lon});
        );
        out geom;
        """
        
        try:
            print(f"  Querying OSM API for region: {min_lat:.3f},{min_lon:.3f} to {max_lat:.3f},{max_lon:.3f}")
            
            # Make request
            data = urllib.parse.urlencode({'data': query}).encode('utf-8')
            req = urllib.request.Request(OSMQuery.OVERPASS_URL, data=data)
            req.add_header('User-Agent', 'HighwayRampDetector/1.0')
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
            
            # Parse results - both ramps and road network
            ramps = []
            roads = []
            
            for element in result.get('elements', []):
                tags = element.get('tags', {})
                highway_type = tags.get('highway', 'unknown')
                
                # Store road network geometry for road type detection
                if 'geometry' in element:
                    # This is a way with geometry
                    road_coords = [(node['lat'], node['lon']) for node in element['geometry']]
                    roads.append({
                        'highway_type': highway_type,
                        'coords': road_coords,
                        'name': tags.get('name', ''),
                        'ref': tags.get('ref', '')
                    })
                
                # Get ramp points (links and junctions)
                if highway_type in ['motorway_link', 'trunk_link', 'motorway_junction']:
                    # Get coordinates
                    if 'lat' in element and 'lon' in element:
                        lat, lon = element['lat'], element['lon']
                    elif 'center' in element:
                        lat, lon = element['center']['lat'], element['center']['lon']
                    elif 'geometry' in element and element['geometry']:
                        # Use first point of way geometry
                        lat, lon = element['geometry'][0]['lat'], element['geometry'][0]['lon']
                    else:
                        continue
                    
                    ramps.append({
                        'lat': lat,
                        'lon': lon,
                        'highway_type': highway_type,
                        'destination': tags.get('destination', ''),
                        'destination_ref': tags.get('destination:ref', ''),
                        'ref': tags.get('ref', ''),
                        'name': tags.get('name', ''),
                        'geometry': element.get('geometry', [])
                    })
            
            print(f"  ✓ Found {len(ramps)} ramps and {len(roads)} road segments from OSM")
            
            # Store roads for road type analysis
            OSMQuery._cached_roads = roads
            
            return ramps
            
        except Exception as e:
            print(f"  ⚠ OSM API query failed: {e}")
            print("  → Continuing with behavior-only detection")
            return []
    
    @staticmethod
    def save_osm_cache(ramps: List[Dict], cache_file: Path, bbox: Tuple[float, float, float, float]):
        """Save OSM ramps to cache file with metadata"""
        with open(cache_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'type', 'lat', 'lon', 'highway_type', 'destination', 
                'destination_ref', 'ref', 'name'
            ])
            writer.writeheader()
            for ramp in ramps:
                writer.writerow({
                    'type': 'ramp',
                    'lat': ramp['lat'],
                    'lon': ramp['lon'],
                    'highway_type': ramp['highway_type'],
                    'destination': ramp['destination'],
                    'destination_ref': ramp['destination_ref'],
                    'ref': ramp.get('ref', ''),
                    'name': ramp.get('name', '')
                })
        
        # Save bounding box metadata
        bbox_file = cache_file.parent / "osm_cache_bbox.json"
        with open(bbox_file, 'w') as f:
            json.dump({
                'bbox': bbox,
                'timestamp': int(time.time()),
                'count': len(ramps)
            }, f)
    
    @staticmethod
    def load_cached_bbox(cache_file: Path) -> Optional[Tuple[float, float, float, float]]:
        """Load cached bounding box if exists"""
        bbox_file = cache_file.parent / "osm_cache_bbox.json"
        if bbox_file.exists():
            try:
                with open(bbox_file, 'r') as f:
                    data = json.load(f)
                return tuple(data['bbox'])
            except:
                return None
        return None
    
    @staticmethod
    def route_in_cached_bbox(route_bbox: Tuple[float, float, float, float], 
                            cached_bbox: Tuple[float, float, float, float]) -> bool:
        """Check if route is fully contained in cached bounding box"""
        r_min_lat, r_min_lon, r_max_lat, r_max_lon = route_bbox
        c_min_lat, c_min_lon, c_max_lat, c_max_lon = cached_bbox
        
        return (r_min_lat >= c_min_lat and r_max_lat <= c_max_lat and
                r_min_lon >= c_min_lon and r_max_lon <= c_max_lon)


class DataLoader:
    """Load GPS route and OSM ramp data"""
    
    @staticmethod
    def load_route(csv_file: Path) -> List[Dict]:
        """Load GPS route from CSV and apply signal processing"""
        route = []
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert timestamp to datetime for processing
                timestamp = datetime.fromtimestamp(int(row['timestamp']))
                route.append({
                    'sample_order': int(row['sample_order']),
                    'timestamp': timestamp,
                    'latitude': float(row['latitude']),
                    'longitude': float(row['longitude']),
                    'speed_kmh': float(row['speed_kmh'])
                })
        
        # Apply GPS signal processing
        print("  • Applying GPS signal processing...")
        filtered_route = GPSFilter.process_gps_track(route)
        
        # Convert back to expected format
        processed_route = []
        for i, point in enumerate(filtered_route):
            processed_route.append({
                'sample_order': i + 1,  # Reindex after filtering
                'timestamp': int(point['timestamp'].timestamp()),
                'lat': point['latitude'],
                'lon': point['longitude'],
                'speed': point['speed_kmh']
            })
        
        print(f"  ✓ Processed {len(processed_route)} GPS points (filtered from {len(route)})")
        return processed_route
    
    @staticmethod
    def load_osm_ramps(csv_file: Path) -> List[Dict]:
        """Load OSM ramp infrastructure data"""
        ramps = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('type') == 'ramp' and row.get('lat'):
                    ramps.append({
                        'lat': float(row['lat']),
                        'lon': float(row['lon']),
                        'highway_type': row.get('highway_type', ''),
                        'destination': row.get('destination', ''),
                        'destination_ref': row.get('destination_ref', ''),
                    })
        return ramps
    
    @staticmethod
    def load_or_query_osm_ramps(route: List[Dict], cache_file: Path) -> List[Dict]:
        """Load OSM ramps from cache or query API if needed"""
        route_bbox = OSMQuery.get_route_bounds(route)
        
        # Check if cache exists and covers this route
        if cache_file.exists():
            cached_bbox = OSMQuery.load_cached_bbox(cache_file)
            if cached_bbox and OSMQuery.route_in_cached_bbox(route_bbox, cached_bbox):
                print("  ✓ Using cached OSM data (route within cached region)")
                return DataLoader.load_osm_ramps(cache_file)
            else:
                print("  ⓘ Route outside cached region, querying OSM API...")
        else:
            print("  ⓘ No OSM cache found, querying OSM API...")
        
        # Query API
        ramps = OSMQuery.query_osm_ramps(route_bbox)
        
        # Save to cache for future use
        if ramps:
            OSMQuery.save_osm_cache(ramps, cache_file, route_bbox)
            print(f"  ✓ Cached {len(ramps)} ramps for future use")
        
        return ramps


# ============================================================================
# MERGE DETECTION 
# ============================================================================

class RampDetector:
    
    def __init__(self, route: List[Dict], osm_ramps: List[Dict]):
        self.route = route
        self.osm_ramps = osm_ramps
        self.config = Config()
        self.osm_roads = getattr(OSMQuery, '_cached_roads', [])
        
        
        # Initialize Google Directions validator if API key is available
        self.google_validator = None
        if self.config.ENABLE_GOOGLE_VALIDATION and self.config.GOOGLE_API_KEY:
            self.google_validator = GoogleDirectionsValidator(self.config.GOOGLE_API_KEY)
            print("  • Google Directions API validation enabled")
        else:
            print("  • Google Directions API validation disabled (no API key)")
    
    def detect_merges(self) -> List[Dict]:
        """Unified merge detection - determines on-ramp vs off-ramp by road hierarchy direction"""
        merges = []
        window = self.config.ANALYSIS_WINDOW
        step_size = 5  # Check every 5th position instead of every position
        
        total_iterations = (len(self.route) - window) // step_size + 1
        print(f"  • Analyzing {total_iterations} potential merge locations (step={step_size})...")
        
        # Pre-compute road types for all points to avoid repeated OSM lookups
        print("  • Pre-computing road types for all GPS points...")
        road_types_cache = {}
        for idx, point in enumerate(self.route):
            if idx % 1000 == 0:
                print(f"    Caching road types: {idx}/{len(self.route)} points")
            road_types_cache[idx] = self._get_road_type_at_point(point)
        
        for i in range(0, len(self.route) - window, step_size):
            # Progress tracking
            if i % 500 == 0 or i == total_iterations - 1:
                progress = (i / total_iterations) * 100
                print(f"    Progress: {progress:.1f}% ({i}/{total_iterations})")
            
            mid_idx = i + window // 2
            mid_point = self.route[mid_idx]
            
            # Extend segment to capture full merge
            extended_window = window * 2  
            end_idx = min(i + extended_window, len(self.route) - 1)
            
            # REQUIRED: Detect road type changes (mandatory for detection)
            road_type_info = self._detect_road_type_change_cached(i, end_idx, road_types_cache)
            
            # Must have road type change to be considered a merge
            if not road_type_info['has_change']:
                continue
            
            # Determine merge type based on road hierarchy direction
            merge_type = self._classify_merge_type(road_type_info['types'])
            if not merge_type:
                continue  # Skip if can't classify (e.g., unknown road types)
            
            # Find nearest OSM ramp
            nearest_ramp, min_dist = self._find_nearest_ramp(mid_point)
            
            # Require OSM proximity (use stricter threshold for off-ramps)
            osm_threshold = self.config.OFFRAMP_OSM_PROXIMITY if merge_type == 'off_ramp' else self.config.ONRAMP_OSM_PROXIMITY
            has_osm = nearest_ramp and min_dist < osm_threshold
            
            if not has_osm:
                continue
            
            # Calculate bearing change
            bearing_change = self._calculate_bearing_change(i, window)
            
            # Check for significant bearing change
            min_bearing = self.config.OFFRAMP_MIN_BEARING_CHANGE if merge_type == 'off_ramp' else self.config.ONRAMP_MIN_BEARING_CHANGE
            has_bearing = bearing_change > min_bearing
            
            # Relax bearing requirement if very close to OSM ramp
            if min_dist > 0.05 and not has_bearing:
                continue
            
            # Calculate base confidence
            confidence = 0.5  # Base confidence since we have road type change
            reasons = f"{merge_type} road type change ({road_type_info['description']})"
            
            # Boost confidence based on OSM proximity
            if min_dist < 0.05:
                confidence += 0.2
                reasons += f"; very close to OSM ramp ({int(min_dist * 1000)}m)"
            elif min_dist < 0.1:
                confidence += 0.1
                reasons += f"; close to OSM ramp ({int(min_dist * 1000)}m)"
            
            # Boost confidence based on bearing change
            if bearing_change > 30:
                confidence += 0.2
                reasons += f"; significant turn ({bearing_change:.0f}°)"
            elif bearing_change > 15:
                confidence += 0.1
                reasons += f"; direction change ({bearing_change:.0f}°)"
            
            # Validate road direction
            direction_info = self._validate_road_direction(i, end_idx)
            
            # Adjust confidence based on direction validation
            if direction_info['valid']:
                confidence = min(1.0, confidence + 0.1)
                reasons += f"; {direction_info['description']}"
            else:
                confidence = max(0.0, confidence - 0.4)  # Stronger penalty for poor direction
                reasons += f"; {direction_info['description']}"
            
            # Calculate speed info for reporting (not used for detection)
            start_point = self.route[i]
            end_point = self.route[end_idx]
            speed_before = start_point.get('speed', 0)
            speed_after = end_point.get('speed', 0)
            speed_change = speed_after - speed_before
            
            # Create segment with start, middle, and end points
            merges.append({
                'segment_start': start_point['sample_order'],
                'segment_end': end_point['sample_order'],
                'sample_order': mid_point['sample_order'],  # For compatibility
                'timestamp': mid_point['timestamp'],
                'start_lat': start_point['lat'],
                'start_lon': start_point['lon'],
                'end_lat': end_point['lat'],
                'end_lon': end_point['lon'],
                'lat': mid_point['lat'],  # Midpoint for reference
                'lon': mid_point['lon'],
                'merge_type': merge_type,
                'confidence': confidence,
                'speed_before': speed_before,
                'speed_after': speed_after,
                'speed_change': speed_change,
                'bearing_change': bearing_change,
                'osm_distance_m': int(min_dist * 1000) if nearest_ramp else 9999,
                'destination': self._get_destination(nearest_ramp),
                'reasons': reasons,
                'segment_length': end_idx - i,
                'road_types': road_type_info['description']
            })
        
        # Apply deduplication first
        deduplicated_merges = self._deduplicate_ramps(merges)
        
        # Initialize Google validation fields for all merges
        for merge in deduplicated_merges:
            merge['google_validated'] = False
            merge['google_rejected'] = False
            merge['rejection_reason'] = ''
        
        # Apply Google validation if available
        if self.google_validator:
            all_merges = []
            print(f"  • Validating {len(deduplicated_merges)} merges with Google Directions API...")
            for i, merge in enumerate(deduplicated_merges):
                print(f"    Validating {merge['merge_type']} {i+1}/{len(deduplicated_merges)}...", end='\r')
                validation = self.google_validator.validate_merge_instance(merge, self.route)
                if validation['valid']:
                    merge['google_validated'] = True
                    merge['google_validation'] = validation
                    print(f"    ✓ {merge['merge_type']} {i+1} validated: {validation['reason']}")
                else:
                    merge['google_validated'] = False
                    merge['google_rejected'] = True
                    merge['rejection_reason'] = validation['reason']
                    print(f"    ✗ {merge['merge_type']} {i+1} rejected: {validation['reason']} (uses_ramps={validation.get('uses_ramps', False)}, distance_ratio={validation.get('distance_ratio', 0):.2f})")
                
                # Keep all merges, just mark validation status
                merge['google_validation'] = validation
                all_merges.append(merge)
            
            validated_count = sum(1 for merge in all_merges if merge.get('google_validated', False))
            print(f"  ✓ Google validation complete: {validated_count}/{len(all_merges)} merges validated")
            return all_merges
        
        return deduplicated_merges
    
    def _classify_merge_type(self, road_types: List[str]) -> Optional[str]:
        """Classify merge type based on road hierarchy direction"""
        if len(road_types) < 2:
            return None
        
        # Define road hierarchy (higher number = higher priority/class)
        hierarchy = {
            'motorway': 6,
            'motorway_link': 5,  # Only motorway_link counts as highway merge
            'trunk': 4,
            'trunk_link': 3,
            'primary': 2,
            'secondary': 1,
            'unknown': 0
        }
        
        # Get hierarchy values for road types
        hierarchy_values = [hierarchy.get(road_type, 0) for road_type in road_types]
        
        # Check if there's a clear hierarchy direction
        if len(set(hierarchy_values)) < 2:
            return None  # No clear hierarchy change
        
        # ONLY classify as highway merge if it involves motorway_link
        if 'motorway_link' not in road_types:
            return None  # Not a highway merge - no motorway_link involved
        
        # Find the first and last road types in the sequence
        first_road_type = road_types[0]
        last_road_type = road_types[-1]
        first_hierarchy = hierarchy.get(first_road_type, 0)
        last_hierarchy = hierarchy.get(last_road_type, 0)
        
        # Classify based on the direction of change from first to last
        if first_hierarchy < last_hierarchy:
            # Upgrading road class (lower to higher) = ON-RAMP
            return 'on_ramp'
        elif first_hierarchy > last_hierarchy:
            # Downgrading road class (higher to lower) = OFF-RAMP
            return 'off_ramp'
        else:
            # Same hierarchy level - check if there's a clear pattern in the middle
            # Look for the most significant transition in the sequence
            max_transition = 0
            transition_direction = 0
            
            for i in range(len(road_types) - 1):
                current_hierarchy = hierarchy.get(road_types[i], 0)
                next_hierarchy = hierarchy.get(road_types[i + 1], 0)
                transition = abs(next_hierarchy - current_hierarchy)
                
                if transition > max_transition:
                    max_transition = transition
                    transition_direction = next_hierarchy - current_hierarchy
            
            if transition_direction > 0:
                return 'on_ramp'  # Upward transition
            elif transition_direction < 0:
                return 'off_ramp'  # Downward transition
            else:
                return None  # Can't classify this transition
    
    def _detect_road_type_change_cached(self, start_idx: int, end_idx: int, road_types_cache: Dict) -> Dict:
        """Detect sustained road type transitions using pre-computed road types"""
        if not self.osm_roads:
            return {'has_change': False, 'types': [], 'description': ''}
        
        # Get road types for each point in the segment from cache
        point_road_types = []
        for i in range(start_idx, min(end_idx + 1, len(self.route))):
            point = self.route[i]
            road_type = road_types_cache.get(i, 'unknown')
            point_road_types.append({
                'index': i,
                'road_type': road_type,
                'timestamp': point['timestamp']
            })
        
        # Find sustained road changes (3+ consecutive points on each road type)
        sustained_changes = self._find_sustained_road_changes(point_road_types, min_consecutive_points=3)
        
        if not sustained_changes:
            return {'has_change': False, 'types': [], 'description': ''}
        
        # Get road types in sequence from sustained changes
        types_list = []
        for change in sustained_changes:
            if change['from_type'] not in types_list:
                types_list.append(change['from_type'])
            if change['to_type'] not in types_list:
                types_list.append(change['to_type'])
        
        # Highway type hierarchy (for display)
        type_names = {
            'motorway': 'Motorway',
            'motorway_link': 'Motorway Link',
            'trunk': 'Trunk Road',
            'trunk_link': 'Trunk Link',
            'primary': 'Primary Road',
            'secondary': 'Secondary Road'
        }
        
        has_change = len(types_list) > 1
        description = ' → '.join([type_names.get(t, t) for t in types_list]) if types_list else ''
        
        return {
            'has_change': has_change,
            'types': types_list,
            'description': description,
            'sustained_changes': sustained_changes
        }
    
    
    def _find_nearest_ramp(self, point: Dict) -> Tuple[Optional[Dict], float]:
        """Find nearest OSM ramp to a point"""
        nearest = None
        min_dist = float('inf')
        
        for ramp in self.osm_ramps:
            dist = haversine_distance(point['lat'], point['lon'], ramp['lat'], ramp['lon'])
            if dist < min_dist:
                min_dist = dist
                nearest = ramp
        
        return nearest, min_dist
    
    def _calculate_bearing_change(self, start_idx: int, window: int) -> float:
        """Calculate bearing change across a route segment"""
        if start_idx < 5 or start_idx + window + 5 >= len(self.route):
            return 0.0
        
        bearing_before = calculate_bearing(
            self.route[start_idx-5]['lat'], self.route[start_idx-5]['lon'],
            self.route[start_idx]['lat'], self.route[start_idx]['lon']
        )
        bearing_after = calculate_bearing(
            self.route[start_idx+window]['lat'], self.route[start_idx+window]['lon'],
            self.route[start_idx+window+5]['lat'], self.route[start_idx+window+5]['lon']
        )
        
        change = abs(bearing_after - bearing_before)
        return change if change <= 180 else 360 - change
    
    def _detect_road_type_change(self, start_idx: int, end_idx: int) -> Dict:
        """Detect sustained road type transitions in a segment using OSM data"""
        if not self.osm_roads:
            return {'has_change': False, 'types': [], 'description': ''}
        
        # Get road types for each point in the segment
        point_road_types = []
        for i in range(start_idx, min(end_idx + 1, len(self.route))):
            point = self.route[i]
            road_type = self._get_road_type_at_point(point)
            point_road_types.append({
                'index': i,
                'road_type': road_type,
                'timestamp': point['timestamp']
            })
        
        # Find sustained road changes (3+ consecutive points on each road type)
        sustained_changes = self._find_sustained_road_changes(point_road_types, min_consecutive_points=3)
        
        if not sustained_changes:
            return {'has_change': False, 'types': [], 'description': ''}
        
        # Get road types in sequence from sustained changes
        types_list = []
        for change in sustained_changes:
            if change['from_type'] not in types_list:
                types_list.append(change['from_type'])
            if change['to_type'] not in types_list:
                types_list.append(change['to_type'])
        
        # Highway type hierarchy (for display)
        type_names = {
            'motorway': 'Motorway',
            'motorway_link': 'Motorway Link',
            'trunk': 'Trunk Road',
            'trunk_link': 'Trunk Link',
            'primary': 'Primary Road',
            'secondary': 'Secondary Road'
        }
        
        has_change = len(types_list) > 1
        description = ' → '.join([type_names.get(t, t) for t in types_list]) if types_list else ''
        
        return {
            'has_change': has_change,
            'types': types_list,
            'description': description,
            'sustained_changes': sustained_changes
        }
    
    def _get_road_type_at_point(self, point: Dict) -> str:
        """Get the road type at a specific GPS point"""
        closest_road_type = 'unknown'
        min_distance = float('inf')
        
        # Find closest road within 50m
        for road in self.osm_roads:
            for road_lat, road_lon in road['coords']:
                dist = haversine_distance(point['lat'], point['lon'], road_lat, road_lon)
                if dist < 0.05 and dist < min_distance:  # Within 50m
                    min_distance = dist
                    closest_road_type = road['highway_type']
        
        return closest_road_type
    
    def _find_sustained_road_changes(self, point_road_types: List[Dict], min_consecutive_points: int = 3) -> List[Dict]:
        """Find road type changes that are sustained for minimum consecutive points on BOTH road types"""
        if len(point_road_types) < min_consecutive_points * 2:
            return []  # Need at least 6 points to have 3+ on each road type
        
        sustained_changes = []
        current_road_type = point_road_types[0]['road_type']
        road_start_index = 0
        consecutive_count = 1
        
        # Track potential transition - we need to verify both sides sustained
        potential_transition = None
        
        for i in range(1, len(point_road_types)):
            point = point_road_types[i]
            
            if point['road_type'] != current_road_type:
                # Road type changed
                
                # If we were tracking a potential transition, check if the previous road type sustained
                if potential_transition:
                    # Previous road type (the "to_type" in potential_transition) should have sustained
                    if consecutive_count >= min_consecutive_points and current_road_type != 'unknown':
                        # Both sides sustained! Record the change
                        potential_transition['to_consecutive_points'] = consecutive_count
                        sustained_changes.append(potential_transition)
                    # Clear potential transition regardless
                    potential_transition = None
                
                # Check if previous road type sustained for 3+ points
                if consecutive_count >= min_consecutive_points and current_road_type != 'unknown' and point['road_type'] != 'unknown':
                    # Previous road sustained - now track if new road also sustains
                    potential_transition = {
                        'from_type': current_road_type,
                        'to_type': point['road_type'],
                        'from_index': road_start_index,
                        'to_index': i,
                        'from_consecutive_points': consecutive_count
                    }
                
                # Start tracking new road type
                current_road_type = point['road_type']
                road_start_index = i
                consecutive_count = 1
            else:
                # Same road type - increment consecutive count
                consecutive_count += 1
        
        # Check if there's a pending potential transition at the end
        # (only if the last road type also sustained)
        if potential_transition and consecutive_count >= min_consecutive_points and current_road_type != 'unknown':
            potential_transition['to_consecutive_points'] = consecutive_count
            sustained_changes.append(potential_transition)
        
        # Final filter: Exclude motorway-to-motorway transitions and ensure both sides truly sustained
        filtered_changes = []
        for change in sustained_changes:
            # Exclude motorway-to-motorway transitions (highway interchanges)
            is_motorway_to_motorway = (
                change['from_type'] in ['motorway', 'motorway_link'] and 
                change['to_type'] in ['motorway', 'motorway_link']
            )
            
            if not is_motorway_to_motorway:
                # Verify both sides sustained (should already be true, but double-check)
                from_points = change.get('from_consecutive_points', 0)
                to_points = change.get('to_consecutive_points', 0)
                if from_points >= min_consecutive_points and to_points >= min_consecutive_points:
                    filtered_changes.append(change)
        
        return filtered_changes
    
    def _validate_road_direction(self, start_idx: int, end_idx: int) -> Dict:
        """Validate that vehicle is traveling in the correct direction for the road"""
        if not self.osm_roads:
            return {'valid': True, 'direction_match': 1.0, 'description': 'No OSM data'}
        
        # Get vehicle bearing from GPS track
        start_point = self.route[start_idx]
        end_point = self.route[end_idx]
        vehicle_bearing = calculate_bearing(
            start_point['lat'], start_point['lon'],
            end_point['lat'], end_point['lon']
        )
        
        # Find the road segment the vehicle is on
        road_segments = []
        for i in range(start_idx, min(end_idx + 1, len(self.route))):
            point = self.route[i]
            road_type = self._get_road_type_at_point(point)
            
            if road_type != 'unknown':
                # Find the specific road segment
                for road in self.osm_roads:
                    if road['highway_type'] == road_type:
                        for j in range(len(road['coords']) - 1):
                            road_start = road['coords'][j]
                            road_end = road['coords'][j + 1]
                            
                            # Check if point is close to this road segment
                            dist_to_start = haversine_distance(
                                point['lat'], point['lon'], road_start[0], road_start[1]
                            )
                            dist_to_end = haversine_distance(
                                point['lat'], point['lon'], road_end[0], road_end[1]
                            )
                            
                            if dist_to_start < 0.05 or dist_to_end < 0.05:  # Within 50m
                                road_bearing = calculate_bearing(
                                    road_start[0], road_start[1],
                                    road_end[0], road_end[1]
                                )
                                road_segments.append({
                                    'road_type': road_type,
                                    'road_bearing': road_bearing,
                                    'distance': min(dist_to_start, dist_to_end)
                                })
        
        if not road_segments:
            return {'valid': True, 'direction_match': 1.0, 'description': 'No matching road segments'}
        
        # Calculate direction alignment for each road segment
        direction_matches = []
        for segment in road_segments:
            bearing_diff = abs(vehicle_bearing - segment['road_bearing'])
            if bearing_diff > 180:
                bearing_diff = 360 - bearing_diff
            
            # Calculate match score (1.0 = perfect alignment, 0.0 = opposite direction)
            match_score = max(0, 1.0 - (bearing_diff / 90.0))  # 90 degrees = 0 score
            direction_matches.append(match_score)
        
        # Use the best match
        best_match = max(direction_matches) if direction_matches else 0.0
        avg_match = sum(direction_matches) / len(direction_matches) if direction_matches else 0.0
        
        # Stricter validation: require 0.7+ match (30 degrees tolerance) to prevent opposite lane false positives
        is_valid = best_match >= 0.7
        
        description = f"Direction match: {best_match:.2f}"
        if not is_valid:
            description += " (poor alignment - possible opposite lane)"
        
        return {
            'valid': is_valid,
            'direction_match': best_match,
            'avg_direction_match': avg_match,
            'description': description,
            'vehicle_bearing': vehicle_bearing,
            'road_bearings': [s['road_bearing'] for s in road_segments]
        }
    
    
    def _get_destination(self, ramp: Optional[Dict]) -> str:
        """Get destination name from OSM ramp"""
        if not ramp:
            return 'Behavior-detected (no OSM data)'
        return ramp['destination_ref'] or ramp['destination'] or 'Unknown'
    
    def _deduplicate_ramps(self, ramps: List[Dict]) -> List[Dict]:
        """Fix issue of duplicate detections of the same ramp, but preserve multiple highway entries in long routes"""
        unique = []
        
        # Sort by absolute speed change (highest first) to keep the most significant merge
        for ramp in sorted(ramps, key=lambda x: abs(x['speed_change']), reverse=True):
            # Check if this overlaps with any existing ramp
            is_duplicate = False
            for existing in unique:
                # Check if segments overlap
                segment_overlap = (
                    ramp['segment_start'] <= existing['segment_end'] and
                    ramp['segment_end'] >= existing['segment_start']
                )
                
                # Check proximity of start points
                start_close = abs(ramp['segment_start'] - existing['segment_start']) < self.config.DEDUPLICATION_WINDOW
                
                # Check proximity of end points
                end_close = abs(ramp['segment_end'] - existing['segment_end']) < self.config.DEDUPLICATION_WINDOW
                
                # Check proximity of midpoints
                midpoint_close = abs(ramp['sample_order'] - existing['sample_order']) < self.config.DEDUPLICATION_WINDOW
                
                # For long routes, allow multiple highway entries if they're far apart
                # Check if this is a different highway entry (different road types or far apart)
                is_different_highway_entry = False
                if existing.get('road_types') and ramp.get('road_types'):
                    # If road types are different, it's likely a different highway entry
                    if existing['road_types'] != ramp['road_types']:
                        is_different_highway_entry = True
                
                # If segments are very far apart (>500 samples), likely different highway entries
                if abs(ramp['sample_order'] - existing['sample_order']) > 500:
                    is_different_highway_entry = True
                
                # Consider duplicate only if close proximity AND not a different highway entry
                if (segment_overlap or start_close or end_close or midpoint_close) and not is_different_highway_entry:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique.append(ramp)
        
        # Re-sort by sample order for output
        return sorted(unique, key=lambda x: x['sample_order'])


# ============================================================================
# OUTPUT GENERATION
# ============================================================================

class ResultsExporter:
    """Export analysis results in various formats"""
    
    @staticmethod
    def save_csv(ramps: List[Dict], output_file: Path):
        """Save ramps to CSV"""
        if not ramps:
            print("  ⚠ No ramps detected")
            return
        
        fieldnames = [
            'segment_start', 'segment_end', 'segment_length',
            'merge_type', 'confidence', 'destination',
            'speed_before', 'speed_after', 'speed_change', 'bearing_change',
            'osm_distance_m', 
            'start_latitude', 'start_longitude',
            'end_latitude', 'end_longitude',
            'midpoint_latitude', 'midpoint_longitude',
            'road_types', 'reasons',
            'google_validated', 'google_rejected', 'rejection_reason',
            'google_uses_ramps', 'google_distance_ratio', 'google_route_distance',
            'google_detected_distance', 'google_route_steps'
        ]
        
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for ramp in ramps:
                writer.writerow({
                    'segment_start': ramp['segment_start'],
                    'segment_end': ramp['segment_end'],
                    'segment_length': ramp['segment_length'],
                    'merge_type': ramp['merge_type'],
                    'confidence': f"{ramp['confidence']:.2f}",
                    'destination': ramp['destination'],
                    'speed_before': f"{ramp['speed_before']:.1f}",
                    'speed_after': f"{ramp['speed_after']:.1f}",
                    'speed_change': f"{ramp['speed_change']:+.1f}",
                    'bearing_change': f"{ramp['bearing_change']:.0f}",
                    'osm_distance_m': ramp['osm_distance_m'],
                    'start_latitude': f"{ramp['start_lat']:.6f}",
                    'start_longitude': f"{ramp['start_lon']:.6f}",
                    'end_latitude': f"{ramp['end_lat']:.6f}",
                    'end_longitude': f"{ramp['end_lon']:.6f}",
                    'midpoint_latitude': f"{ramp['lat']:.6f}",
                    'midpoint_longitude': f"{ramp['lon']:.6f}",
                    'road_types': ramp.get('road_types', ''),
                    'reasons': ramp['reasons'],
                    'google_validated': 'True' if ramp.get('google_validated', False) else 'False',
                    'google_rejected': 'True' if ramp.get('google_rejected', False) else 'False',
                    'rejection_reason': ramp.get('rejection_reason', ''),
                    'google_uses_ramps': 'True' if ramp.get('google_validation', {}).get('uses_ramps', False) else 'False',
                    'google_distance_ratio': f"{ramp.get('google_validation', {}).get('distance_ratio', 0):.2f}",
                    'google_route_distance': ramp.get('google_validation', {}).get('google_distance', 0),
                    'google_detected_distance': ramp.get('google_validation', {}).get('detected_distance', 0),
                    'google_route_steps': ramp.get('google_validation', {}).get('route_steps', 0)
                })
    
    @staticmethod
    def save_summary(ramps: List[Dict], route_points: int, output_file: Path):
        on_ramps = [r for r in ramps if r['merge_type'] == 'on_ramp']
        off_ramps = [r for r in ramps if r['merge_type'] == 'off_ramp']
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("HIGHWAY RAMP DETECTION ANALYSIS SUMMARY\n")
            f.write("=" * 70 + "\n\n")
            
            f.write(f"Route Information:\n")
            f.write(f"  Total GPS Points: {route_points}\n")
            f.write(f"  Total Ramps Detected: {len(ramps)}\n")
            f.write(f"    - On-Ramps:  {len(on_ramps)}\n")
            f.write(f"    - Off-Ramps: {len(off_ramps)}\n\n")
            
            if on_ramps:
                f.write("On-Ramps (Entering Highway):\n")
                f.write("-" * 70 + "\n")
                for i, ramp in enumerate(on_ramps, 1):
                    f.write(f"{i}. SEGMENT: Samples {ramp['segment_start']:4d} → {ramp['segment_end']:4d} "
                           f"({ramp['segment_length']} points) | Confidence: {ramp['confidence']:.0%}\n")
                    f.write(f"   Speed: {ramp['speed_before']:.1f} → {ramp['speed_after']:.1f} km/h "
                           f"({ramp['speed_change']:+.1f} km/h)\n")
                    f.write(f"   Turn: {ramp['bearing_change']:.0f}° | OSM: {ramp['osm_distance_m']}m\n")
                    f.write(f"   Destination: {ramp['destination']}\n")
                    f.write(f"   Start: ({ramp['start_lat']:.6f}, {ramp['start_lon']:.6f})\n")
                    f.write(f"   End:   ({ramp['end_lat']:.6f}, {ramp['end_lon']:.6f})\n")
                    f.write(f"   Verification: {ramp['reasons']}\n\n")
            
            if off_ramps:
                f.write("\nOff-Ramps (Exiting Highway):\n")
                f.write("-" * 70 + "\n")
                for i, ramp in enumerate(off_ramps, 1):
                    f.write(f"{i}. SEGMENT: Samples {ramp['segment_start']:4d} → {ramp['segment_end']:4d} "
                           f"({ramp['segment_length']} points) | Confidence: {ramp['confidence']:.0%}\n")
                    f.write(f"   Speed: {ramp['speed_before']:.1f} → {ramp['speed_after']:.1f} km/h "
                           f"({ramp['speed_change']:+.1f} km/h)\n")
                    f.write(f"   Turn: {ramp['bearing_change']:.0f}° | OSM: {ramp['osm_distance_m']}m\n")
                    f.write(f"   Destination: {ramp['destination']}\n")
                    f.write(f"   Start: ({ramp['start_lat']:.6f}, {ramp['start_lon']:.6f})\n")
                    f.write(f"   End:   ({ramp['end_lat']:.6f}, {ramp['end_lon']:.6f})\n")
                    f.write(f"   Verification: {ramp['reasons']}\n\n")
            
            f.write("=" * 70 + "\n")
            f.write("Detection Methodology:\n")
            f.write("  • Multi-layered analysis combining:\n")
            f.write("    - GPS speed pattern analysis\n")
            f.write("    - Road geometry (bearing changes)\n")
            f.write("    - OpenStreetMap infrastructure verification\n")
            f.write("  • On-ramps: Can be detected without OSM (behavior-only)\n")
            f.write("  • Off-ramps: Require OSM proximity (well-mapped infrastructure)\n")
            f.write("=" * 70 + "\n")


# ============================================================================
# MAIN ANALYSIS PIPELINE
# ============================================================================

def main():
    """Main analysis pipeline"""
    print("\n" + "=" * 70)
    print("HIGHWAY RAMP DETECTION SYSTEM")
    print("=" * 70 + "\n")
    
    # Setup
    print("1. Setting up directories...")
    setup_directories()
    print("   ✓ Directories ready\n")
    
    # Find input files
    print("2. Locating input files...")
    gpx_files = list(Config.INPUT_DIR.glob("*.gpx"))
    
    if not gpx_files:
        print("   ✗ No GPX files found in input/ directory")
        print("   → Place your GPS track (.gpx file) in the 'input/' folder")
        return
    
    gpx_file = gpx_files[0]
    print(f"   ✓ Found: {gpx_file.name}\n")
    
    # Convert GPX to CSV
    print("3. Converting GPS data...")
    route_csv = Config.DATA_DIR / "gps_route.csv"
    num_points = GPXConverter.convert(gpx_file, route_csv)
    print()
    
    # Load data
    print("4. Loading data...")
    route = DataLoader.load_route(route_csv)
    print(f"   ✓ Loaded {len(route)} GPS points")
    
    osm_ramps_file = Config.DATA_DIR / "osm_ramps.csv"
    print("\n   Loading OSM highway ramp infrastructure...")
    osm_ramps = DataLoader.load_or_query_osm_ramps(route, osm_ramps_file)
    print(f"   ✓ Loaded {len(osm_ramps)} OSM ramps")
    print()
    
    # Detect ramps
    print("5. Analyzing highway ramps...")
    detector = RampDetector(route, osm_ramps)
    
    print("   Detecting merges (on-ramps and off-ramps)...")
    all_merges = detector.detect_merges()
    
    # Separate on-ramps and off-ramps for reporting
    on_ramps = [merge for merge in all_merges if merge['merge_type'] == 'on_ramp']
    off_ramps = [merge for merge in all_merges if merge['merge_type'] == 'off_ramp']
    
    print(f"   ✓ Found {len(on_ramps)} on-ramp(s) and {len(off_ramps)} off-ramp(s)")
    print()
    
    # Combine results
    all_ramps = sorted(on_ramps + off_ramps, key=lambda x: x['sample_order'])
    
    # Export results
    print("6. Generating results...")
    ResultsExporter.save_csv(all_ramps, Config.OUTPUT_DIR / "ramps_detected.csv")
    print(f"   ✓ Saved CSV: output/ramps_detected.csv")
    
    ResultsExporter.save_summary(all_ramps, num_points, Config.OUTPUT_DIR / "analysis_summary.txt")
    print(f"   ✓ Saved Summary: output/analysis_summary.txt")
    print()
    
    # Final summary
    print("=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"\nDetected {len(all_ramps)} highway ramps:")
    print(f"  • {len(on_ramps)} on-ramps  (entering highway)")
    print(f"  • {len(off_ramps)} off-ramps (exiting highway)")
    print(f"\nResults saved to 'output/' directory")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

