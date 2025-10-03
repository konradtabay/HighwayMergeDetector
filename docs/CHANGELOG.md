# Changelog

All notable changes to the Highway Ramp Detection System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2025-10-02

### Added
- **Road Type Change Detection**: System now detects and tracks road type transitions through segments
  - Identifies transitions like "Primary Road → Motorway Link → Motorway"
  - Adds +15% confidence boost when road type change detected
  - Provides valuable context for ramp classification
- **Smart Bounding Box Queries**: Adaptive OSM query regions
  - Rectangle-based around start/end points instead of fixed radius
  - Buffer scales with route distance (30%, min 1km, max 10km)
  - More efficient for short trips, better coverage for long trips
- **Enhanced OSM Data**: Now fetches complete road network geometry
  - Motorways (red highways), trunk roads (orange), primary (yellow), secondary
  - Full geometry data for accurate road type matching
  - Better infrastructure verification
- **Segment-Based Detection**: Ramps now detected as segments instead of points
  - Shows full merge/exit maneuver with start and end coordinates
  - On-ramps use extended window (2x) to capture complete merge
  - Better visualization of ramp transitions
- **Interactive Web Visualization**: Local server with live updates
  - No HTML file generation - all dynamic
  - Dropdown trip selector for easy browsing
  - Claude AI-inspired modern UI
  - Real-time statistics and interactive maps

### Changed
- **Detection Logic**: Improved multi-layered approach
  - On-ramps can be detected without OSM (with strict filtering)
  - Off-ramps REQUIRE OSM proximity (eliminates false positives)
  - Road type changes boost confidence scores
- **Output Format**: Enhanced CSV with new fields
  - `segment_start`, `segment_end`, `segment_length`
  - `start_latitude`, `start_longitude`, `end_latitude`, `end_longitude`
  - `road_types` - Road type transition description
  - `reasons` - Enhanced with road type information
- **OSM Caching**: Improved cache system with route bounds metadata
  - Faster subsequent runs for same geographic region
  - Automatic cache validation
  - Better memory efficiency

### Fixed
- False positive on-ramps from stop sign accelerations (strict bearing change requirements)
- False positive off-ramps from random slowdowns (mandatory OSM proximity)
- Speed calculation from GPX files without speed data
- Unicode encoding issues in Windows console output
- Cache invalidation for routes outside cached region

## [1.0.0] - 2025-09-28

### Added
- Initial release
- Multi-layered highway ramp detection
- GPX and CSV input support
- Batch processing capability
- OSM integration with Overpass API
- Basic web visualization
- Command-line interface
- Automated setup scripts

### Detection Features
- Speed pattern analysis
- Bearing change detection
- OSM proximity verification
- Confidence scoring system
- On-ramp and off-ramp classification

### Output Formats
- CSV with detailed ramp data
- Human-readable text summaries
- Batch processing summaries
- Interactive HTML maps

---

## Legend

- `Added` - New features
- `Changed` - Changes in existing functionality
- `Deprecated` - Soon-to-be removed features
- `Removed` - Removed features
- `Fixed` - Bug fixes
- `Security` - Vulnerability fixes

---

**Maintained by:** Konrad Tabay - [tabay.konrad@gmail.com](mailto:tabay.konrad@gmail.com)

