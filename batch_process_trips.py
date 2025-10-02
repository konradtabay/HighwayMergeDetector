#!/usr/bin/env python3
"""
Batch process multiple GPS trip files
"""
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import sys

# Import the detector
from highway_ramp_detector import (
    GPXConverter, DataLoader, RampDetector, ResultsExporter, Config
)


class BatchProcessor:
    """Process multiple trips efficiently"""
    
    def __init__(self, input_dir: Path, output_dir: Path):
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.results_dir = output_dir / "results"
        self.summary_file = output_dir / "batch_summary.csv"
        
        # Create directories
        self.results_dir.mkdir(parents=True, exist_ok=True)
    
    def find_trip_files(self) -> List[Path]:
        """Find all GPS files (GPX or CSV)"""
        gpx_files = list(self.input_dir.glob("*.gpx"))
        csv_files = list(self.input_dir.glob("*.csv"))
        
        all_files = gpx_files + csv_files
        all_files.sort()
        
        return all_files
    
    def process_single_trip(self, trip_file: Path) -> Dict:
        """Process a single trip file"""
        print(f"\n{'='*70}")
        print(f"Processing: {trip_file.name}")
        print(f"{'='*70}")
        
        trip_name = trip_file.stem
        trip_output_dir = self.results_dir / trip_name
        trip_output_dir.mkdir(exist_ok=True)
        
        try:
            # Convert or load GPS data
            if trip_file.suffix.lower() == '.gpx':
                csv_file = trip_output_dir / f"{trip_name}_gps_route.csv"
                route_points = GPXConverter.convert(trip_file, csv_file)
                print(f"  ✓ Converted {route_points} GPS points from GPX")
            else:
                csv_file = trip_file
                print(f"  ✓ Using existing CSV: {trip_file.name}")
            
            # Load data
            loader = DataLoader()
            route = loader.load_route(csv_file)
            osm_cache = Path('data/osm_ramps.csv')
            osm_ramps = loader.load_or_query_osm_ramps(route, osm_cache)
            
            print(f"  ✓ Loaded {len(route)} route points")
            print(f"  ✓ Loaded {len(osm_ramps)} OSM ramps")
            
            # Detect ramps
            detector = RampDetector(route, osm_ramps)
            
            print("  • Detecting on-ramps...")
            on_ramps = detector.detect_on_ramps()
            
            print("  • Detecting off-ramps...")
            off_ramps = detector.detect_off_ramps()
            
            all_ramps = on_ramps + off_ramps
            
            print(f"  ✓ Found {len(on_ramps)} on-ramp(s)")
            print(f"  ✓ Found {len(off_ramps)} off-ramp(s)")
            
            # Save results
            csv_output = trip_output_dir / f"{trip_name}_ramps.csv"
            summary_output = trip_output_dir / f"{trip_name}_summary.txt"
            
            ResultsExporter.save_csv(all_ramps, csv_output)
            ResultsExporter.save_summary(all_ramps, len(route), summary_output)
            
            print(f"  ✓ Saved results to: {trip_output_dir.name}/")
            
            # Return summary data
            return {
                'trip_name': trip_name,
                'file_path': str(trip_file),
                'status': 'success',
                'gps_points': len(route),
                'total_ramps': len(all_ramps),
                'on_ramps': len(on_ramps),
                'off_ramps': len(off_ramps),
                'output_dir': str(trip_output_dir),
                'processed_at': datetime.now().isoformat()
            }
            
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")
            return {
                'trip_name': trip_name,
                'file_path': str(trip_file),
                'status': 'error',
                'error_message': str(e),
                'processed_at': datetime.now().isoformat()
            }
    
    def process_all(self) -> List[Dict]:
        """Process all trips in the input directory"""
        trip_files = self.find_trip_files()
        
        if not trip_files:
            print(f"\n✗ No GPS files found in: {self.input_dir}")
            print("  Supported formats: .gpx, .csv")
            return []
        
        print(f"\n{'='*70}")
        print(f"BATCH PROCESSING: {len(trip_files)} trip(s)")
        print(f"{'='*70}")
        
        results = []
        for trip_file in trip_files:
            result = self.process_single_trip(trip_file)
            results.append(result)
        
        # Save batch summary
        self.save_batch_summary(results)
        
        return results
    
    def save_batch_summary(self, results: List[Dict]):
        """Save batch processing summary"""
        if not results:
            return
        
        # Determine all possible fields
        fieldnames = set()
        for result in results:
            fieldnames.update(result.keys())
        fieldnames = sorted(list(fieldnames))
        
        with open(self.summary_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f"\n{'='*70}")
        print(f"BATCH SUMMARY")
        print(f"{'='*70}")
        
        successful = [r for r in results if r.get('status') == 'success']
        failed = [r for r in results if r.get('status') == 'error']
        
        print(f"  Total Trips: {len(results)}")
        print(f"  Successful: {len(successful)}")
        print(f"  Failed: {len(failed)}")
        
        if successful:
            total_ramps = sum(r.get('total_ramps', 0) for r in successful)
            total_on = sum(r.get('on_ramps', 0) for r in successful)
            total_off = sum(r.get('off_ramps', 0) for r in successful)
            
            print(f"\n  Total Ramps Detected: {total_ramps}")
            print(f"    - On-Ramps:  {total_on}")
            print(f"    - Off-Ramps: {total_off}")
        
        print(f"\n  Summary saved to: {self.summary_file}")
        print(f"  Results directory: {self.results_dir}")
        print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Batch process multiple GPS trip files for highway ramp detection'
    )
    parser.add_argument(
        '--input-dir',
        type=str,
        default='input',
        help='Directory containing trip files (GPX or CSV)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='output/batch',
        help='Directory to save results'
    )
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    
    if not input_dir.exists():
        print(f"✗ Input directory not found: {input_dir}")
        print(f"  Creating directory: {input_dir}")
        input_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Please add GPS files (.gpx or .csv) to this directory")
        return
    
    processor = BatchProcessor(input_dir, output_dir)
    results = processor.process_all()
    
    if results:
        print("\n✓ Batch processing complete!")
        print(f"  To visualize results, run: python visualize_server.py")


if __name__ == '__main__':
    main()

