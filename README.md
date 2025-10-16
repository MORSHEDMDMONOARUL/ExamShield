# ExamShield: Smart Device Detection System

ExamShield is an advanced IoT-based detection system designed to identify unauthorized smartphones, laptops, and smartwatches in secure environments such as exam halls, meeting rooms, and restricted facilities.

## Features

- **Multi-layer Detection**: Combines RF (WiFi/BLE) scanning and thermal imaging for high accuracy
- **Real-time Monitoring**: Live dashboard with thermal visualization and device tracking
- **Smart Alerts**: Laser pointer targeting with audio/visual alerts
- **Position Estimation**: RSSI-based triangulation to locate detected devices
- **Low False Positives**: Correlation between RF signals and thermal hotspots
- **Scalable Design**: Modular architecture for easy expansion

## System Architecture

### Hardware Components

#### Core Processing
- Raspberry Pi 4B (4GB RAM) with 64-bit Pi OS
- MicroSD card (32GB+)
- Official Raspberry Pi power supply

#### RF Detection Layer
- 4Ã— ESP32 development boards
- USB cables and power adapters for ESP32s
- WiFi/BLE scanning capabilities

#### Thermal Detection Layer  
- MLX90640 thermal sensor (32Ã—24 resolution, 110Â° FOV)
- I2C connection to Raspberry Pi
- 4Hz refresh rate for real-time detection

#### Alert System
- Laser diode module (<5mW, eye-safe)
- 2Ã— Servo motors (SG90/MG90S) for X-Y laser positioning
- Buzzer module for audio alerts
- LED indicator for visual alerts
- Breadboards and jumper wires

### Software Stack

#### Raspberry Pi (Python 3.9+)
- **main.py**: Central control system
- **rf_receiver.py**: ESP32 data processing and triangulation
- **thermal_detection.py**: MLX90640 sensor interface and hotspot detection
- **alert_system.py**: Servo, laser, and alert control
- **gui_dashboard.py**: Real-time monitoring interface
- **utils.py**: Common utilities and helper functions

#### ESP32 (Arduino IDE)
- **esp32_scanner.ino**: BLE/WiFi scanning firmware
- Continuous device discovery and RSSI reporting
- Serial communication with Raspberry Pi

## Installation & Setup

### Prerequisites

1. **Raspberry Pi 4B Setup**
   ```bash
   # Update system
   sudo apt update && sudo apt upgrade -y

   # Install Python dependencies
   sudo apt install python3-pip python3-venv i2c-tools -y

   # Enable I2C interface
   sudo raspi-config  # Interface Options -> I2C -> Enable
   ```

2. **ESP32 Setup**
   - Install Arduino IDE
   - Add ESP32 board support: `https://dl.espressif.com/dl/package_esp32_index.json`
   - Install required libraries: WiFi, BLEDevice

### Virtual Environment Setup

```bash
# Navigate to project directory
cd /home/pi/ExamShield

# Create virtual environment
python3 -m venv --system-site-packages .venv

# Activate virtual environment
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### Hardware Connections

#### MLX90640 Thermal Sensor (I2C)
```
MLX90640    Raspberry Pi 4
VCC    â†’    3.3V (Pin 1)
GND    â†’    GND (Pin 6)
SDA    â†’    GPIO 2/SDA (Pin 3)
SCL    â†’    GPIO 3/SCL (Pin 5)
```

#### Alert System Connections
```
Component        GPIO Pin    Purpose
Servo X-Axis  â†’  GPIO 11     Horizontal laser control
Servo Y-Axis  â†’  GPIO 13     Vertical laser control
Laser Diode   â†’  GPIO 15     Laser on/off
Buzzer        â†’  GPIO 16     Audio alerts
LED           â†’  GPIO 18     Visual indicator
```

#### ESP32 Placement
Position the 4 ESP32 boards in corners of the monitoring area:
- ESP32 #1: Top-left corner
- ESP32 #2: Top-right corner  
- ESP32 #3: Bottom-left corner
- ESP32 #4: Bottom-right corner

Connect each ESP32 via USB to the Raspberry Pi or use external power supplies.

### Software Configuration

1. **Upload ESP32 Firmware**
   ```arduino
   // Open esp32/esp32_scanner.ino in Arduino IDE
   // Select your ESP32 board and port
   // Upload the sketch to all 4 ESP32 boards
   ```

2. **Configure System Settings**
   ```bash
   # Edit config.json for your setup
   nano config.json

   # Update ESP32 serial ports
   # Adjust detection thresholds
   # Set GPIO pin assignments
   ```

3. **Test Hardware Connections**
   ```bash
   # Run hardware test
   python test_hardware.py
   ```

## ðŸš€ Running the System

### Start with GUI Dashboard
```bash
# Activate virtual environment
source .venv/bin/activate

# Run with GUI dashboard
python main.py
```

### Console Mode (Headless)
```bash
# Run without GUI
python main.py --no-gui
```

### Testing Individual Components
```bash
# Test thermal detection
python raspberry_pi/thermal_detection.py

# Test RF receiver
python raspberry_pi/rf_receiver.py

# Test alert system
python raspberry_pi/alert_system.py
```

##  How It Works

### Detection Process

1. **RF Scanning**: ESP32 boards continuously scan for WiFi and BLE devices
2. **Signal Processing**: Raspberry Pi collects RSSI values from all ESP32s
3. **Triangulation**: Calculate approximate device positions using RSSI data
4. **Thermal Analysis**: MLX90640 detects heat signatures and identifies hotspots
5. **Correlation**: Match RF positions with thermal hotspots
6. **Alert Generation**: Trigger laser pointing and audio/visual alerts

### Detection Scenarios

- **RF + Thermal**: High confidence device detection (active phone/laptop)
- **RF Only**: Device in airplane mode or signal blocked
- **Thermal Only**: Device without RF signature or RF interference

### Alert System

When a device is detected with sufficient confidence:
1. Servo motors point laser at estimated device location
2. Laser activates to highlight the detection
3. Buzzer sounds audio alert
4. LED provides visual confirmation
5. GUI dashboard updates with detection information

##  Configuration

### Key Settings (config.json)

```json
{
  "thermal": {
    "temp_threshold": 30,        // Hotspot temperature threshold (Â°C)
    "refresh_rate": 4,           // Thermal sensor refresh rate (Hz)
    "hotspot_min_size": 3,       // Minimum hotspot size (pixels)
    "hotspot_max_size": 20       // Maximum hotspot size (pixels)
  },
  "detection": {
    "confidence_threshold": 0.7,  // Minimum confidence for alerts
    "min_detection_time": 2       // Minimum detection duration (seconds)
  },
  "alert": {
    "alert_duration": 5           // Alert duration (seconds)
  }
}
```

##  Troubleshooting

### Common Issues

1. **MLX90640 Not Detected**
   ```bash
   # Check I2C connection
   sudo i2cdetect -y 1
   # Should show device at address 0x33
   ```

2. **ESP32 Connection Issues**
   ```bash
   # Check USB connections
   ls /dev/ttyUSB*
   # Update serial ports in config.json
   ```

3. **Servo Jitter**
   ```bash
   # Check power supply capacity
   # Ensure proper GPIO connections
   # Adjust PWM frequency if needed
   ```

4. **Permission Denied (GPIO)**
   ```bash
   # Add user to gpio group
   sudo usermod -a -G gpio $USER
   # Logout and login again
   ```

### Performance Optimization

- **Thermal Processing**: Adjust refresh rate based on CPU capability
- **RF Scanning**: Modify scan intervals for power vs responsiveness trade-off  
- **Alert Sensitivity**: Tune confidence thresholds to reduce false positives

##  Future Enhancements

- **Camera Integration**: Add visual confirmation with object detection
- **Machine Learning**: Improve device classification accuracy
- **Cloud Dashboard**: Remote monitoring capabilities
- **Mobile App**: Smartphone control interface
- **mmWave Radar**: Enhanced detection through obstacles
- **Multi-room Support**: Scale to larger facilities

##  Security & Privacy

- All detection data is processed locally
- No personal data is stored or transmitted
- MAC addresses are hashed for privacy
- Thermal images contain no identifying information
- System operates independently without internet connection

##  License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

##  Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Create a Pull Request

##  Support

For issues, questions, or contributions, please:
- Open an issue on GitHub
- Contact the development team
- Check the troubleshooting guide

##  Disclaimer

This system is designed for legitimate security purposes in authorized environments only. Users must comply with local laws and regulations regarding privacy, surveillance, and RF monitoring. The developers are not responsible for misuse of this technology.

---

**ExamShield Team** - Smart Security Through Innovation
