#!/usr/bin/env python3
"""
Convert q01 CSV file to the format expected by the highway merge detector
"""
import csv
import math
from datetime import datetime
from pathlib import Path

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two GPS points in kilometers"""
    R = 6371  # Earth radius in km
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

def convert_q01_to_detector_format(input_file, output_file):
    """Convert q01 CSV to the format expected by the highway merge detector"""
    print(f"Converting {input_file} to detector format...")
    
    # Group points by trip_id
    trips_data = {}  # {trip_id: [points]}
    valid_points = 0
    
    with open(input_file, 'r') as f:
        reader = csv.DictReader(f)
        
        for row in reader:
            # Extract GPS coordinates
            lat = float(row['Latitude'])
            lon = float(row['Longitude'])
            
            # Skip invalid coordinates (0,0)
            if lat == 0 and lon == 0:
                continue
                
            # Extract Trip column (trip_id)
            try:
                trip_id = int(row['Trip'])
            except (ValueError, KeyError):
                trip_id = 1  # Default to trip 1 if missing
            
            # Extract timestamp components
            year = int(row['Year'])
            month = int(row['Month'])
            day = int(row['Day'])
            hour = int(row['Hour'])
            minute = int(row['Minute'])
            second = int(row['Second'])
            
            # Create datetime and convert to timestamp
            dt = datetime(year, month, day, hour, minute, second)
            timestamp = int(dt.timestamp())
            
            # Extract speed from V_GPS column (convert from m/s to km/h if needed)
            try:
                speed_kmh = float(row['V_GPS'])
                # If speed seems to be in m/s (typical range 0-50), convert to km/h
                if speed_kmh < 100:  # Likely m/s
                    speed_kmh *= 3.6
            except (ValueError, KeyError):
                speed_kmh = 0.0
            
            # Group by trip_id
            if trip_id not in trips_data:
                trips_data[trip_id] = []
            
            trips_data[trip_id].append({
                'lat': lat,
                'lon': lon,
                'timestamp': timestamp,
                'speed_kmh': speed_kmh
            })
            valid_points += 1
    
    # Process each trip separately: calculate speeds and maintain chronological order
    all_points = []  # Will store all points with trip_id for final output
    total_points = 0
    
    # Sort trips by trip_id to maintain order
    for trip_id in sorted(trips_data.keys()):
        trip_points = trips_data[trip_id]
        
        # Sort points within trip by timestamp to ensure chronological order
        trip_points.sort(key=lambda p: p['timestamp'])
        
        # Calculate speeds within each trip
        for i, point in enumerate(trip_points):
            if i > 0:
                prev = trip_points[i-1]
                distance_km = haversine_distance(
                    prev['lat'], prev['lon'], 
                    point['lat'], point['lon']
                )
                time_diff = point['timestamp'] - prev['timestamp']
                
                if time_diff > 0:
                    calculated_speed = (distance_km / time_diff) * 3600
                    # Use calculated speed if it's reasonable, otherwise keep original
                    if 0 <= calculated_speed <= 200:  # Reasonable speed range
                        point['speed_kmh'] = calculated_speed
                    else:
                        point['speed_kmh'] = max(0, point['speed_kmh'])
                else:
                    point['speed_kmh'] = 0.0
            else:
                point['speed_kmh'] = 0.0
            
            # Add trip_id to point for output
            point['trip_id'] = trip_id
            all_points.append(point)
            total_points += 1
        
        print(f"  Trip {trip_id}: {len(trip_points)} points")
    
    # Write converted CSV with trip_id and per-trip sample_order
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['trip_id', 'sample_order', 'timestamp', 'latitude', 'longitude', 'speed_kmh'])
        writer.writeheader()
        
        # Track sample_order per trip
        current_trip_id = None
        sample_order = 0
        
        for point in all_points:
            # Reset sample_order when trip_id changes
            if current_trip_id != point['trip_id']:
                sample_order = 1
                current_trip_id = point['trip_id']
            else:
                sample_order += 1
            
            writer.writerow({
                'trip_id': point['trip_id'],
                'sample_order': sample_order,
                'timestamp': point['timestamp'],
                'latitude': point['lat'],
                'longitude': point['lon'],
                'speed_kmh': round(point['speed_kmh'], 1)
            })
    
    print(f"✓ Converted {total_points} GPS points across {len(trips_data)} trips to {output_file}")
    if all_points:
        print(f"  Time range: {datetime.fromtimestamp(all_points[0]['timestamp'])} to {datetime.fromtimestamp(all_points[-1]['timestamp'])}")
        print(f"  Speed range: {min(p['speed_kmh'] for p in all_points):.1f} - {max(p['speed_kmh'] for p in all_points):.1f} km/h")
    
    return total_points

if __name__ == "__main__":
    input_file = Path("input/otherdata/q01_1012_Y1m6-00b.csv")
    output_file = Path("input/otherdata/q01_converted.csv")
    
    if not input_file.exists():
        print(f"Error: Input file {input_file} not found!")
        exit(1)
    
    num_points = convert_q01_to_detector_format(input_file, output_file)
    print(f"\nConversion complete! {num_points} points ready for processing.")
