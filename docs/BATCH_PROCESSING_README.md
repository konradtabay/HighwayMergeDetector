# Batch Processing for Highway Ramp Detection

## Overview

Process thousands of GPS trips efficiently with scalable batch processing and interactive visualization.

## Quick Start

### 1. Prepare Your Data

Place all your trip files in the `input/` directory:
```bash
input/
  ├── trip_001.gpx
  ├── trip_002.gpx
  ├── trip_003.csv
  └── ...
```

**Supported formats:**
- `.gpx` - GPS Exchange Format (automatically converted)
- `.csv` - CSV with columns: `sample_order`, `timestamp`, `latitude`, `longitude`, `speed_kmh`

### 2. Run Batch Processing

Process all trips:
```bash
python batch_process_trips.py
```

With custom directories:
```bash
python batch_process_trips.py --input-dir my_trips --output-dir my_results
```

### 3. Visualize Results

Start the visualization server:
```bash
python visualize_server.py
```

This will:
- Start a local web server at `http://localhost:5000`
- Automatically open your browser
- Allow you to browse and visualize all processed trips interactively

## Output Structure

```
output/
└── batch/
    ├── batch_summary.csv          # Summary of all trips
    └── results/
        ├── trip_001/
        │   ├── trip_001_gps_route.csv
        │   ├── trip_001_ramps.csv
        │   └── trip_001_summary.txt
        ├── trip_002/
        │   ├── trip_002_gps_route.csv
        │   ├── trip_002_ramps.csv
        │   └── trip_002_summary.txt
        └── ...
```

## Batch Summary CSV

The `batch_summary.csv` contains:
- `trip_name` - Name of the trip
- `file_path` - Original file path
- `status` - Processing status (success/error)
- `gps_points` - Number of GPS points
- `total_ramps` - Total ramps detected
- `on_ramps` - Number of on-ramps
- `off_ramps` - Number of off-ramps
- `output_dir` - Result directory
- `processed_at` - Processing timestamp

## Visualization Server Features

### Interactive Trip Selection
- Dropdown menu to select any processed trip
- Instant loading and visualization
- No need to regenerate HTML files

### Live Statistics
- GPS points count
- Total segments detected
- On-ramps and off-ramps breakdown

### Interactive Map
- Click segment cards to zoom to specific ramps
- Hover over segments for details
- Click markers for detailed popups
- Color-coded segments:
  - **Green** - On-ramps (entering highway)
  - **Red** - Off-ramps (exiting highway)
  - **Blue** - Full driving route

### Detailed Information
Each ramp segment shows:
- Destination information
- Speed transition (before → after)
- Speed change magnitude
- Bearing/turn angle
- Distance to OSM infrastructure
- Confidence score
- Verification reasons

## Performance

### Scalability
- Processes trips independently (parallelizable)
- Memory-efficient streaming
- Automatic OSM data caching per region
- Results saved incrementally

### Processing Speed
Typical processing time per trip:
- Small trip (< 500 points): ~2-5 seconds
- Medium trip (500-2000 points): ~5-10 seconds
- Large trip (> 2000 points): ~10-20 seconds

### Batch Processing Example
- 1,000 trips: ~1-3 hours (depending on trip sizes)
- Automatic error handling and recovery
- Progress tracking for each trip

## Error Handling

The system gracefully handles:
- Corrupted GPS files
- Invalid coordinate data
- Missing speed information (calculated from GPS)
- Network issues (OSM API)
- Incomplete trips

Failed trips are logged in `batch_summary.csv` with error details.

## Advanced Usage

### Custom Analysis Parameters

Edit `highway_ramp_detector.py` to adjust:
```python
class Config:
    ANALYSIS_WINDOW = 20              # Detection window size
    ONRAMP_MIN_SPEED_INCREASE = 30    # Minimum acceleration
    OFFRAMP_MIN_SPEED_DECREASE = 20   # Minimum deceleration
    # ... and more
```

### Filtering Results

Query the batch summary:
```bash
# Find trips with most ramps
sort -t',' -k5 -nr output/batch/batch_summary.csv | head -10

# Find trips with errors
grep "error" output/batch/batch_summary.csv
```

### Export for Analysis

All results are in CSV format for easy analysis:
- Import into pandas/Excel/R
- Run statistical analysis
- Generate custom reports
- Create visualizations

## System Requirements

- **Python**: 3.7+
- **RAM**: 2GB minimum (4GB+ recommended for large batches)
- **Storage**: ~1MB per trip (route + results)
- **Network**: Required for OSM queries (results cached)

## Troubleshooting

### "No trips found"
- Check that files are in the `input/` directory
- Verify file extensions (.gpx or .csv)
- Ensure files are not empty

### "Visualization shows no data"
- Run batch processing first: `python batch_process_trips.py`
- Check `output/batch/batch_summary.csv` for errors

### "Server won't start"
- Check if port 5000 is available
- Try closing other Flask applications
- Check firewall settings

### "OSM query fails"
- Check internet connection
- OSM API may be temporarily unavailable
- System will fall back to behavior-only detection

## Credits

**Highway Ramp Detection System**  
By Konrad Tabay - tabay.konrad@gmail.com

Multi-layered behavioral analysis combining:
- GPS speed pattern analysis
- Road geometry and bearing changes
- OpenStreetMap infrastructure verification

