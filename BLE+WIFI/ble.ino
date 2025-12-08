#include <BLEDevice.h>
#include <BLEUtils.h>
#include <BLEScan.h>
#include <BLEAdvertisedDevice.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ArduinoJson.h>
#include <map>
#include <math.h>
#include <vector>
#include <algorithm>

// WiFi credentials
const char* ssid = "sejong-guest";
const char* password = "0234083114";

// UDP settings
WiFiUDP udp;
const char* targetIP = "172.19.5.15"; // ← laptop IP
const unsigned int udpPort = 12345;

// Scan parameters
int scanTime = 5; // Reduced scan time for more frequent scanning
BLEScan* pBLEScan;
int scanCount = 0;
const int REQUIRED_SCANS = 10; // Number of scans to perform
const int MIN_SEEN_COUNT = 5;  // Minimum times device must be seen

// Structure to store device information
struct BLEDeviceInfo {
  std::string address;
  std::string name;
  int rssi;
  float distance;
  int seenCount;
  unsigned long lastSeen;
  unsigned long firstSeen;
};

std::map<std::string, BLEDeviceInfo> knownDevices;

// Function declarations 
void sendUDPData(const char* eventType, const BLEDeviceInfo& device);
void sendFrequentDevicesSummary();
void cleanupOldDevices();
void printFrequentDevices();

// WiFi Setup
void setupWiFi() {
  Serial.println();
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(1000);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("");
    Serial.println("WiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("");
    Serial.println("Failed to connect to WiFi. Continuing without WiFi...");
  }
}

// Send data via UDP
void sendUDPData(const char* eventType, const BLEDeviceInfo& device) {
  if (WiFi.status() != WL_CONNECTED) return;

  DynamicJsonDocument doc(512);
  doc["event"] = eventType;
  doc["device"]["name"] = device.name;
  doc["device"]["address"] = device.address;
  doc["device"]["rssi"] = device.rssi;
  doc["device"]["distance"] = device.distance;
  doc["device"]["seenCount"] = device.seenCount;
  doc["device"]["lastSeen"] = (millis() - device.lastSeen) / 1000;
  doc["device"]["firstSeen"] = (millis() - device.firstSeen) / 1000;
  doc["timestamp"] = millis();

  String jsonString;
  serializeJson(doc, jsonString);
  
  udp.beginPacket(targetIP, udpPort);
  udp.write((const uint8_t*)jsonString.c_str(), jsonString.length());
  udp.endPacket();
}

// Send summary of frequently seen devices
void sendFrequentDevicesSummary() {
  if (WiFi.status() != WL_CONNECTED) return;

  // Get devices seen 5+ times within 5 meters
  std::vector<std::pair<std::string, BLEDeviceInfo>> frequentDevices;
  for (const auto& device : knownDevices) {
    if (device.second.seenCount >= MIN_SEEN_COUNT) {
      frequentDevices.push_back(device);
    }
  }
  
  if (frequentDevices.empty()) {
    // Send empty summary
    DynamicJsonDocument doc(256);
    doc["event"] = "FREQUENT_DEVICES_SUMMARY";
    doc["totalScans"] = scanCount;
    doc["frequentDevicesCount"] = 0;
    doc["message"] = "No devices seen 5+ times yet";
    doc["scanTimestamp"] = millis();
    
    String jsonString;
    serializeJson(doc, jsonString);
    
    udp.beginPacket(targetIP, udpPort);
    udp.write((const uint8_t*)jsonString.c_str(), jsonString.length());
    udp.endPacket();
    return;
  }
  
  // Sort frequent devices by distance (closest first)
  std::sort(frequentDevices.begin(), frequentDevices.end(), 
    [](const std::pair<std::string, BLEDeviceInfo>& a, 
       const std::pair<std::string, BLEDeviceInfo>& b) {
      return a.second.distance < b.second.distance;
    });
  
  // Take only the closest 10 frequent devices
  int devicesToSend = std::min(10, (int)frequentDevices.size());

  DynamicJsonDocument doc(2048);
  doc["event"] = "FREQUENT_DEVICES_SUMMARY";
  doc["totalScans"] = scanCount;
  doc["totalDevices"] = knownDevices.size();
  doc["frequentDevicesCount"] = frequentDevices.size();
  doc["closestFrequentDevices"] = devicesToSend;
  doc["scanTimestamp"] = millis();
  
  JsonArray devices = doc.createNestedArray("devices");
  
  for (int i = 0; i < devicesToSend; i++) {
    const BLEDeviceInfo& info = frequentDevices[i].second;
    JsonObject dev = devices.createNestedObject();
    dev["name"] = info.name;
    dev["address"] = info.address;
    dev["rssi"] = info.rssi;
    dev["distance"] = info.distance;
    dev["seenCount"] = info.seenCount;
    dev["lastSeen"] = (millis() - info.lastSeen) / 1000;
    dev["firstSeen"] = (millis() - info.firstSeen) / 1000;
    dev["rank"] = i + 1; // Add rank (1 = closest)
  }

  String jsonString;
  serializeJson(doc, jsonString);
  
  udp.beginPacket(targetIP, udpPort);
  udp.write((const uint8_t*)jsonString.c_str(), jsonString.length());
  udp.endPacket();
}

class EnhancedAdvertisedDeviceCallbacks: public BLEAdvertisedDeviceCallbacks {
  private:
    float calculateDistance(int rssi, int txPower = -59) {
      if (rssi == 0) {
        return -1.0;
      }
      
      float ratio = rssi * 1.0 / txPower;
      if (ratio < 1.0) {
        return pow(ratio, 10);
      } else {
        return (0.89976) * pow(ratio, 7.7095) + 0.111;
      }
    }

  public:
    void onResult(BLEAdvertisedDevice advertisedDevice) {
      int rssi = advertisedDevice.getRSSI();
      float distance = calculateDistance(rssi);
      std::string address = advertisedDevice.getAddress().toString();
      std::string name = advertisedDevice.getName();
      
      if (name.empty()) {
        name = "Unknown";
      }
      
      // ONLY PROCESS DEVICES WITHIN 5 METERS
      if (distance > 0 && distance <= 5.0) {
        unsigned long currentTime = millis();
        
        // Check if we've seen this device before
        if (knownDevices.find(address) == knownDevices.end()) {
          // New device
          BLEDeviceInfo newDevice;
          newDevice.address = address;
          newDevice.name = name;
          newDevice.rssi = rssi;
          newDevice.distance = distance;
          newDevice.seenCount = 1;
          newDevice.lastSeen = currentTime;
          newDevice.firstSeen = currentTime;
          knownDevices[address] = newDevice;
        } else {
          // Update existing device - use the closest distance seen
          if (distance < knownDevices[address].distance) {
            knownDevices[address].distance = distance;
          }
          knownDevices[address].rssi = rssi; // Use latest RSSI
          knownDevices[address].seenCount++;
          knownDevices[address].lastSeen = currentTime;
        }
      }
    }
};

// Print frequently seen devices (5+ times within 5 meters)
void printFrequentDevices() {
  Serial.println("\n📊 FREQUENT DEVICES SUMMARY (Seen 5+ times within 5m)");
  Serial.println("====================================================");
  Serial.printf("Total scans performed: %d\n", scanCount);
  Serial.printf("Total devices tracked: %d\n", knownDevices.size());
  
  // Get devices seen 5+ times
  std::vector<std::pair<std::string, BLEDeviceInfo>> frequentDevices;
  for (const auto& device : knownDevices) {
    if (device.second.seenCount >= MIN_SEEN_COUNT) {
      frequentDevices.push_back(device);
    }
  }
  
  if (frequentDevices.empty()) {
    Serial.println("No devices seen 5+ times within 5 meters yet.");
    Serial.println("Continuing scans...");
    return;
  }
  
  // Sort by distance (closest first)
  std::sort(frequentDevices.begin(), frequentDevices.end(), 
    [](const std::pair<std::string, BLEDeviceInfo>& a, 
       const std::pair<std::string, BLEDeviceInfo>& b) {
      return a.second.distance < b.second.distance;
    });
  
  // Print only the closest 10 frequent devices
  int devicesToPrint = std::min(10, (int)frequentDevices.size());
  
  Serial.printf("Devices seen 5+ times: %d\n", frequentDevices.size());
  Serial.printf("Showing closest %d frequent devices:\n", devicesToPrint);
  Serial.println();
  
  for (int i = 0; i < devicesToPrint; i++) {
    const BLEDeviceInfo& info = frequentDevices[i].second;
    unsigned long timeSinceSeen = (millis() - info.lastSeen) / 1000;
    unsigned long timeSinceFirstSeen = (millis() - info.firstSeen) / 1000;
    
    Serial.printf("📍 #%d %s\n", i + 1, info.name.c_str());
    Serial.printf("   Address: %s\n", info.address.c_str());
    Serial.printf("   Last RSSI: %d dBm\n", info.rssi);
    Serial.printf("   Closest Distance: %.2f meters\n", info.distance);
    Serial.printf("   Seen: %d times\n", info.seenCount);
    Serial.printf("   Last seen: %lu seconds ago\n", timeSinceSeen);
    Serial.printf("   First seen: %lu seconds ago\n", timeSinceFirstSeen);
    Serial.println("   ---");
  }
  
  if (frequentDevices.size() > 10) {
    Serial.printf("... and %d more frequent devices\n", frequentDevices.size() - 10);
  }
}

void cleanupOldDevices() {
  unsigned long currentTime = millis();
  const unsigned long TIMEOUT = 60000; // 60 seconds (longer timeout for tracking)
  
  for (auto it = knownDevices.begin(); it != knownDevices.end(); ) {
    if (currentTime - it->second.lastSeen > TIMEOUT) {
      Serial.printf("Removing inactive device: %s\n", it->second.name.c_str());
      it = knownDevices.erase(it);
    } else {
      ++it;
    }
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("🚀 ESP32 Enhanced BLE Scanner");
  Serial.println("📏 Tracking devices within 5 meters");
  Serial.println("⭐ Showing devices seen 5+ times (closest 10 only)");
  Serial.println("🔄 Performing 10 scans before showing results");
  Serial.printf("🎯 Target IP: %s:%d\n", targetIP, udpPort);
  Serial.println("=====================================\n");
  
  // Setup WiFi
  setupWiFi();
  
  // Setup UDP
  udp.begin(udpPort);
  Serial.printf("UDP client started, sending to %s:%d\n", targetIP, udpPort);
  
  // Setup BLE
  BLEDevice::init("ESP32-BLE-Scanner");
  
  pBLEScan = BLEDevice::getScan();
  pBLEScan->setAdvertisedDeviceCallbacks(new EnhancedAdvertisedDeviceCallbacks());
  pBLEScan->setActiveScan(true);
  pBLEScan->setInterval(100);
  pBLEScan->setWindow(99);
}

void loop() {
  scanCount++;
  Serial.printf("\n🔍 Scan #%d of %d...\n", scanCount, REQUIRED_SCANS);
  
  BLEScanResults foundDevices = pBLEScan->start(scanTime, false);
  
  Serial.printf("✅ Scan #%d completed! Processed %d advertisements\n", scanCount, foundDevices.getCount());
  Serial.printf("📈 Currently tracking %d devices\n", knownDevices.size());
  
  // Count devices seen 5+ times
  int frequentCount = 0;
  for (const auto& device : knownDevices) {
    if (device.second.seenCount >= MIN_SEEN_COUNT) {
      frequentCount++;
    }
  }
  Serial.printf("⭐ Devices seen 5+ times: %d\n", frequentCount);
  
  // Clean up old devices
  cleanupOldDevices();
  
  // After 10 scans, show frequent devices summary
  if (scanCount >= REQUIRED_SCANS) {
    Serial.println("\n==================================================");
    Serial.println("🎯 10 SCANS COMPLETED - GENERATING FINAL REPORT");
    Serial.println("==================================================");
    
    printFrequentDevices();
    sendFrequentDevicesSummary();
    
    // Reset scan count for continuous operation
    scanCount = 0;
    Serial.println("\n🔄 Resetting scan counter for next round...");
  }
  
  pBLEScan->clearResults();
  delay(2000); // Shorter delay between scans
}