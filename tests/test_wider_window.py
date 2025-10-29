#!/usr/bin/env python3
"""
Test Google validation with wider window around off-ramp detection
"""

import sys
import csv
from pathlib import Path

# Add core directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))

from highway_ramp_detector import GoogleDirectionsValidator
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()


def load_route(gps_file: Path):
    """Load GPS route from CSV"""
    route = []
    with open(gps_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            route.append({
                'lat': float(row['latitude']),
                'lon': float(row['longitude']),
                'speed': float(row['speed_kmh']),
                'sample': int(row['sample_order'])
            })
    return route


def test_wider_window_validation():
    """Test Google validation with wider window around off-ramp"""
    
    # Check for API key
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("❌ ERROR: GOOGLE_MAPS_API_KEY not found in environment variables")
        return False
    
    print("=" * 70)
    print("TESTING WIDER WINDOW VALIDATION")
    print("Using Realroute off-ramp with extended start/end points")
    print("=" * 70)
    print()
    
    # Load data
    base_dir = Path(__file__).parent.parent
    gps_file = base_dir / 'output' / 'batch' / 'results' / 'Realroute' / 'Realroute_gps_route.csv'
    
    if not gps_file.exists():
        print(f"❌ ERROR: GPS file not found: {gps_file}")
        return False
    
    print(f"✓ Loading GPS route from: {gps_file.name}")
    route = load_route(gps_file)
    print(f"  Loaded {len(route)} GPS points")
    print()
    
    # Original off-ramp segment (samples 403-443)
    original_start = 403
    original_end = 443
    
    print(f"Original off-ramp segment: {original_start} → {original_end}")
    print(f"Original start: ({route[original_start-1]['lat']:.6f}, {route[original_start-1]['lon']:.6f})")
    print(f"Original end:   ({route[original_end-1]['lat']:.6f}, {route[original_end-1]['lon']:.6f})")
    print()
    
    # Test different window sizes
    window_sizes = [20, 50, 100, 150, 200]
    
    validator = GoogleDirectionsValidator(api_key)
    
    for window in window_sizes:
        print(f"=" * 70)
        print(f"TESTING WINDOW SIZE: ±{window} samples")
        print(f"=" * 70)
        print()
        
        # Calculate wider window
        wider_start = max(0, original_start - window)
        wider_end = min(len(route), original_end + window)
        
        print(f"Wider window: {wider_start} → {wider_end} ({wider_end - wider_start} samples)")
        print(f"Start: ({route[wider_start]['lat']:.6f}, {route[wider_start]['lon']:.6f})")
        print(f"End:   ({route[wider_end-1]['lat']:.6f}, {route[wider_end-1]['lon']:.6f})")
        print()
        
        # Create merge data for wider window
        merge_data = {
            'segment_start': wider_start,
            'segment_end': wider_end,
            'merge_type': 'off_ramp',
            'start_lat': route[wider_start]['lat'],
            'start_lon': route[wider_start]['lon'],
            'end_lat': route[wider_end-1]['lat'],
            'end_lon': route[wider_end-1]['lon'],
            'osm_distance_m': 8  # From original detection
        }
        
        print("Querying Google Directions API...")
        validation = validator.validate_merge_instance(merge_data, route)
        
        print()
        print(f"Validation Result:")
        print(f"  Valid: {validation['valid']}")
        print(f"  Uses Ramps: {validation.get('uses_ramps', False)}")
        print(f"  Distance Valid: {validation.get('distance_valid', False)}")
        print(f"  Distance Ratio: {validation.get('distance_ratio', 0):.2f}")
        print(f"  Detected Distance: {validation.get('detected_distance', 0):.0f}m")
        print(f"  Google Distance: {validation.get('google_distance', 0):.0f}m")
        print(f"  Route Steps: {validation.get('route_steps', 0)}")
        print(f"  Has OSM Fallback: {validation.get('has_osm_fallback', False)}")
        print(f"  Reason: {validation['reason']}")
        print()
        
        if validation['valid']:
            print(f"  ✓ SUCCESS: Off-ramp validated with ±{window} window")
        else:
            print(f"  ✗ FAILED: Off-ramp rejected with ±{window} window")
        
        print()
        print("-" * 70)
        print()
    
    return True


if __name__ == '__main__':
    test_wider_window_validation()
