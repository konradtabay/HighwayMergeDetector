# Highway Ramp Detection System

**Production-ready system for automated highway on/off ramp detection**

By Konrad Tabay - tabay.konrad@gmail.com

---

## Quick Start

```bash
# 1. Install dependencies
pip install flask

# 2. Analyze a GPS trip
python core/highway_ramp_detector.py input/your_trip.gpx

# 3. Batch process multiple trips
python core/batch_process_trips.py --input-dir input --output-dir output/batch

# 4. View results
python core/visualize_server.py
# Open: http://localhost:5000
```

---

## Features

✅ **Multi-layered Detection**
- GPS speed pattern analysis
- Road geometry (bearing changes)
- OpenStreetMap infrastructure verification
- Automatic OSM caching for any region

✅ **High Accuracy**
- OSM proximity required (no false positives)
- Confidence scoring with edge case handling
- Smart deduplication (keeps strongest signals)
- Segment-based detection (full maneuver capture)

✅ **Scalable**
- Batch processing for thousands of trips
- Interactive Flask visualization
- Handles 1Hz GPS data
- Optimized for Ottawa (656 OSM ramps)

---

## Project Structure

```
driver-test/
├── core/                           # Core System
│   ├── highway_ramp_detector.py   # Main analysis engine
│   ├── batch_process_trips.py     # Batch processing
│   └── visualize_server.py        # Web visualization
├── docs/                           # Documentation
│   ├── README.md                  # Main documentation
│   ├── QUICK_START.md             # 5-minute guide
│   ├── DETECTION_WEIGHTS_ANALYSIS.md  # Weight optimization
│   └── [other docs...]
├── setup/                          # Setup & Configuration
│   ├── requirements.txt
│   ├── setup.bat / setup.sh
│   └── LICENSE
├── input/                          # Input GPS files
├── output/                         # Analysis results
└── data/                          # Cached OSM data
```

---

## Documentation

- **[Full Documentation](docs/README.md)** - Complete user guide
- **[Quick Start](docs/QUICK_START.md)** - Get running in 5 minutes
- **[Weight Analysis](docs/DETECTION_WEIGHTS_ANALYSIS.md)** - Detection algorithm details
- **[Batch Processing](docs/BATCH_PROCESSING_README.md)** - Scale to thousands of trips
- **[Deployment](docs/DEPLOYMENT_PACKAGE.md)** - Production deployment guide

---

## Detection Performance (Ottawa Region)

| Metric | Value |
|--------|-------|
| **OSM Ramps Mapped** | 656 ramps |
| **Detection Accuracy** | 100% (4/4 real trips) |
| **False Positives** | 0 (after filtering) |
| **Avg Confidence** | 100% |
| **On-Ramp Speed Change** | +67 km/h avg |
| **Off-Ramp Speed Change** | -70 km/h avg |

---

## Requirements

- Python 3.7+
- Flask (for visualization)
- No other dependencies (uses standard library)

---

## License

MIT License - See [setup/LICENSE](setup/LICENSE)

---

## GitHub

https://github.com/konradtabay/HighwayMergeDetector

