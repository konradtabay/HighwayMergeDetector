#!/usr/bin/env python3
"""
Convert CSV GPS data to GPX format
"""
import csv
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

def convert_csv_to_gpx(csv_file, gpx_file):
    """Convert CSV GPS data to GPX format"""
    print(f"Converting {csv_file} to GPX...")
    
    # Create GPX root element
    gpx = ET.Element("gpx")
    gpx.set("version", "1.1")
    gpx.set("creator", "HighwayMergeDetector")
    gpx.set("xmlns", "http://www.topografix.com/GPX/1/1")
    
    # Create track
    trk = ET.SubElement(gpx, "trk")
    trk_name = ET.SubElement(trk, "name")
    trk_name.text = "Q01 GPS Track"
    
    # Create track segment
    trkseg = ET.SubElement(trk, "trkseg")
    
    # Read CSV and create track points
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        point_count = 0
        
        for row in reader:
            # Create track point
            trkpt = ET.SubElement(trkseg, "trkpt")
            trkpt.set("lat", str(row['latitude']))
            trkpt.set("lon", str(row['longitude']))
            
            # Add time
            time_elem = ET.SubElement(trkpt, "time")
            timestamp = int(row['timestamp'])
            dt = datetime.fromtimestamp(timestamp)
            time_elem.text = dt.isoformat() + "Z"
            
            # Add speed if available
            if 'speed_kmh' in row and row['speed_kmh']:
                try:
                    speed_ms = float(row['speed_kmh']) / 3.6  # Convert km/h to m/s
                    speed_elem = ET.SubElement(trkpt, "extensions")
                    speed_data = ET.SubElement(speed_elem, "speed")
                    speed_data.text = str(speed_ms)
                except (ValueError, TypeError):
                    pass
            
            point_count += 1
            if point_count % 10000 == 0:
                print(f"  Processed {point_count} points...")
    
    # Write GPX file
    tree = ET.ElementTree(gpx)
    ET.indent(tree, space="  ", level=0)
    tree.write(gpx_file, encoding='utf-8', xml_declaration=True)
    
    print(f"✓ Converted {point_count} GPS points to {gpx_file}")
    return point_count

if __name__ == "__main__":
    csv_file = Path("input/q01_converted.csv")
    gpx_file = Path("input/q01_converted.gpx")
    
    if not csv_file.exists():
        print(f"Error: {csv_file} not found!")
        exit(1)
    
    convert_csv_to_gpx(csv_file, gpx_file)
    print(f"\nGPX file created: {gpx_file}")
