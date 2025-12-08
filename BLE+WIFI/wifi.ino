#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_now.h>

// Your WiFi credentials
const char* ssid = "sejong-guest";
const char* password = "0234083114";

// Server configuration
const int serverPort = 8888;
const int maxClients = 1;

// Packet structure
#pragma pack(push, 1)
typedef struct {
  uint8_t mac[6];        // Source MAC address
  int8_t rssi;           // Signal strength
  uint32_t timestamp;    // Timestamp
  uint16_t packet_len;   // Packet length
  uint8_t channel;       // Channel number
  uint8_t packet_type;   // Packet type (0: management, 1: data, 2: control)
} packet_info_t;
#pragma pack(pop)

WiFiServer server(serverPort);
WiFiClient client;

// Variables for channel hopping
int currentChannel = 1;
const int maxChannel = 14;
unsigned long lastChannelChange = 0;
const unsigned long channelDwellTime = 500;  // ms per channel

// Statistics
unsigned long packetCount = 0;
unsigned long startTime = 0;

// Buffer for queuing packets
#define MAX_QUEUE_SIZE 50
packet_info_t packetQueue[MAX_QUEUE_SIZE];
int queueFront = 0;
int queueRear = 0;
int queueSize = 0;

// Promiscuous mode callback
void IRAM_ATTR wifi_sniffer_packet_handler(void* buff, wifi_promiscuous_pkt_type_t type) {
  wifi_promiscuous_pkt_t* ppkt = (wifi_promiscuous_pkt_t*)buff;
  
  // Only process valid packets
  if (ppkt->rx_ctrl.sig_len > 0) {
    packet_info_t pkt_info;
    
    // Extract MAC from packet
    if (ppkt->rx_ctrl.sig_len >= 10) {  // Minimum size for MAC header
      uint8_t* frame = ppkt->payload;
      
      // Frame control field (first 2 bytes)
      uint16_t frameControl = (frame[0] << 8) | frame[1];
      
      // Determine packet type from frame control
      uint8_t typeSubtype = (frame[0] >> 2) & 0x3F;
      if (typeSubtype == 0x08) pkt_info.packet_type = 0;  // Beacon
      else if (typeSubtype == 0x00) pkt_info.packet_type = 0;  // Association request
      else if ((typeSubtype & 0x04) == 0x08) pkt_info.packet_type = 1;  // Data
      else pkt_info.packet_type = 2;  // Control or other
      
      // Extract source MAC (address 2 in 802.11 frame)
      if (ppkt->rx_ctrl.sig_len >= 16) {
        memcpy(pkt_info.mac, &frame[10], 6);  // Source address at offset 10
      } else {
        memset(pkt_info.mac, 0, 6);
      }
    } else {
      memset(pkt_info.mac, 0, 6);
      pkt_info.packet_type = 2;
    }
    
    pkt_info.rssi = ppkt->rx_ctrl.rssi;
    pkt_info.timestamp = ppkt->rx_ctrl.timestamp;
    pkt_info.packet_len = ppkt->rx_ctrl.sig_len;
    pkt_info.channel = currentChannel;
    
    // Add to queue
    if (queueSize < MAX_QUEUE_SIZE) {
      packetQueue[queueRear] = pkt_info;
      queueRear = (queueRear + 1) % MAX_QUEUE_SIZE;
      queueSize++;
      packetCount++;
    }
  }
}

bool addToQueue(packet_info_t pkt) {
  if (queueSize < MAX_QUEUE_SIZE) {
    packetQueue[queueRear] = pkt;
    queueRear = (queueRear + 1) % MAX_QUEUE_SIZE;
    queueSize++;
    return true;
  }
  return false;
}

packet_info_t removeFromQueue() {
  packet_info_t pkt;
  if (queueSize > 0) {
    pkt = packetQueue[queueFront];
    queueFront = (queueFront + 1) % MAX_QUEUE_SIZE;
    queueSize--;
  }
  return pkt;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n======================================");
  Serial.println("ESP32 WiFi Sniffer - All Channel Scan");
  Serial.println("======================================\n");
  
  // Connect to your WiFi network
  Serial.print("Connecting to WiFi: ");
  Serial.println(ssid);
  
  WiFi.begin(ssid, password);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nFailed to connect to WiFi. Starting AP mode...");
    // Fallback to AP mode
    WiFi.mode(WIFI_AP);
    WiFi.softAP("ESP32-Sniffer", "sniffer123");
    Serial.print("AP IP: ");
    Serial.println(WiFi.softAPIP());
  }
  
  // Start TCP server
  server.begin();
  server.setNoDelay(true);
  Serial.print("TCP Server started on port ");
  Serial.println(serverPort);
  
  // Initialize WiFi in promiscuous mode
  wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
  esp_wifi_init(&cfg);
  esp_wifi_set_storage(WIFI_STORAGE_RAM);
  esp_wifi_set_mode(WIFI_MODE_NULL);
  esp_wifi_start();
  
  // Set promiscuous mode
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(&wifi_sniffer_packet_handler);
  
  // Start on channel 1
  esp_wifi_set_channel(currentChannel, WIFI_SECOND_CHAN_NONE);
  Serial.println("Sniffer initialized");
  Serial.println("Scanning all channels (1-14)...");
  
  startTime = millis();
  Serial.println("\nWaiting for client connection...");
}

void loop() {
  // Handle client connections
  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      Serial.println("\nClient connected!");
      client.println("ESP32 WiFi Sniffer Ready");
      client.println("Format: MAC,RSSI,Channel,Length,Type");
    }
  }
  
  // Channel hopping
  if (millis() - lastChannelChange >= channelDwellTime) {
    currentChannel++;
    if (currentChannel > maxChannel) {
      currentChannel = 1;
    }
    
    esp_wifi_set_channel(currentChannel, WIFI_SECOND_CHAN_NONE);
    lastChannelChange = millis();
    
    // Optional: Print channel change to serial
    static unsigned long lastPrint = 0;
    if (millis() - lastPrint >= 1000) {
      Serial.print("Channel: ");
      Serial.print(currentChannel);
      Serial.print(" | Packets: ");
      Serial.print(packetCount);
      Serial.print(" | Queue: ");
      Serial.println(queueSize);
      lastPrint = millis();
    }
  }
  
  // Send queued packets to client
  if (client && client.connected() && queueSize > 0) {
    int packetsToSend = min(queueSize, 10);  // Send up to 10 packets at once
    
    for (int i = 0; i < packetsToSend; i++) {
      packet_info_t pkt = removeFromQueue();
      
      // Send packet data
      client.write((uint8_t*)&pkt, sizeof(pkt));
      
      // Optional: Also send as CSV text for debugging
      char csvBuffer[100];
      snprintf(csvBuffer, sizeof(csvBuffer), "%02X:%02X:%02X:%02X:%02X:%02X,%d,%d,%d,%d",
               pkt.mac[0], pkt.mac[1], pkt.mac[2],
               pkt.mac[3], pkt.mac[4], pkt.mac[5],
               pkt.rssi, pkt.channel, pkt.packet_len, pkt.packet_type);
      client.println(csvBuffer);
    }
    client.flush();
  }
  
  delay(1);  // Small delay to prevent watchdog reset
}