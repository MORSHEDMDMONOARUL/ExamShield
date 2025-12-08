# Changelog

All notable changes to ExamShield will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.2] - 2025-12-08

### Added
- Comprehensive GitHub documentation with SEO optimization
- Professional README with badges and diagrams
- MIT License for open source distribution
- Contributing guidelines for community collaboration
- System architecture Mermaid diagrams
- ESP32 integration documentation
- Multi-camera support (Standard, Pro, Enterprise modes)
- Intelligent alert system with cooldown management
- Risk scoring with priority-weighted confidence
- Session reporting with CSV logging
- BLE and WiFi device monitoring via ESP32
- GPU acceleration support (CUDA, DirectML, CPU)

### Changed
- Standardized class naming conventions across all files
- Aligned configuration thresholds for consistency
- Improved code documentation and inline comments
- Enhanced UI rendering with modern design

### Fixed
- Configuration inconsistencies in videotodetect.py
- Earphone threshold alignment (0.30 across all files)
- Calibration multiplier standardization
- Python syntax validation (all files compile successfully)

##  [2.2.0] - 2025-11-28

### Added
- Multi-student tracking using centroid matching
- Person-to-detection association system
- Student-specific risk analysis
- Enhanced behavioral detection logic
- Earphone multi-detection requirement (3+)
- Head rotation duration tracking (5s sustained)
- Paper passing high-confidence filtering

### Improved
- Frame processing performance with threading
- Camera initialization with multiple backend support
- Alert photo management system
- UI overlay with statistics panel

## [2.1.0] - 2025-11-27

### Added
- Video analysis mode for pre-recorded footage
- Enterprise multi-camera support (16 cameras)
- Pro 4-camera configuration
- Threaded camera capture for better FPS
- Real-time FPS monitoring and warnings

### Changed
- Refactored alert management system
- Improved UI responsiveness
- Enhanced logging mechanism

## [2.0.0] - 2025-11-25

### Added
- YOLOv8 custom model training
- Five detection classes (phone, earphone, smartwatch, headrotation, paperpassing)
- Confidence calibration system
- Priority-based alerting
- Photo proof capture system
- Session report generation

### Changed
- Complete rewrite using YOLOv8 (from YOLOv5)
- Modernized UI with OpenCV overlays
- Improved detection accuracy

## [1.0.0] - 2025-10-15

### Added
- Initial release
- Basic camera monitoring
- Simple object detection
- Alert notifications

---

## Version Numbering

**MAJOR.MINOR.PATCH**

- **MAJOR**: Incompatible API changes
- **MINOR**: Backwards-compatible new features  
- **PATCH**: Backwards-compatible bug fixes

---

## Upcoming Releases

### [2.3.0] - Planned Q1 2025
- Web dashboard for remote monitoring
- Database integration
- Email/SMS notifications
- Mobile supervisor app

### [3.0.0] - Planned Q2 2025
- Facial recognition integration
- Gaze tracking
- Speech detection
- Cloud deployment support

See [FUTURE_ROADMAP.md](FUTURE_ROADMAP.md) for detailed plans.
