#!/usr/bin/env python3
"""
Test Google Directions API validation against Realroute merges
These merges are confirmed correct by the user, so we can verify
the Google API is working properly.
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


def load_ramps(ramps_file: Path):
    """Load detected ramps from CSV"""
    ramps = []
    with open(ramps_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ramps.append({
                'segment_start': int(row['segment_start']),
                'segment_end': int(row['segment_end']),
                'segment_length': int(row['segment_length']),
                'merge_type': row['merge_type'],
                'confidence': float(row['confidence']),
                'destination': row['destination'],
                'start_lat': float(row['start_latitude']),
                'start_lon': float(row['start_longitude']),
                'end_lat': float(row['end_latitude']),
                'end_lon': float(row['end_longitude']),
                'osm_distance_m': int(row['osm_distance_m']),
                'reasons': row['reasons']
            })
    return ramps


def test_realroute_validation():
    """Test Google validation against Realroute merges"""
    
    # Check for API key
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("❌ ERROR: GOOGLE_MAPS_API_KEY not found in environment variables")
        print("   Make sure .env file exists with GOOGLE_MAPS_API_KEY set")
        return False
    
    print("=" * 70)
    print("TESTING GOOGLE DIRECTIONS API VALIDATION")
    print("Using Realroute merges (confirmed correct by user)")
    print("=" * 70)
    print()
    
    # Load data
    base_dir = Path(__file__).parent.parent
    gps_file = base_dir / 'output' / 'batch' / 'results' / 'Realroute' / 'Realroute_gps_route.csv'
    ramps_file = base_dir / 'output' / 'batch' / 'results' / 'Realroute' / 'Realroute_ramps.csv'
    
    if not gps_file.exists():
        print(f"❌ ERROR: GPS file not found: {gps_file}")
        return False
    
    if not ramps_file.exists():
        print(f"❌ ERROR: Ramps file not found: {ramps_file}")
        return False
    
    print(f"✓ Loading GPS route from: {gps_file.name}")
    route = load_route(gps_file)
    print(f"  Loaded {len(route)} GPS points")
    print()
    
    print(f"✓ Loading ramps from: {ramps_file.name}")
    ramps = load_ramps(ramps_file)
    print(f"  Loaded {len(ramps)} ramps")
    print()
    
    # Initialize validator
    print(f"✓ Initializing Google Directions API validator")
    validator = GoogleDirectionsValidator(api_key)
    print()
    
    # Test each ramp
    print("=" * 70)
    print("VALIDATING MERGES")
    print("=" * 70)
    print()
    
    all_passed = True
    
    for i, ramp in enumerate(ramps, 1):
        merge_type = ramp['merge_type']
        merge_label = 'On-Ramp' if merge_type == 'on_ramp' else 'Off-Ramp'
        
        print(f"[{i}/{len(ramps)}] Testing {merge_label}")
        print(f"  Segment: {ramp['segment_start']} → {ramp['segment_end']} ({ramp['segment_length']} points)")
        print(f"  Destination: {ramp['destination']}")
        print(f"  Confidence: {ramp['confidence']:.2f}")
        print(f"  Start: ({ramp['start_lat']:.6f}, {ramp['start_lon']:.6f})")
        print(f"  End:   ({ramp['end_lat']:.6f}, {ramp['end_lon']:.6f})")
        print()
        print("  Querying Google Directions API...")
        
        # Validate
        validation = validator.validate_merge_instance(ramp, route)
        
        # Display results
        print()
        print(f"  Validation Result:")
        print(f"    Valid: {validation['valid']}")
        print(f"    Uses Ramps: {validation.get('uses_ramps', False)}")
        print(f"    Distance Valid: {validation.get('distance_valid', False)}")
        print(f"    Distance Ratio: {validation.get('distance_ratio', 0):.2f}")
        print(f"    Detected Distance: {validation.get('detected_distance', 0):.0f}m")
        print(f"    Google Distance: {validation.get('google_distance', 0):.0f}m")
        print(f"    Route Steps: {validation.get('route_steps', 0)}")
        print(f"    Reason: {validation['reason']}")
        print()
        
        # Check if validation passed
        if validation['valid']:
            print(f"  ✓ PASS: {merge_label} correctly validated")
        else:
            print(f"  ✗ FAIL: {merge_label} was rejected")
            print(f"     Expected: Should be valid (confirmed correct by user)")
            all_passed = False
        
        print()
        print("-" * 70)
        print()
    
    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if all_passed:
        print("✓ ALL TESTS PASSED")
        print("  Google Directions API is working correctly!")
        print("  Validation logic correctly identifies confirmed ramps.")
    else:
        print("✗ SOME TESTS FAILED")
        print("  Google validation rejected some confirmed ramps.")
        print("  This may indicate:")
        print("  - API is not detecting ramp maneuvers correctly")
        print("  - Validation logic needs adjustment")
        print("  - Route query parameters need tuning")
    
    print()
    return all_passed


if __name__ == '__main__':
    success = test_realroute_validation()
    sys.exit(0 if success else 1)

