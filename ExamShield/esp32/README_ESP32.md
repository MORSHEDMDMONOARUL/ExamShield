# ESP32 Scanner Setup Guide

This directory contains the Arduino firmware for the ESP32 BLE/WiFi scanners used in the ExamShield system.

## Hardware Requirements

- 4Ã— ESP32 development boards (ESP32-WROOM-32 or similar)
- USB cables for programming and power
- Optional: External 5V power supplies for standalone operation

## Software Requirements

1. **Arduino IDE** (version 1.8.13 or later)
2. **ESP32 Board Package** for Arduino IDE
3. Required libraries (usually pre-installed with ESP32 package):
   - WiFi
   - BLEDevice
   - BLEUtils
   - BLEScan

## Installation Steps

### 1. Install Arduino IDE
Download and install Arduino IDE from [arduino.cc](https://www.arduino.cc/en/software)

### 2. Add ESP32 Board Support
1. Open Arduino IDE
2. Go to **File** > **Preferences**
3. In "Additional Board Manager URLs" field, add:
   ```
   https://dl.espressif.com/dl/package_esp32_index.json
   ```
4. Click **OK**
5. Go to **Tools** > **Board** > **Boards Manager**
6. Search for "ESP32" and install "ESP32 by Espressif Systems"

### 3. Select Board and Port
1. Connect your ESP32 to computer via USB
2. Go to **Tools** > **Board** > **ESP32 Arduino**
3. Select your ESP32 board (e.g., "ESP32 Dev Module")
4. Go to **Tools** > **Port** and select the correct COM port

### 4. Upload Firmware
1. Open `esp32_scanner.ino` in Arduino IDE
2. Click the **Upload** button (â†’)
3. Wait for compilation and upload to complete
4. Open **Serial Monitor** (Tools > Serial Monitor)
5. Set baud rate to **115200**
6. You should see scanning output

### 5. Repeat for All ESP32s
Upload the same firmware to all 4 ESP32 boards.

## Firmware Features

### WiFi Scanning
- Scans for nearby WiFi networks
- Reports SSID, BSSID (MAC address), and RSSI
- Identifies device types based on SSID patterns:
  - iPhone_Hotspot (iPhone personal hotspots)
  - Samsung_Hotspot (Samsung hotspots)
  - Android_Hotspot (Android hotspots)
  - WiFi_Direct (WiFi Direct connections)

### BLE Scanning
- Scans for Bluetooth Low Energy devices
- Reports device MAC address, name, and RSSI
- Identifies device types based on device names:
  - iPhone (Apple devices)
  - Samsung (Samsung devices)
  - Android (Android devices)
  - Smartwatch (wearable devices)
  - Earbuds (audio devices)

### Serial Communication
The ESP32 sends data to the Raspberry Pi via serial connection using this format:

```
DEVICE:MAC_ADDRESS:RSSI:TYPE
```

Examples:
```
DEVICE:AA:BB:CC:DD:EE:FF:-45:iPhone
DEVICE:11:22:33:44:55:66:-67:Samsung_Hotspot
DEVICE:99:88:77:66:55:44:-52:BLE
```

### Serial Commands
The ESP32 accepts these commands from Raspberry Pi:

- `STATUS` - Returns system status
- `RESET` - Clears device list
- `LIST_DEVICES` - Lists all tracked devices

## Troubleshooting

### ESP32 Not Detected
1. Check USB cable (use data cable, not power-only)
2. Install CP210x or CH340 drivers if needed
3. Press and hold BOOT button while connecting USB
4. Try different USB port

### Upload Fails
1. Hold BOOT button during upload
2. Check board selection in Tools menu
3. Lower upload speed (Tools > Upload Speed > 115200)
4. Use different USB cable or port

### No Scanning Output
1. Open Serial Monitor (115200 baud)
2. Press RESET button on ESP32
3. Check for WiFi networks nearby
4. Ensure ESP32 has good antenna connection

### Serial Communication Issues
1. Check baud rate (115200)
2. Verify USB connection to Raspberry Pi
3. Check `/dev/ttyUSB*` devices on Pi
4. Update serial ports in `config.json`

## Positioning ESP32 Scanners

For optimal triangulation, position the 4 ESP32 boards at:

1. **ESP32 #1**: Top-left corner of monitored area
2. **ESP32 #2**: Top-right corner of monitored area  
3. **ESP32 #3**: Bottom-left corner of monitored area
4. **ESP32 #4**: Bottom-right corner of monitored area

### Mounting Tips
- Mount 1-2 meters above ground level
- Avoid metal obstacles between ESP32 and monitored area
- Ensure stable power supply
- Use USB extension cables if needed
- Consider weatherproof enclosures for permanent installation

## Power Considerations

### USB Power from Raspberry Pi
- Simple setup for development/testing
- Limited by Pi's USB power capacity
- May need powered USB hub for all 4 ESP32s

### External Power Supplies
- More reliable for production use
- Use 5V power supplies with micro-USB connectors
- Ensure common ground with Raspberry Pi
- Better for permanent installations

## Customization

### Scan Intervals
Modify these values in the code:
```cpp
#define SCAN_INTERVAL 5000    // Overall scan interval (ms)
#define WIFI_SCAN_TIME 3      // WiFi scan duration (seconds)
#define BLE_SCAN_TIME 3       // BLE scan duration (seconds)
```

### Device Type Detection
Add custom device type patterns in:
- `scanWiFiDevices()` function for WiFi devices
- `MyAdvertisedDeviceCallbacks::onResult()` for BLE devices

### Serial Output Format
Modify the output format in `updateDeviceList()` function.

## Performance Notes

- Each scan cycle takes ~6-8 seconds
- Memory usage increases with number of detected devices
- Automatic cleanup removes devices not seen for 30 seconds
- BLE scanning may interfere with WiFi scanning slightly

## Security Considerations

- ESP32s only listen for device advertisements
- No connection attempts are made to detected devices
- Only MAC addresses and signal strengths are recorded
- No personal data is accessed or stored

## Support

For ESP32-specific issues:
1. Check Arduino IDE error messages
2. Verify board and library versions
3. Test with simple ESP32 examples first
4. Check ESP32 documentation and forums

Remember to upload the firmware to all 4 ESP32 boards before running the complete ExamShield system!
