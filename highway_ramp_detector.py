#!/usr/bin/env python3
"""
Highway Ramp Detection System
=============================

Professional-grade highway on-ramp and off-ramp detection using multi-layered analysis:
- GPS speed pattern analysis
- Road geometry (bearing change detection)
- OpenStreetMap infrastructure verification

Author: AI Assistant
Version: 1.0.0
License: MIT
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
    ONRAMP_START_SPEED_MAX = 40     # km/h
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
    ANALYSIS_WINDOW = 20  # Number of GPS points to analyze
    DEDUPLICATION_WINDOW = 100  # Points within this are considered same ramp


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
        """Load GPS route from CSV"""
        route = []
        with open(csv_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                route.append({
                    'sample_order': int(row['sample_order']),
                    'timestamp': int(row['timestamp']),
                    'lat': float(row['latitude']),
                    'lon': float(row['longitude']),
                    'speed': float(row['speed_kmh'])
                })
        return route
    
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
# DETECTION ALGORITHMS
# ============================================================================

class RampDetector:
    """Main detection engine for highway ramps"""
    
    def __init__(self, route: List[Dict], osm_ramps: List[Dict]):
        self.route = route
        self.osm_ramps = osm_ramps
        self.config = Config()
        self.osm_roads = getattr(OSMQuery, '_cached_roads', [])
    
    def detect_on_ramps(self) -> List[Dict]:
        """Detect highway on-ramps using layered analysis"""
        on_ramps = []
        window = self.config.ANALYSIS_WINDOW
        
        for i in range(len(self.route) - window):
            # Calculate speed changes
            speeds_before = [self.route[j]['speed'] for j in range(max(0, i-10), i)]
            speeds_after = [self.route[j]['speed'] for j in range(i+window, min(len(self.route), i+window+10))]
            
            if not speeds_before or not speeds_after:
                continue
            
            avg_before = sum(speeds_before) / len(speeds_before)
            avg_after = sum(speeds_after) / len(speeds_after)
            speed_increase = avg_after - avg_before
            
            # Check if matches on-ramp pattern
            if (speed_increase > self.config.ONRAMP_MIN_SPEED_INCREASE and 
                avg_before < self.config.ONRAMP_START_SPEED_MAX and 
                avg_after > self.config.ONRAMP_END_SPEED_MIN):
                
                mid_idx = i + window // 2
                mid_point = self.route[mid_idx]
                
                # Find nearest OSM ramp
                nearest_ramp, min_dist = self._find_nearest_ramp(mid_point)
                
                # Calculate bearing change
                bearing_change = self._calculate_bearing_change(i, window)
                
                # MANDATORY: Require OSM proximity (just like off-ramps)
                has_osm = nearest_ramp and min_dist < self.config.ONRAMP_OSM_PROXIMITY
                
                if not has_osm:
                    continue
                
                # Also check for significant bearing change
                has_bearing = bearing_change > self.config.ONRAMP_MIN_BEARING_CHANGE
                
                # Relax bearing requirement if very close to OSM ramp
                if min_dist > 0.05 and not has_bearing:
                    continue
                
                # Calculate confidence and reasons
                confidence, reasons = self._calculate_onramp_confidence(
                    speed_increase, avg_after, bearing_change, nearest_ramp, min_dist
                )
                
                # Extend on-ramp segment to capture full merge onto highway
                # On-ramps take longer as you need to accelerate and merge into traffic
                extended_window = window * 2  # Double the window for on-ramps
                end_idx = min(i + extended_window, len(self.route) - 1)
                
                # Detect road type changes
                road_type_info = self._detect_road_type_change(i, end_idx)
                
                # Boost confidence if road type change detected
                if road_type_info['has_change']:
                    confidence = min(1.0, confidence + 0.15)
                    reasons += f"; crosses road types ({road_type_info['description']})"
                
                # Create segment with start, middle, and end points
                start_point = self.route[i]
                end_point = self.route[end_idx]
                
                on_ramps.append({
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
                    'merge_type': 'on_ramp',
                    'confidence': confidence,
                    'speed_before': avg_before,
                    'speed_after': avg_after,
                    'speed_change': speed_increase,
                    'bearing_change': bearing_change,
                    'osm_distance_m': int(min_dist * 1000) if nearest_ramp else 9999,
                    'destination': self._get_destination(nearest_ramp),
                    'reasons': reasons,
                    'segment_length': end_idx - i,
                    'road_types': road_type_info['description']
                })
        
        return self._deduplicate_ramps(on_ramps)
    
    def detect_off_ramps(self) -> List[Dict]:
        """Detect highway off-ramps using layered analysis"""
        off_ramps = []
        window = self.config.ANALYSIS_WINDOW
        extended_window = window * 2  # Match on-ramp segment length
        
        for i in range(len(self.route) - window):
            # Calculate speed changes
            speeds_before = [self.route[j]['speed'] for j in range(max(0, i-10), i)]
            speeds_after = [self.route[j]['speed'] for j in range(i+window, min(len(self.route), i+window+10))]
            
            if not speeds_before or not speeds_after:
                continue
            
            avg_before = sum(speeds_before) / len(speeds_before)
            avg_after = sum(speeds_after) / len(speeds_after)
            speed_decrease = avg_before - avg_after
            
            # Check if matches off-ramp pattern (basic deceleration from elevated speed)
            if (speed_decrease > 20 and avg_before > self.config.OFFRAMP_START_SPEED_MIN):
                
                mid_idx = i + window // 2
                mid_point = self.route[mid_idx]
                
                # Find nearest OSM ramp
                nearest_ramp, min_dist = self._find_nearest_ramp(mid_point)
                
                # OFF-RAMPS REQUIRE OSM PROXIMITY (well-mapped in OSM)
                if not nearest_ramp or min_dist > self.config.OFFRAMP_OSM_PROXIMITY:
                    continue
                
                # Calculate bearing change
                bearing_change = self._calculate_bearing_change(i, window)
                
                # Calculate confidence and reasons (considers speed_after and decel magnitude)
                confidence, reasons = self._calculate_offramp_confidence(
                    speed_decrease, avg_before, avg_after, bearing_change, min_dist
                )
                
                # Extend off-ramp segment to match on-ramp length
                end_idx = min(i + extended_window, len(self.route) - 1)
                
                # Detect road type changes
                road_type_info = self._detect_road_type_change(i, end_idx)
                
                # Boost confidence if road type change detected
                if road_type_info['has_change']:
                    confidence = min(1.0, confidence + 0.15)
                    reasons += f"; crosses road types ({road_type_info['description']})"
                
                # Create segment with start, middle, and end points
                start_point = self.route[i]
                end_point = self.route[end_idx]
                
                off_ramps.append({
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
                    'merge_type': 'off_ramp',
                    'confidence': confidence,
                    'speed_before': avg_before,
                    'speed_after': avg_after,
                    'speed_change': -speed_decrease,
                    'bearing_change': bearing_change,
                    'osm_distance_m': int(min_dist * 1000),
                    'destination': self._get_destination(nearest_ramp),
                    'reasons': reasons,
                    'segment_length': end_idx - i,
                    'road_types': road_type_info['description']
                })
        
        return self._deduplicate_ramps(off_ramps)
    
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
        """Detect road type transitions in a segment using OSM data"""
        if not self.osm_roads:
            return {'has_change': False, 'types': [], 'description': ''}
        
        road_types_found = set()
        
        # Check each point in the segment against OSM roads
        for i in range(start_idx, min(end_idx + 1, len(self.route))):
            point = self.route[i]
            
            # Find nearby roads (within 50m)
            for road in self.osm_roads:
                for road_lat, road_lon in road['coords']:
                    dist = haversine_distance(point['lat'], point['lon'], road_lat, road_lon)
                    if dist < 0.05:  # Within 50m
                        road_types_found.add(road['highway_type'])
                        break
        
        types_list = sorted(list(road_types_found))
        
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
            'description': description
        }
    
    def _calculate_onramp_confidence(self, speed_increase: float, avg_after: float,
                                     bearing_change: float, nearest_ramp: Optional[Dict], 
                                     min_dist: float) -> Tuple[float, str]:
        """Calculate confidence score and reasons for on-ramp detection"""
        confidence = 0.0
        reasons = []
        
        if speed_increase > 40:
            confidence += 0.4
            reasons.append(f'strong acceleration (+{speed_increase:.1f} km/h)')
        else:
            confidence += 0.2
            reasons.append(f'acceleration (+{speed_increase:.1f} km/h)')
        
        if avg_after > 70:
            confidence += 0.2
            reasons.append('reaches highway speed')
        
        if bearing_change > 30:
            confidence += 0.3
            reasons.append(f'significant turn ({bearing_change:.0f}°)')
        elif bearing_change > 15:
            confidence += 0.1
            reasons.append(f'direction change ({bearing_change:.0f}°)')
        
        if nearest_ramp and min_dist < 0.3:
            confidence += 0.2
            reasons.append(f'OSM ramp {int(min_dist*1000)}m away')
        
        return min(1.0, confidence), '; '.join(reasons)
    
    def _calculate_offramp_confidence(self, speed_decrease: float, avg_before: float,
                                      avg_after: float, bearing_change: float, osm_dist: float) -> Tuple[float, str]:
        """Calculate confidence score and reasons for off-ramp detection"""
        confidence = 0.0
        reasons = []
        
        # Higher confidence for stronger deceleration
        if speed_decrease > 40:
            confidence += 0.4
            reasons.append(f'strong deceleration (-{speed_decrease:.1f} km/h)')
        elif speed_decrease > 30:
            confidence += 0.3
            reasons.append(f'deceleration (-{speed_decrease:.1f} km/h)')
        else:
            confidence += 0.15
            reasons.append(f'minor deceleration (-{speed_decrease:.1f} km/h)')
        
        # Higher confidence if starting from highway speed
        if avg_before > 90:
            confidence += 0.3
            reasons.append('from highway speed')
        elif avg_before > 70:
            confidence += 0.2
            reasons.append('from elevated speed')
        
        # PENALIZE if stopping completely (likely intersection, not clean off-ramp)
        if avg_after < 5:
            confidence -= 0.3
            reasons.append('stops completely (possible intersection)')
        # Boost if ending at ramp speed (typical off-ramp pattern)
        elif 20 < avg_after < 60:
            confidence += 0.2
            reasons.append('ends at ramp speed')
        
        if bearing_change > 30:
            confidence += 0.3
            reasons.append(f'significant turn ({bearing_change:.0f}°)')
        elif bearing_change > 15:
            confidence += 0.1
            reasons.append(f'direction change ({bearing_change:.0f}°)')
        
        if osm_dist < 0.1:
            confidence += 0.3
            reasons.append(f'OSM ramp {int(osm_dist*1000)}m away')
        else:
            confidence += 0.2
            reasons.append(f'OSM ramp {int(osm_dist*1000)}m away')
        
        return min(1.0, confidence), '; '.join(reasons)
    
    def _get_destination(self, ramp: Optional[Dict]) -> str:
        """Get destination name from OSM ramp"""
        if not ramp:
            return 'Behavior-detected (no OSM data)'
        return ramp['destination_ref'] or ramp['destination'] or 'Unknown'
    
    def _deduplicate_ramps(self, ramps: List[Dict]) -> List[Dict]:
        """Remove duplicate detections of the same ramp, keeping the one with greatest speed change"""
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
                
                # Consider duplicate if ANY proximity check matches
                if segment_overlap or start_close or end_close or midpoint_close:
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
            'road_types', 'reasons'
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
                    'reasons': ramp['reasons']
                })
    
    @staticmethod
    def save_summary(ramps: List[Dict], route_points: int, output_file: Path):
        """Generate human-readable summary"""
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
    
    print("   Detecting on-ramps...")
    on_ramps = detector.detect_on_ramps()
    print(f"   ✓ Found {len(on_ramps)} on-ramp(s)")
    
    print("   Detecting off-ramps...")
    off_ramps = detector.detect_off_ramps()
    print(f"   ✓ Found {len(off_ramps)} off-ramp(s)")
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

