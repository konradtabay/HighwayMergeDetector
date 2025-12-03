#!/usr/bin/env python3
"""Run highway merge detection on all q01 files"""
import sys
# Force unbuffered output for real-time logging
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

from core.highway_ramp_detector import DataLoader, RampDetector, ResultsExporter, Config
from pathlib import Path

files = [
    'input/q01_1012_Y6m6-00b_converted.csv',
    'input/q01_1012_Y7A-00b_converted.csv',
    'input/q01_1012_Y7m6-00b_converted.csv',
]

for csv_file in files:
    csv_path = Path(csv_file)
    if not csv_path.exists():
        print(f'⚠️  {csv_file} not found, skipping...')
        continue
    
    print(f'\n{"="*70}', flush=True)
    print(f'Processing: {csv_path.name}', flush=True)
    print(f'{"="*70}\n', flush=True)
    
    route = DataLoader.load_route(csv_path)
    print(f'✓ Loaded {len(route)} GPS points\n', flush=True)
    
    osm_cache = Config.DATA_DIR / 'osm_ramps.csv'
    osm_ramps = DataLoader.load_or_query_osm_ramps(route, osm_cache)
    print(f'✓ Loaded {len(osm_ramps)} OSM ramps\n', flush=True)
    
    detector = RampDetector(route, osm_ramps)
    all_merges = detector.detect_merges()
    
    on_ramps = [m for m in all_merges if m['merge_type'] == 'on_ramp']
    off_ramps = [m for m in all_merges if m['merge_type'] == 'off_ramp']
    highway_merges = [m for m in all_merges if m['merge_type'] == 'highway_merge']
    
    print(f'✓ Found {len(on_ramps)} on-ramp(s), {len(off_ramps)} off-ramp(s), {len(highway_merges)} highway merge(s)\n', flush=True)
    
    output_name = csv_path.stem.replace('_converted', '')
    output_dir = Config.OUTPUT_DIR / output_name
    output_dir.mkdir(exist_ok=True)
    
    all_ramps = sorted(on_ramps + off_ramps + highway_merges, key=lambda x: x.get('trip_id', 1) * 1000000 + x['sample_order'])
    ResultsExporter.save_csv(all_ramps, output_dir / 'ramps_detected.csv')
    ResultsExporter.save_summary(all_ramps, len(route), output_dir / 'analysis_summary.txt')
    
    print(f'✓ Saved: {output_dir}/ramps_detected.csv', flush=True)
    print(f'✓ Saved: {output_dir}/analysis_summary.txt\n', flush=True)

print(f'\n{"="*70}', flush=True)
print('ALL FILES PROCESSED', flush=True)
print(f'{"="*70}', flush=True)

