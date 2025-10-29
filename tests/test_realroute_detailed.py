#!/usr/bin/env python3
"""
Detailed test of Google Directions API - shows raw responses
"""

import sys
import csv
import json
from pathlib import Path

# Add core directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))

from highway_ramp_detector import GoogleDirectionsValidator
from dotenv import load_dotenv
import os
import requests

# Load environment variables
load_dotenv()


def query_google_directions(start: str, end: str, api_key: str):
    """Query Google Directions API and return raw response"""
    base_url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        'origin': start,
        'destination': end,
        'key': api_key,
        'mode': 'driving'
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None


def analyze_google_response(response: dict):
    """Analyze Google Directions response in detail"""
    if not response or 'routes' not in response:
        print("  No routes found in response")
        return
    
    route = response['routes'][0]
    leg = route['legs'][0]
    steps = leg['steps']
    
    print(f"  Route Overview:")
    print(f"    Total Distance: {leg['distance']['text']}")
    print(f"    Total Duration: {leg['duration']['text']}")
    print(f"    Number of Steps: {len(steps)}")
    print()
    
    print(f"  Route Steps (checking for ramp maneuvers):")
    print()
    
    ramp_maneuvers = ['ramp-right', 'ramp-left', 'merge', 'fork-right', 'fork-left', 'exit-right', 'exit-left']
    found_ramps = False
    
    for i, step in enumerate(steps, 1):
        maneuver = step.get('maneuver', '')
        html_instructions = step.get('html_instructions', '')
        distance = step.get('distance', {}).get('text', '')
        
        print(f"    Step {i}:")
        print(f"      Maneuver: {maneuver if maneuver else '(none)'}")
        print(f"      Distance: {distance}")
        print(f"      Instruction: {html_instructions[:80]}...")
        
        if maneuver in ramp_maneuvers:
            print(f"      ✓ RAMP DETECTED: {maneuver}")
            found_ramps = True
        elif 'ramp' in html_instructions.lower() or 'exit' in html_instructions.lower() or 'merge' in html_instructions.lower():
            print(f"      ⚠ Ramp keywords in instruction (but no maneuver field)")
        
        print()
    
    if not found_ramps:
        print(f"    ✗ No ramp maneuvers found in any step")
        print(f"      Available maneuvers: {[s.get('maneuver', '(none)') for s in steps]}")
    else:
        print(f"    ✓ Found ramp maneuver(s)")


def test_off_ramp_detail():
    """Test the off-ramp that failed validation"""
    
    api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    if not api_key:
        print("❌ ERROR: GOOGLE_MAPS_API_KEY not found")
        return
    
    print("=" * 70)
    print("DETAILED ANALYSIS: OFF-RAMP (Failed Validation)")
    print("=" * 70)
    print()
    
    # Off-ramp coordinates from Realroute
    start = "45.433381,-75.603576"
    end = "45.433936,-75.607909"
    
    print(f"Start: {start}")
    print(f"End: {end}")
    print()
    print("Querying Google Directions API...")
    print()
    
    response = query_google_directions(start, end, api_key)
    
    if not response:
        print("❌ Failed to get response")
        return
    
    if response.get('status') != 'OK':
        print(f"❌ API Error: {response.get('status')}")
        print(f"   {response.get('error_message', 'No error message')}")
        return
    
    print("=" * 70)
    print("RAW GOOGLE RESPONSE ANALYSIS")
    print("=" * 70)
    print()
    
    analyze_google_response(response)
    
    print()
    print("=" * 70)
    print("FULL RESPONSE (JSON)")
    print("=" * 70)
    print()
    print(json.dumps(response, indent=2)[:2000])  # First 2000 chars
    if len(json.dumps(response, indent=2)) > 2000:
        print("\n... (truncated)")
    print()


if __name__ == '__main__':
    test_off_ramp_detail()

