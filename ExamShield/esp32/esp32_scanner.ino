/*
 * ExamShield ESP32 Scanner
 * Scans for BLE and WiFi devices and reports findings via serial
 * 
 * Hardware: ESP32 Development Board
 * Author: ExamShield Team
 * Version: 1.0
 */

#include "WiFi.h"
#include "BLEDevice.h"
#include "BLEUtils.h"
#include "BLEScan.h"
#include "BLEAdvertisedDevice.h"

// Configuration
#define SCAN_INTERVAL 5000    // Scan interval in milliseconds
#define WIFI_SCAN_TIME 3      // WiFi scan time in seconds
#define BLE_SCAN_TIME 3       // BLE scan time in seconds
#define SERIAL_BAUD 115200    // Serial communication baud rate

// Global variables
BLEScan* pBLEScan;
unsigned long lastScanTime = 0;
int scanCounter = 0;

// Device tracking
struct DeviceInfo {
  String macAddress;
  int rssi;
  String deviceType;
  unsigned long lastSeen;
};

// Storage for detected devices
std::vector<DeviceInfo> detectedDevices;
const int MAX_DEVICES = 50;

class MyAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
  void onResult(BLEAdvertisedDevice advertisedDevice) {
    // Extract device information
    String macAddr = advertisedDevice.getAddress().toString().c_str();
    int rssi = advertisedDevice.getRSSI();
    String deviceName = advertisedDevice.getName().c_str();

    // Determine device type based on name or manufacturer data
    String deviceType = "BLE";
    if (deviceName.length() > 0) {
      deviceName.toLowerCase();
      if (deviceName.indexOf("iphone") >= 0 || deviceName.indexOf("apple") >= 0) {
        deviceType = "iPhone";
      } else if (deviceName.indexOf("samsung") >= 0 || deviceName.indexOf("galaxy") >= 0) {
        deviceType = "Samsung";
      } else if (deviceName.indexOf("pixel") >= 0 || deviceName.indexOf("android") >= 0) {
        deviceType = "Android";
      } else if (deviceName.indexOf("watch") >= 0) {
        deviceType = "Smartwatch";
      } else if (deviceName.indexOf("buds") >= 0 || deviceName.indexOf("airpod") >= 0) {
        deviceType = "Earbuds";
      }
    }

    // Store or update device information
    updateDeviceList(macAddr, rssi, deviceType);
  }
};

void setup() {
  Serial.begin(SERIAL_BAUD);
  delay(1000);

  Serial.println("ExamShield ESP32 Scanner Starting...");

  // Initialize WiFi in station mode
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);

  // Initialize BLE
  Serial.println("Initializing BLE...");
  BLEDevice::init("");
  pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new MyAdvertisedDeviceCallbacks());
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);

  Serial.println("ESP32 Scanner Ready");
  Serial.println("Format: DEVICE:MAC_ADDRESS:RSSI:TYPE");
}

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastScanTime >= SCAN_INTERVAL) {
    scanCounter++;

    Serial.println("SCAN_START:" + String(scanCounter));

    // Scan WiFi networks
    scanWiFiDevices();

    // Small delay between scans
    delay(500);

    // Scan BLE devices
    scanBLEDevices();

    // Clean up old devices (older than 30 seconds)
    cleanupOldDevices();

    // Send heartbeat
    Serial.println("HEARTBEAT:" + String(currentTime));

    Serial.println("SCAN_END:" + String(scanCounter));

    lastScanTime = currentTime;
  }

  delay(100); // Small delay to prevent CPU overload
}

void scanWiFiDevices() {
  Serial.println("Scanning WiFi devices...");

  int networkCount = WiFi.scanNetworks();

  if (networkCount == 0) {
    Serial.println("No WiFi networks found");
  } else {
    for (int i = 0; i < networkCount; ++i) {
      String ssid = WiFi.SSID(i);
      String bssid = WiFi.BSSIDstr(i);
      int rssi = WiFi.RSSI(i);

      // Determine device type based on SSID patterns
      String deviceType = "WiFi";
      ssid.toLowerCase();

      if (ssid.indexOf("iphone") >= 0 || ssid.indexOf("apple") >= 0) {
        deviceType = "iPhone_Hotspot";
      } else if (ssid.indexOf("samsung") >= 0 || ssid.indexOf("galaxy") >= 0) {
        deviceType = "Samsung_Hotspot";
      } else if (ssid.indexOf("android") >= 0 || ssid.indexOf("pixel") >= 0) {
        deviceType = "Android_Hotspot";
      } else if (ssid.indexOf("direct") >= 0) {
        deviceType = "WiFi_Direct";
      }

      // Update device list
      updateDeviceList(bssid, rssi, deviceType);

      delay(10); // Small delay between processing
    }
  }

  // Clear WiFi scan results to free memory
  WiFi.scanDelete();
}

void scanBLEDevices() {
  Serial.println("Scanning BLE devices...");

  BLEScanResults foundDevices = pBLEScan->start(BLE_SCAN_TIME, false);
  int deviceCount = foundDevices.getCount();

  Serial.println("BLE scan found " + String(deviceCount) + " devices");

  // Results are processed in the callback function
  // Clear results to free memory
  pBLEScan->clearResults();
}

void updateDeviceList(String macAddress, int rssi, String deviceType) {
  bool deviceFound = false;
  unsigned long currentTime = millis();

  // Check if device already exists in our list
  for (int i = 0; i < detectedDevices.size(); i++) {
    if (detectedDevices[i].macAddress == macAddress) {
      // Update existing device
      detectedDevices[i].rssi = rssi;
      detectedDevices[i].deviceType = deviceType;
      detectedDevices[i].lastSeen = currentTime;
      deviceFound = true;
      break;
    }
  }

  // Add new device if not found and we have space
  if (!deviceFound && detectedDevices.size() < MAX_DEVICES) {
    DeviceInfo newDevice;
    newDevice.macAddress = macAddress;
    newDevice.rssi = rssi;
    newDevice.deviceType = deviceType;
    newDevice.lastSeen = currentTime;
    detectedDevices.push_back(newDevice);
  }

  // Send device information to Raspberry Pi
  Serial.println("DEVICE:" + macAddress + ":" + String(rssi) + ":" + deviceType);
}

void cleanupOldDevices() {
  unsigned long currentTime = millis();
  const unsigned long DEVICE_TIMEOUT = 30000; // 30 seconds

  // Remove devices that haven't been seen for a while
  for (int i = detectedDevices.size() - 1; i >= 0; i--) {
    if (currentTime - detectedDevices[i].lastSeen > DEVICE_TIMEOUT) {
      Serial.println("DEVICE_LOST:" + detectedDevices[i].macAddress);
      detectedDevices.erase(detectedDevices.begin() + i);
    }
  }
}

// Function to handle serial commands from Raspberry Pi (optional)
void handleSerialCommands() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "STATUS") {
      Serial.println("STATUS:OK");
      Serial.println("DEVICES_TRACKED:" + String(detectedDevices.size()));
      Serial.println("UPTIME:" + String(millis()));

    } else if (command == "RESET") {
      detectedDevices.clear();
      Serial.println("RESET:OK");

    } else if (command == "LIST_DEVICES") {
      for (const auto& device : detectedDevices) {
        Serial.println("STORED_DEVICE:" + device.macAddress + ":" + 
                      String(device.rssi) + ":" + device.deviceType + ":" + 
                      String(millis() - device.lastSeen));
      }
    }
  }
}