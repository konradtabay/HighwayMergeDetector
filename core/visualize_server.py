#!/usr/bin/env python3
"""
Local web server for visualizing trips
"""
from flask import Flask, render_template_string, jsonify, request
import csv
import json
from pathlib import Path
from typing import List, Dict
import webbrowser
import threading
import time

app = Flask(__name__)

# Configuration
RESULTS_DIR = Path('output/batch/results')
OUTPUT_DIR = Path('output')


def load_trip_list() -> List[Dict]:
    """Load list of processed trips"""
    trips = []
    
    # Check batch results
    if RESULTS_DIR.exists():
        for trip_dir in sorted(RESULTS_DIR.iterdir()):
            if trip_dir.is_dir():
                ramp_file = trip_dir / f"{trip_dir.name}_ramps.csv"
                if ramp_file.exists():
                    trips.append({
                        'name': trip_dir.name,
                        'path': str(trip_dir),
                        'type': 'batch'
                    })
    
    # Check single output (for backward compatibility)
    single_ramps = OUTPUT_DIR / 'ramps_detected.csv'
    if single_ramps.exists():
        trips.append({
            'name': 'Latest Single Analysis',
            'path': str(OUTPUT_DIR),
            'type': 'single'
        })
    
    return trips


def load_trip_data(trip_path: str) -> Dict:
    """Load trip route and ramp data"""
    trip_dir = Path(trip_path)
    
    # Find CSV files
    if trip_dir.name == 'output':
        # Single analysis format
        route_file = Path('data/gps_route.csv')
        ramps_file = trip_dir / 'ramps_detected.csv'
    else:
        # Batch format
        route_file = None
        for f in trip_dir.glob('*_gps_route.csv'):
            route_file = f
            break
        
        if not route_file:
            # Try to find original CSV in input
            route_file = Path('data/gps_route.csv')
        
        ramps_file = None
        for f in trip_dir.glob('*_ramps.csv'):
            ramps_file = f
            break
    
    # Load route
    route = []
    if route_file and route_file.exists():
        with open(route_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                route.append({
                    'lat': float(row['latitude']),
                    'lon': float(row['longitude']),
                    'speed': float(row['speed_kmh']),
                    'sample': int(row['sample_order'])
                })
    
    segments = []
    if ramps_file and ramps_file.exists():
        with open(ramps_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                segment = {
                    'segment_start': int(row['segment_start']),
                    'segment_end': int(row['segment_end']),
                    'segment_length': int(row['segment_length']),
                    'merge_type': row['merge_type'],
                    'confidence': float(row['confidence']),
                    'destination': row['destination'],
                    'speed_before': float(row['speed_before']),
                    'speed_after': float(row['speed_after']),
                    'speed_change': float(row['speed_change']),
                    'bearing_change': float(row['bearing_change']),
                    'osm_distance': int(row['osm_distance_m']),
                    'start_lat': float(row['start_latitude']),
                    'start_lon': float(row['start_longitude']),
                    'end_lat': float(row['end_latitude']),
                    'end_lon': float(row['end_longitude']),
                    'mid_lat': float(row['midpoint_latitude']),
                    'mid_lon': float(row['midpoint_longitude']),
                    'road_types': row.get('road_types', ''),
                    'reasons': row['reasons'],
                    'google_validated': row.get('google_validated', 'False').lower() == 'true',
                    'google_rejected': row.get('google_rejected', 'False').lower() == 'true',
                    'rejection_reason': row.get('rejection_reason', ''),
                    'google_uses_ramps': row.get('google_uses_ramps', 'False').lower() == 'true',
                    'google_distance_ratio': float(row.get('google_distance_ratio', '0')) if row.get('google_distance_ratio') else 0,
                    'google_route_distance': float(row.get('google_route_distance', '0')) if row.get('google_route_distance') else 0,
                    'google_detected_distance': float(row.get('google_detected_distance', '0')) if row.get('google_detected_distance') else 0,
                    'google_route_steps': int(row.get('google_route_steps', '0')) if row.get('google_route_steps') else 0
                }
                
                # Build path from route
                segment['path'] = [
                    {'lat': p['lat'], 'lon': p['lon'], 'speed': p['speed']}
                    for p in route
                    if segment['segment_start'] <= p['sample'] <= segment['segment_end']
                ]
                
                segments.append(segment)
    
    return {
        'route': route,
        'segments': segments
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Highway Ramp Detection System</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #F5F5F3;
            color: #1F1F1F;
            -webkit-font-smoothing: antialiased;
        }
        
        .container {
            display: flex;
            height: 100vh;
        }
        
        .sidebar {
            width: 420px;
            background: #FFFFFF;
            border-right: 1px solid #E8E8E6;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }
        
        .header {
            background: linear-gradient(135deg, #D97D54 0%, #C26644 100%);
            color: white;
            padding: 32px 28px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
            letter-spacing: -0.02em;
        }
        
        .header .subtitle {
            font-size: 14px;
            opacity: 0.95;
            font-weight: 400;
            letter-spacing: 0.01em;
        }
        
        .trip-selector {
            padding: 20px;
            background: #FAFAF9;
            border-bottom: 1px solid #E8E8E6;
        }
        
        .trip-selector label {
            display: block;
            font-size: 12px;
            color: #6B6B68;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-weight: 500;
            margin-bottom: 8px;
        }
        
        .trip-selector select {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid #E8E8E6;
            border-radius: 8px;
            font-family: 'Inter', sans-serif;
            font-size: 14px;
            color: #1F1F1F;
            background: white;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .trip-selector select:hover {
            border-color: #D97D54;
        }
        
        .trip-selector select:focus {
            outline: none;
            border-color: #D97D54;
            box-shadow: 0 0 0 3px rgba(217, 125, 84, 0.1);
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            padding: 20px;
            background: #FAFAF9;
            border-bottom: 1px solid #E8E8E6;
        }
        
        .stat-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            border: 1px solid #E8E8E6;
            text-align: center;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .stat-value {
            font-size: 36px;
            font-weight: 600;
            color: #1F1F1F;
            letter-spacing: -0.02em;
        }
        
        .stat-label {
            font-size: 12px;
            color: #6B6B68;
            text-transform: uppercase;
            margin-top: 6px;
            letter-spacing: 0.06em;
            font-weight: 500;
        }
        
        .stat-card.highlight {
            border-width: 1.5px;
        }
        
        .stat-card.on-ramp {
            border-color: #10A37F;
            background: linear-gradient(135deg, #F0FDF9 0%, #FFFFFF 100%);
        }
        
        .stat-card.on-ramp .stat-value {
            color: #10A37F;
        }
        
        .stat-card.off-ramp {
            border-color: #EF4444;
            background: linear-gradient(135deg, #FEF2F2 0%, #FFFFFF 100%);
        }
        
        .stat-card.off-ramp .stat-value {
            color: #EF4444;
        }
        
        .segments-list {
            padding: 20px;
            flex: 1;
            overflow-y: auto;
        }
        
        .segment-card {
            background: white;
            border: 1.5px solid #E8E8E6;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 16px;
            cursor: pointer;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .segment-card:hover {
            border-color: #D97D54;
            box-shadow: 0 8px 24px rgba(217, 125, 84, 0.12);
            transform: translateY(-2px);
        }
        
        .segment-card.on-ramp {
            border-left: 4px solid #10A37F;
        }
        
        .segment-card.off-ramp {
            border-left: 4px solid #EF4444;
        }
        
        .segment-card.rejected {
            opacity: 0.7;
            background: #F9FAFB;
        }
        
        .segment-card.rejected .segment-type {
            color: #6B7280;
        }
        
        .segment-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .segment-type {
            font-size: 16px;
            font-weight: 600;
            color: #1F1F1F;
            letter-spacing: -0.01em;
        }
        
        .segment-type.on-ramp {
            color: #10A37F;
        }
        
        .segment-type.off-ramp {
            color: #EF4444;
        }
        
        .confidence {
            background: linear-gradient(135deg, #D97D54 0%, #C26644 100%);
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.02em;
        }
        
        .destination {
            font-size: 15px;
            color: #1F1F1F;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: #FAFAF9;
            border-radius: 8px;
            border: 1px solid #E8E8E6;
            font-weight: 500;
        }
        
        .segment-info {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-bottom: 14px;
        }
        
        .info-item {
            font-size: 13px;
            color: #6B6B68;
            line-height: 1.5;
        }
        
        .info-label {
            font-weight: 500;
            margin-bottom: 4px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        
        .info-value {
            font-weight: 600;
            color: #1F1F1F;
            font-size: 14px;
        }
        
        .segment-range {
            font-size: 12px;
            color: #6B6B68;
            padding: 10px 14px;
            background: #FAFAF9;
            border-radius: 8px;
            margin-top: 12px;
            border: 1px solid #E8E8E6;
            font-weight: 500;
        }
        
        .map-container {
            flex: 1;
            position: relative;
            background: #F5F5F3;
        }
        
        #map {
            height: 100%;
            width: 100%;
        }
        
        .legend {
            position: absolute;
            bottom: 24px;
            right: 24px;
            background: white;
            padding: 20px 24px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.08);
            border: 1px solid #E8E8E6;
            z-index: 1000;
        }
        
        .legend-title {
            font-weight: 600;
            margin-bottom: 14px;
            color: #1F1F1F;
            font-size: 14px;
            letter-spacing: -0.01em;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            margin-bottom: 10px;
            font-size: 13px;
            color: #6B6B68;
        }
        
        .legend-item:last-child {
            margin-bottom: 0;
        }
        
        .legend-line {
            width: 32px;
            height: 4px;
            margin-right: 12px;
            border-radius: 2px;
        }
        
        .loading {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 40px;
            color: #6B6B68;
        }
        
        ::-webkit-scrollbar {
            width: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: #FAFAF9;
        }
        
        ::-webkit-scrollbar-thumb {
            background: #D1D1CF;
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: #B8B8B6;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="header">
                <h1>Highway Ramp Detection</h1>
                <div class="subtitle">By Konrad Tabay - tabay.konrad@gmail.com</div>
            </div>
            
            <div class="trip-selector">
                <label for="trip-select">Select Trip</label>
                <select id="trip-select" onchange="loadTrip()">
                    <option value="">Loading trips...</option>
                </select>
                
                <div style="margin-top: 16px;">
                    <label style="display: flex; align-items: center; cursor: pointer; font-size: 13px; color: #6B6B68;">
                        <input type="checkbox" id="showHiddenRamps" onchange="toggleHiddenRamps()" style="margin-right: 8px;">
                        Show Hidden Ramps (Google Rejected)
                    </label>
                </div>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <div class="stat-value" id="stat-points">-</div>
                    <div class="stat-label">GPS Points</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value" id="stat-segments">-</div>
                    <div class="stat-label">Segments</div>
                </div>
                <div class="stat-card highlight on-ramp">
                    <div class="stat-value" id="stat-on">-</div>
                    <div class="stat-label">On-Ramps</div>
                </div>
                <div class="stat-card highlight off-ramp">
                    <div class="stat-value" id="stat-off">-</div>
                    <div class="stat-label">Off-Ramps</div>
                </div>
            </div>
            
            <div class="segments-list" id="segments-list">
                <div class="loading">Select a trip to view details</div>
            </div>
        </div>
        
        <div class="map-container">
            <div id="map"></div>
            <div class="legend">
                <div class="legend-title">Legend</div>
                <div class="legend-item">
                    <div class="legend-line" style="background: #6B9BD1; height: 3px;"></div>
                    <span>Driving Route</span>
                </div>
                <div class="legend-item">
                    <div class="legend-line" style="background: #10A37F; height: 5px;"></div>
                    <span>On-Ramp Segment</span>
                </div>
                <div class="legend-item">
                    <div class="legend-line" style="background: #EF4444; height: 5px;"></div>
                    <span>Off-Ramp Segment</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        let map = null;
        let currentLayers = [];
        
        // Initialize map
        function initMap() {
            if (!map) {
                map = L.map('map').setView([45.4, -75.7], 11);
                L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                    attribution: '© OpenStreetMap contributors'
                }).addTo(map);
            }
        }
        
        // Load trip list
        async function loadTripList() {
            const response = await fetch('/api/trips');
            const trips = await response.json();
            
            const select = document.getElementById('trip-select');
            select.innerHTML = '';
            
            if (trips.length === 0) {
                select.innerHTML = '<option value="">No trips found</option>';
                return;
            }
            
            trips.forEach(trip => {
                const option = document.createElement('option');
                option.value = trip.path;
                option.textContent = trip.name;
                select.appendChild(option);
            });
            
            // Load first trip
            if (trips.length > 0) {
                loadTrip();
            }
        }
        
        // Load trip data
        async function loadTrip() {
            const select = document.getElementById('trip-select');
            const tripPath = select.value;
            
            if (!tripPath) return;
            
            const response = await fetch(`/api/trip?path=${encodeURIComponent(tripPath)}`);
            const data = await response.json();
            
            displayTripData(data);
        }
        
        // Toggle hidden ramps visibility
        function toggleHiddenRamps() {
            const showHidden = document.getElementById('showHiddenRamps').checked;
            const allLayers = [...currentLayers];
            
            // Clear current layers
            currentLayers.forEach(layer => map.removeLayer(layer));
            currentLayers = [];
            
            // Re-add layers based on visibility setting
            allLayers.forEach(layer => {
                if (layer.options && layer.options.rejected) {
                    // This is a rejected ramp layer
                    if (showHidden) {
                        map.addLayer(layer);
                        currentLayers.push(layer);
                    }
                } else {
                    // This is a normal ramp layer
                    map.addLayer(layer);
                    currentLayers.push(layer);
                }
            });
            
            // Update sidebar
            if (currentSegments) {
                updateSidebar(currentSegments, showHidden);
            }
        }
        
        // Display trip data on map
        function displayTripData(data) {
            // Clear existing layers
            currentLayers.forEach(layer => map.removeLayer(layer));
            currentLayers = [];
            
            const route = data.route;
            const segments = data.segments;
            
            // Store current segments and trip name for labeling
            currentSegments = segments;
            const select = document.getElementById('trip-select');
            currentTripName = select.options[select.selectedIndex].text;
            
            // Update stats
            document.getElementById('stat-points').textContent = route.length;
            document.getElementById('stat-segments').textContent = segments.length;
            document.getElementById('stat-on').textContent = segments.filter(s => s.merge_type === 'on_ramp').length;
            document.getElementById('stat-off').textContent = segments.filter(s => s.merge_type === 'off_ramp').length;
            
            // Draw route
            const routeCoords = route.map(p => [p.lat, p.lon]);
            const routeLine = L.polyline(routeCoords, {
                color: '#6B9BD1',
                weight: 3,
                opacity: 0.7
            }).addTo(map);
            currentLayers.push(routeLine);
            
            // Fit map
            if (routeCoords.length > 0) {
                map.fitBounds(routeLine.getBounds(), {padding: [50, 50]});
            }
            
            // Draw segments
            const segmentLayers = [];
            const showHidden = document.getElementById('showHiddenRamps').checked;
            
            segments.forEach((segment, index) => {
                const isRejected = segment.google_rejected || false;
                let color, weight, opacity;
                
                if (isRejected) {
                    // Rejected ramps - different styling
                    color = segment.merge_type === 'on_ramp' ? '#6B7280' : '#9CA3AF';
                    weight = 4;
                    opacity = 0.6;
                } else {
                    // Valid ramps - normal styling
                    color = segment.merge_type === 'on_ramp' ? '#10A37F' : '#EF4444';
                    weight = 6;
                    opacity = 0.85;
                }
                
                const pathCoords = segment.path.map(p => [p.lat, p.lon]);
                
                const segmentLine = L.polyline(pathCoords, {
                    color: color,
                    weight: weight,
                    opacity: opacity,
                    lineCap: 'round',
                    lineJoin: 'round',
                    rejected: isRejected
                });
                
                // Only add to map if not rejected or if show hidden is enabled
                if (!isRejected || showHidden) {
                    segmentLine.addTo(map);
                }
                
                const startMarker = L.circleMarker([segment.start_lat, segment.start_lon], {
                    radius: 7,
                    fillColor: color,
                    color: 'white',
                    weight: 2.5,
                    fillOpacity: 1
                }).addTo(map);
                
                const endMarker = L.circleMarker([segment.end_lat, segment.end_lon], {
                    radius: 7,
                    fillColor: color,
                    color: 'white',
                    weight: 2.5,
                    fillOpacity: 1
                }).addTo(map);
                
                currentLayers.push(segmentLine, startMarker, endMarker);
                segmentLayers.push({line: segmentLine, start: startMarker, end: endMarker});
                
                const icon = segment.merge_type === 'on_ramp' ? '↗' : '↘';
                const typeLabel = segment.merge_type === 'on_ramp' ? 'On-Ramp' : 'Off-Ramp';
                
                const popupContent = `
                    <div style="font-family: 'Inter', sans-serif; min-width: 320px; padding: 8px;">
                        <div style="font-size: 18px; font-weight: 600; color: ${color}; margin-bottom: 12px; letter-spacing: -0.01em;">
                            ${icon} ${typeLabel} Segment
                        </div>
                        
                        <div style="background: #FAFAF9; padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #E8E8E6;">
                            <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">Destination</div>
                            <div style="font-size: 15px; font-weight: 600; color: #1F1F1F;">→ ${segment.destination}</div>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">
                            <div>
                                <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">Confidence</div>
                                <div style="font-size: 16px; font-weight: 600; color: #1F1F1F;">${(segment.confidence * 100).toFixed(0)}%</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">Samples</div>
                                <div style="font-size: 16px; font-weight: 600; color: #1F1F1F;">${segment.segment_length}</div>
                            </div>
                        </div>
                        
                        <div style="background: #FAFAF9; padding: 12px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #E8E8E6;">
                            <div style="font-size: 11px; color: #6B6B68; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">Speed Transition</div>
                            <div style="font-size: 15px; font-weight: 600; color: #1F1F1F;">
                                ${segment.speed_before.toFixed(1)} → ${segment.speed_after.toFixed(1)} km/h
                            </div>
                            <div style="font-size: 14px; font-weight: 600; color: ${segment.speed_change > 0 ? '#10A37F' : '#EF4444'}; margin-top: 4px;">
                                ${segment.speed_change > 0 ? '+' : ''}${segment.speed_change.toFixed(1)} km/h
                            </div>
                        </div>
                        
                        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 12px;">
                            <div>
                                <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">Turn Angle</div>
                                <div style="font-size: 15px; font-weight: 600; color: #1F1F1F;">${segment.bearing_change.toFixed(0)}°</div>
                            </div>
                            <div>
                                <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 500;">OSM Distance</div>
                                <div style="font-size: 15px; font-weight: 600; color: #1F1F1F;">${segment.osm_distance}m</div>
                            </div>
                        </div>
                        
                        ${segment.road_types ? `
                        <div style="background: #F0FDF9; padding: 10px 12px; border-radius: 8px; border: 1px solid #10A37F20; margin-bottom: 12px;">
                            <div style="font-size: 11px; color: #0D8265; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;">Road Types</div>
                            <div style="font-size: 12px; color: #1F1F1F; font-weight: 500;">${segment.road_types}</div>
                        </div>
                        ` : ''}
                        
                        <div style="background: #FAFAF9; padding: 10px 12px; border-radius: 8px; border: 1px solid #E8E8E6; margin-bottom: 12px;">
                            <div style="font-size: 11px; color: #6B6B68; margin-bottom: 4px; font-weight: 500;">VERIFICATION</div>
                            <div style="font-size: 12px; color: #1F1F1F; line-height: 1.5;">${segment.reasons}</div>
                        </div>
                        
                        <div style="background: #F8F9FA; padding: 10px 12px; border-radius: 8px; border: 1px solid #E8E8E6;">
                            <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="toggleWeights(this)">
                                <div style="font-size: 11px; color: #6B6B68; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Confidence Weights</div>
                                <div style="font-size: 12px; color: #6B6B68;">▼</div>
                            </div>
                            <div id="weights-${index}" style="display: none; margin-top: 8px; font-size: 11px; color: #6B6B68; line-height: 1.4;">
                                ${getConfidenceWeights(segment)}
                            </div>
                        </div>
                        
                        ${segment.google_route_steps > 0 ? `
                        <div style="background: ${segment.google_validated ? '#F0FDF9' : '#FEF2F2'}; padding: 12px; border-radius: 8px; border: 1px solid ${segment.google_validated ? '#10A37F' : '#EF4444'}; margin-top: 12px;">
                            <div style="font-size: 11px; color: ${segment.google_validated ? '#0D8265' : '#DC2626'}; margin-bottom: 8px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Google Directions API Validation</div>
                            <div style="font-size: 12px; color: #1F1F1F; line-height: 1.6;">
                                <div style="margin-bottom: 4px;"><strong>Status:</strong> ${segment.google_validated ? '<span style="color: #10A37F;">✓ Validated</span>' : '<span style="color: #EF4444;">✗ Rejected</span>'}</div>
                                <div style="margin-bottom: 4px;"><strong>Uses Ramps:</strong> ${segment.google_uses_ramps ? '<span style="color: #10A37F;">Yes</span>' : '<span style="color: #EF4444;">No</span>'}</div>
                                <div style="margin-bottom: 4px;"><strong>Distance Ratio:</strong> ${segment.google_distance_ratio.toFixed(2)}</div>
                                <div style="margin-bottom: 4px;"><strong>Detected Distance:</strong> ${segment.google_detected_distance}m</div>
                                <div style="margin-bottom: 4px;"><strong>Google Route Distance:</strong> ${segment.google_route_distance}m</div>
                                <div style="margin-bottom: 4px;"><strong>Route Steps:</strong> ${segment.google_route_steps}</div>
                                ${segment.rejection_reason ? `<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid ${segment.google_validated ? '#10A37F40' : '#EF444440'};"><strong>Reason:</strong> ${segment.rejection_reason}</div>` : ''}
                            </div>
                        </div>
                        ` : ''}
                        
                        <div style="background: #F0F9FF; padding: 12px; border-radius: 8px; border: 1px solid #0EA5E9; margin-top: 12px;">
                            <div style="font-size: 11px; color: #0369A1; margin-bottom: 8px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">ML Training Label</div>
                            <div style="display: flex; gap: 8px;">
                                <button onclick="labelMerge(${index}, 'accept')" style="flex: 1; padding: 8px 12px; background: #10A37F; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s;">✓ Accept</button>
                                <button onclick="labelMerge(${index}, 'reject')" style="flex: 1; padding: 8px 12px; background: #EF4444; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s;">✗ Reject</button>
                            </div>
                            <div id="label-status-${index}" style="margin-top: 6px; font-size: 11px; color: #0369A1; font-weight: 500;"></div>
                        </div>
                    </div>
                `;
                
                segmentLine.bindPopup(popupContent, {maxWidth: 380});
                startMarker.bindPopup(popupContent, {maxWidth: 380});
                endMarker.bindPopup(popupContent, {maxWidth: 380});
            });
            
            // Update sidebar
            updateSidebar(segments, showHidden);
        }
        
        // Update sidebar with segments
        function updateSidebar(segments, showHidden = false) {
            const segmentsList = document.getElementById('segments-list');
            segmentsList.innerHTML = '';
            
            if (segments.length === 0) {
                segmentsList.innerHTML = '<div class="loading">No ramps detected in this trip</div>';
                return;
            }
            
            // Filter segments based on visibility
            const visibleSegments = segments.filter(segment => {
                const isRejected = segment.google_rejected || false;
                return !isRejected || showHidden;
            });
            
            if (visibleSegments.length === 0) {
                segmentsList.innerHTML = '<div class="loading">No visible ramps (toggle "Show Hidden Ramps" to see rejected ones)</div>';
                return;
            }
            
            visibleSegments.forEach((segment, index) => {
                const card = document.createElement('div');
                const isRejected = segment.google_rejected || false;
                card.className = `segment-card ${segment.merge_type} ${isRejected ? 'rejected' : ''}`;
                
                const icon = segment.merge_type === 'on_ramp' ? '↗' : '↘';
                const typeLabel = segment.merge_type === 'on_ramp' ? 'On-Ramp' : 'Off-Ramp';
                const rejectionBadge = isRejected ? '<span style="background: #EF4444; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 8px;">REJECTED</span>' : '';
                
                card.innerHTML = `
                    <div class="segment-header">
                        <div class="segment-type ${segment.merge_type}">${icon} ${typeLabel}${rejectionBadge}</div>
                        <div class="confidence">${(segment.confidence * 100).toFixed(0)}%</div>
                    </div>
                    <div class="destination">→ ${segment.destination}</div>
                    <div class="segment-info">
                        <div class="info-item">
                            <div class="info-label">Speed Change</div>
                            <div class="info-value" style="color: ${segment.speed_change > 0 ? '#10A37F' : '#EF4444'}">
                                ${segment.speed_change > 0 ? '+' : ''}${segment.speed_change.toFixed(1)} km/h
                            </div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Turn Angle</div>
                            <div class="info-value">${segment.bearing_change.toFixed(0)}°</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">Speed Range</div>
                            <div class="info-value">${segment.speed_before.toFixed(0)} → ${segment.speed_after.toFixed(0)} km/h</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">OSM Distance</div>
                            <div class="info-value">${segment.osm_distance}m</div>
                        </div>
                    </div>
                    <div class="segment-range">
                        Samples ${segment.segment_start} → ${segment.segment_end} (${segment.segment_length} points)
                    </div>
                    <div class="weights-section" style="margin-top: 12px; padding: 10px; background: #F8F9FA; border-radius: 8px; border: 1px solid #E8E8E6;">
                        <div style="display: flex; align-items: center; justify-content: space-between; cursor: pointer;" onclick="toggleWeights(this)">
                            <div style="font-size: 11px; color: #6B6B68; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Confidence Weights</div>
                            <div style="font-size: 12px; color: #6B6B68;">▼</div>
                        </div>
                        <div id="weights-sidebar-${index}" style="display: none; margin-top: 8px; font-size: 11px; color: #6B6B68; line-height: 1.4;">
                            ${getConfidenceWeights(segment)}
                        </div>
                    </div>
                    
                    ${isRejected ? `
                    <div style="margin-top: 12px; padding: 12px; background: #FEF2F2; border-radius: 8px; border: 1px solid #FECACA;">
                        <div style="font-size: 11px; color: #DC2626; margin-bottom: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">Google Rejection</div>
                        <div style="font-size: 12px; color: #7F1D1D; line-height: 1.4;">${segment.rejection_reason || 'Rejected by Google validation'}</div>
                    </div>
                    ` : ''}
                    
                    <div class="labeling-section" style="margin-top: 12px; padding: 12px; background: #F0F9FF; border-radius: 8px; border: 1px solid #0EA5E9;">
                        <div style="font-size: 11px; color: #0369A1; margin-bottom: 8px; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em;">ML Training Label</div>
                        <div style="display: flex; gap: 8px;">
                            <button onclick="labelMerge(${index}, 'accept')" style="flex: 1; padding: 8px 12px; background: #10A37F; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s;">✓ Accept</button>
                            <button onclick="labelMerge(${index}, 'reject')" style="flex: 1; padding: 8px 12px; background: #EF4444; color: white; border: none; border-radius: 6px; font-size: 12px; font-weight: 500; cursor: pointer; transition: all 0.2s;">✗ Reject</button>
                        </div>
                        <div id="label-status-sidebar-${index}" style="margin-top: 6px; font-size: 11px; color: #0369A1; font-weight: 500;"></div>
                    </div>
                `;
                
                card.onclick = () => {
                    const layers = segmentLayers[index];
                    map.fitBounds(layers.line.getBounds(), {padding: [80, 80]});
                    layers.line.openPopup();
                };
                
                segmentsList.appendChild(card);
            });
        }
        
        // Toggle confidence weights visibility
        function toggleWeights(element) {
            const weightsDiv = element.nextElementSibling;
            const arrow = element.querySelector('div:last-child');
            
            if (weightsDiv.style.display === 'none') {
                weightsDiv.style.display = 'block';
                arrow.textContent = '▲';
            } else {
                weightsDiv.style.display = 'none';
                arrow.textContent = '▼';
            }
        }
        
        // Calculate confidence weights breakdown
        function getConfidenceWeights(segment) {
            const isOnRamp = segment.merge_type === 'on_ramp';
            let weights = [];
            let total = 0;
            
            if (isOnRamp) {
                // Removed acceleration-based confidence - focus on other factors
                
                // Removed car-specific speed assumptions - focus on relative speed changes
                // No longer penalizing high start speeds or requiring specific end speeds
                
                if (segment.bearing_change > 30) {
                    weights.push('Significant turn: +0.3');
                    total += 0.3;
                } else if (segment.bearing_change > 15) {
                    weights.push('Direction change: +0.1');
                    total += 0.1;
                }
                
                if (segment.osm_distance < 300) {
                    weights.push('OSM proximity: +0.2');
                    total += 0.2;
                }
            } else {
                // Removed deceleration-based confidence - focus on other factors
                
                // Removed car-specific speed assumptions - focus on relative speed changes
                // No longer making assumptions about "highway speed" or "ramp speed"
                
                if (segment.bearing_change > 30) {
                    weights.push('Significant turn: +0.3');
                    total += 0.3;
                } else if (segment.bearing_change > 15) {
                    weights.push('Direction change: +0.1');
                    total += 0.1;
                }
                
                if (segment.osm_distance < 100) {
                    weights.push('OSM proximity: +0.3');
                    total += 0.3;
                } else if (segment.osm_distance < 150) {
                    weights.push('OSM proximity: +0.2');
                    total += 0.2;
                }
            }
            
            // Add road type bonus if present
            if (segment.road_types && segment.road_types.includes('→')) {
                weights.push('Road type change: +0.15');
                total += 0.15;
            }
            
            // Cap at 1.0
            total = Math.min(1.0, total);
            
            let html = weights.map(w => `• ${w}`).join('<br>');
            html += `<br><br><strong>Total: ${(total * 100).toFixed(0)}%</strong>`;
            
            return html;
        }
        
        // ML Labeling functions
        function labelMerge(segmentIndex, label) {
            const segment = currentSegments[segmentIndex];
            if (!segment) return;
            
            // Create label data
            const labelData = {
                trip_name: currentTripName,
                segment_index: segmentIndex,
                merge_type: segment.merge_type,
                confidence: segment.confidence,
                speed_change: segment.speed_change,
                bearing_change: segment.bearing_change,
                osm_distance: segment.osm_distance,
                road_types: segment.road_types,
                label: label,
                timestamp: new Date().toISOString()
            };
            
            // Send to server
            fetch('/api/label', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(labelData)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Update UI
                    const statusDiv = document.getElementById(`label-status-${segmentIndex}`);
                    if (statusDiv) {
                        statusDiv.textContent = `Labeled as: ${label.toUpperCase()}`;
                        statusDiv.style.color = label === 'accept' ? '#10A37F' : '#EF4444';
                    }
                    
                    // Update sidebar if exists
                    const sidebarStatus = document.getElementById(`label-status-sidebar-${segmentIndex}`);
                    if (sidebarStatus) {
                        sidebarStatus.textContent = `Labeled as: ${label.toUpperCase()}`;
                        sidebarStatus.style.color = label === 'accept' ? '#10A37F' : '#EF4444';
                    }
                } else {
                    alert('Failed to save label: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error saving label:', error);
                alert('Error saving label. Please try again.');
            });
        }
        
        // Store current segments and trip name for labeling
        let currentSegments = [];
        let currentTripName = '';
        
        // Initialize
        initMap();
        loadTripList();
    </script>
</body>
</html>"""


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/trips')
def api_trips():
    trips = load_trip_list()
    return jsonify(trips)


@app.route('/api/trip')
def api_trip():
    trip_path = request.args.get('path', '')
    if not trip_path:
        return jsonify({'error': 'No path provided'}), 400
    
    data = load_trip_data(trip_path)
    return jsonify(data)


@app.route('/api/label', methods=['POST'])
def api_label():
    """Save ML training labels for merge segments"""
    try:
        label_data = request.get_json()
        
        # Validate required fields
        required_fields = ['trip_name', 'segment_index', 'merge_type', 'confidence', 'label']
        for field in required_fields:
            if field not in label_data:
                return jsonify({'success': False, 'error': f'Missing required field: {field}'}), 400
        
        # Create labels directory if it doesn't exist
        labels_dir = Path('output/labels')
        labels_dir.mkdir(parents=True, exist_ok=True)
        
        # Save label to CSV file
        labels_file = labels_dir / 'ml_training_labels.csv'
        
        # Check if file exists to determine if we need headers
        file_exists = labels_file.exists()
        
        with open(labels_file, 'a', newline='', encoding='utf-8') as f:
            fieldnames = [
                'trip_name', 'segment_index', 'merge_type', 'confidence', 
                'speed_change', 'bearing_change', 'osm_distance', 'road_types',
                'label', 'timestamp'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow({
                'trip_name': label_data['trip_name'],
                'segment_index': label_data['segment_index'],
                'merge_type': label_data['merge_type'],
                'confidence': label_data['confidence'],
                'speed_change': label_data.get('speed_change', ''),
                'bearing_change': label_data.get('bearing_change', ''),
                'osm_distance': label_data.get('osm_distance', ''),
                'road_types': label_data.get('road_types', ''),
                'label': label_data['label'],
                'timestamp': label_data['timestamp']
            })
        
        return jsonify({'success': True, 'message': 'Label saved successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def open_browser():
    """Open browser after short delay"""
    time.sleep(1.5)
    webbrowser.open('http://localhost:5001')


def main():
    print("\n" + "="*70)
    print("HIGHWAY RAMP DETECTION - VISUALIZATION SERVER")
    print("="*70)
    print("\n Starting local server...")
    print(" Opening browser at: http://localhost:5001")
    print("\n Press Ctrl+C to stop the server")
    print("="*70 + "\n")
    
    # Open browser in separate thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    # Run server
    app.run(host='localhost', port=5001, debug=False)


if __name__ == '__main__':
    main()

