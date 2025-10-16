"""
ExamShield RF Receiver Module
Receives and processes data from ESP32 BLE/WiFi scanners
"""

import serial
import threading
import time
import json
import logging
from queue import Queue
import re

class RFReceiver:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.serial_connections = {}
        self.data_queue = Queue()
        self.running = False
        self.threads = []

        # Device tracking
        self.detected_devices = {}
        self.esp32_positions = [
            (0, 0),      # ESP32 #1 - Top-left corner
            (100, 0),    # ESP32 #2 - Top-right corner  
            (0, 100),    # ESP32 #3 - Bottom-left corner
            (100, 100)   # ESP32 #4 - Bottom-right corner
        ]

    def start(self):
        """Start RF receiver threads"""
        self.running = True
        self.logger.info("Starting RF Receiver...")

        # Start serial connections to ESP32s
        for i, port in enumerate(self.config['esp32']['serial_ports']):
            try:
                self.connect_esp32(i, port)
            except Exception as e:
                self.logger.error(f"Failed to connect to ESP32 on {port}: {e}")

        # Start data processing thread
        processing_thread = threading.Thread(target=self._process_data)
        processing_thread.daemon = True
        processing_thread.start()
        self.threads.append(processing_thread)

        self.logger.info(f"RF Receiver started with {len(self.serial_connections)} ESP32 connections")

    def connect_esp32(self, esp32_id, port):
        """Connect to individual ESP32"""
        try:
            ser = serial.Serial(
                port=port,
                baudrate=self.config['esp32']['baud_rate'],
                timeout=1
            )

            self.serial_connections[esp32_id] = ser

            # Start reading thread for this ESP32
            thread = threading.Thread(target=self._read_esp32_data, args=(esp32_id, ser))
            thread.daemon = True
            thread.start()
            self.threads.append(thread)

            self.logger.info(f"Connected to ESP32 #{esp32_id} on {port}")

        except serial.SerialException as e:
            self.logger.error(f"Could not connect to ESP32 on {port}: {e}")
            raise

    def _read_esp32_data(self, esp32_id, serial_connection):
        """Read data from individual ESP32"""
        while self.running:
            try:
                if serial_connection.in_waiting > 0:
                    line = serial_connection.readline().decode('utf-8').strip()
                    if line:
                        self._parse_esp32_data(esp32_id, line)

                time.sleep(0.1)  # Small delay to prevent CPU overload

            except Exception as e:
                self.logger.error(f"Error reading from ESP32 #{esp32_id}: {e}")
                time.sleep(1)

    def _parse_esp32_data(self, esp32_id, data_line):
        """Parse data received from ESP32"""
        try:
            # Expected format: "DEVICE:MAC_ADDRESS:RSSI:TYPE"
            # Example: "DEVICE:AA:BB:CC:DD:EE:FF:-45:WiFi"
            if data_line.startswith("DEVICE:"):
                parts = data_line.split(":")
                if len(parts) >= 4:
                    mac_address = ":".join(parts[1:7])  # MAC address parts
                    rssi = int(parts[7])
                    device_type = parts[8] if len(parts) > 8 else "Unknown"

                    # Add to data queue for processing
                    detection_data = {
                        'esp32_id': esp32_id,
                        'mac_address': mac_address,
                        'rssi': rssi,
                        'device_type': device_type,
                        'timestamp': time.time(),
                        'position': self.esp32_positions[esp32_id]
                    }

                    self.data_queue.put(detection_data)

                    if self.config['system']['debug_mode']:
                        self.logger.debug(f"ESP32 #{esp32_id} detected: {mac_address} ({rssi} dBm)")

        except Exception as e:
            self.logger.error(f"Error parsing ESP32 data '{data_line}': {e}")

    def _process_data(self):
        """Process queued RF detection data"""
        while self.running:
            try:
                if not self.data_queue.empty():
                    detection = self.data_queue.get()
                    self._update_device_tracking(detection)

                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"Error processing RF data: {e}")

    def _update_device_tracking(self, detection):
        """Update device tracking with new detection"""
        mac = detection['mac_address']

        # Initialize device tracking if new device
        if mac not in self.detected_devices:
            self.detected_devices[mac] = {
                'first_seen': detection['timestamp'],
                'last_seen': detection['timestamp'],
                'detections': [],
                'estimated_position': None
            }

        # Update device info
        device = self.detected_devices[mac]
        device['last_seen'] = detection['timestamp']
        device['detections'].append(detection)

        # Keep only recent detections (last 30 seconds)
        cutoff_time = detection['timestamp'] - 30
        device['detections'] = [
            d for d in device['detections'] 
            if d['timestamp'] > cutoff_time
        ]

        # Estimate position if we have multiple ESP32 detections
        self._estimate_device_position(mac)

    def _estimate_device_position(self, mac_address):
        """Estimate device position using RSSI triangulation"""
        if mac_address not in self.detected_devices:
            return

        device = self.detected_devices[mac_address]
        recent_detections = device['detections']

        # Get latest RSSI from each ESP32
        esp32_rssi = {}
        for detection in recent_detections:
            esp32_id = detection['esp32_id']
            # Keep the strongest (most recent) signal from each ESP32
            if esp32_id not in esp32_rssi or detection['rssi'] > esp32_rssi[esp32_id]['rssi']:
                esp32_rssi[esp32_id] = detection

        # Need at least 3 ESP32 detections for triangulation
        if len(esp32_rssi) >= 3:
            from utils import calculate_distance, trilaterate

            positions = []
            distances = []

            for esp32_id in sorted(esp32_rssi.keys()):
                detection = esp32_rssi[esp32_id]
                positions.append(detection['position'])
                # Convert RSSI to approximate distance
                distance = self._rssi_to_distance(detection['rssi'])
                distances.append(distance)

            # Perform triangulation
            estimated_pos = trilaterate(distances, positions)
            if estimated_pos:
                device['estimated_position'] = estimated_pos
                self.logger.debug(f"Device {mac_address} estimated position: {estimated_pos}")

    def _rssi_to_distance(self, rssi):
        """Convert RSSI to approximate distance in meters"""
        if rssi == 0:
            return -1.0

        # Simple path loss model: RSSI = -10*n*log10(d) + A
        # Where n=2 (free space), A=-30 (reference RSSI at 1m)
        # Solving for d: d = 10^((A - RSSI) / (10 * n))
        n = 2.0  # Path loss exponent
        A = -30  # Reference RSSI at 1 meter

        distance = 10 ** ((A - rssi) / (10 * n))
        return max(distance, 0.1)  # Minimum 10cm

    def get_detected_devices(self):
        """Get currently detected devices"""
        current_time = time.time()
        active_devices = {}

        for mac, device in self.detected_devices.items():
            # Only include devices seen in last 10 seconds
            if current_time - device['last_seen'] <= 10:
                active_devices[mac] = device

        return active_devices

    def get_estimated_positions(self):
        """Get estimated positions of detected devices"""
        positions = []
        active_devices = self.get_detected_devices()

        for mac, device in active_devices.items():
            if device['estimated_position']:
                positions.append({
                    'mac_address': mac,
                    'position': device['estimated_position'],
                    'confidence': self._calculate_position_confidence(device)
                })

        return positions

    def _calculate_position_confidence(self, device):
        """Calculate confidence in position estimate"""
        # Confidence based on number of ESP32s detecting the device
        # and signal strength consistency
        detections = device['detections']
        if not detections:
            return 0.0

        # Count unique ESP32s
        unique_esp32s = len(set(d['esp32_id'] for d in detections))

        # Base confidence on number of detecting ESP32s
        base_confidence = min(unique_esp32s / 4.0, 1.0)  # Max confidence with all 4 ESP32s

        # Adjust based on signal strength (stronger signals = higher confidence)
        avg_rssi = sum(d['rssi'] for d in detections) / len(detections)
        rssi_factor = max(0.1, min(1.0, (avg_rssi + 100) / 50))  # Normalize RSSI to 0.1-1.0

        return base_confidence * rssi_factor

    def stop(self):
        """Stop RF receiver"""
        self.running = False
        self.logger.info("Stopping RF Receiver...")

        # Close all serial connections
        for ser in self.serial_connections.values():
            try:
                ser.close()
            except:
                pass

        # Wait for threads to finish
        for thread in self.threads:
            thread.join(timeout=2)

        self.logger.info("RF Receiver stopped")

# Test function
def test_rf_receiver():
    """Test RF receiver functionality"""
    from utils import load_config, setup_logging

    config = load_config()
    if not config:
        print("Failed to load config")
        return

    setup_logging(config['system']['log_level'])

    rf_receiver = RFReceiver(config)

    try:
        rf_receiver.start()

        # Run for 30 seconds for testing
        for i in range(30):
            time.sleep(1)
            devices = rf_receiver.get_detected_devices()
            positions = rf_receiver.get_estimated_positions()

            print(f"\rActive devices: {len(devices)}, Positions: {len(positions)}", end="")

        print("\nTest completed")

    except KeyboardInterrupt:
        print("\nTest interrupted")
    finally:
        rf_receiver.stop()

if __name__ == "__main__":
    test_rf_receiver()
