"""
ExamShield Utility Functions
Provides common utility functions for the ExamShield system
"""

import json
import logging
import os
import time
from datetime import datetime
import math

def load_config(config_path="config.json"):
    """Load configuration from JSON file"""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file {config_path} not found")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"Error parsing configuration file: {e}")
        return None

def setup_logging(log_level="INFO", log_file="data/detections.log"):
    """Setup logging configuration"""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    return logging.getLogger(__name__)

def calculate_distance(rssi1, rssi2, rssi3, rssi4):
    """
    Calculate approximate position based on RSSI triangulation
    Using simplified RSSI-to-distance conversion
    """
    def rssi_to_distance(rssi):
        # Simple RSSI to distance conversion (approximate)
        if rssi == 0:
            return -1.0

        ratio = rssi * 1.0
        if ratio < 1.0:
            return math.pow(ratio, 10)
        else:
            accuracy = (0.89976) * math.pow(ratio, 7.7095) + 0.111
            return accuracy

    distances = [rssi_to_distance(rssi) for rssi in [rssi1, rssi2, rssi3, rssi4]]
    return distances

def trilaterate(distances, positions):
    """
    Simple trilateration to estimate position
    positions: list of (x, y) coordinates of ESP32 scanners
    distances: corresponding distances from each scanner
    """
    # Simplified 2D trilateration using first 3 points
    if len(distances) < 3 or len(positions) < 3:
        return None

    x1, y1 = positions[0]
    x2, y2 = positions[1]
    x3, y3 = positions[2]

    r1, r2, r3 = distances[0], distances[1], distances[2]

    # Trilateration calculation
    A = 2 * (x2 - x1)
    B = 2 * (y2 - y1)
    C = r1**2 - r2**2 - x1**2 + x2**2 - y1**2 + y2**2
    D = 2 * (x3 - x2)
    E = 2 * (y3 - y2)
    F = r2**2 - r3**2 - x2**2 + x3**2 - y2**2 + y3**2

    try:
        x = (C * E - F * B) / (E * A - B * D)
        y = (A * F - D * C) / (A * E - B * D)
        return (x, y)
    except ZeroDivisionError:
        return None

def detect_hotspots(thermal_frame, temp_threshold=30, min_size=3, max_size=20):
    """
    Detect potential device hotspots in thermal image
    Returns list of hotspot coordinates and sizes
    """
    import cv2
    import numpy as np

    # Threshold the thermal image
    _, binary = cv2.threshold(thermal_frame.astype(np.uint8), 
                             temp_threshold, 255, cv2.THRESH_BINARY)

    # Find contours
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    hotspots = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if min_size <= area <= max_size:
            # Get centroid
            M = cv2.moments(contour)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                hotspots.append({
                    'position': (cx, cy),
                    'area': area,
                    'contour': contour
                })

    return hotspots

def correlate_rf_thermal(rf_positions, thermal_hotspots, threshold=50):
    """
    Correlate RF detection positions with thermal hotspots
    Returns list of correlated detections
    """
    correlations = []

    for rf_pos in rf_positions:
        if rf_pos is None:
            continue

        for hotspot in thermal_hotspots:
            thermal_pos = hotspot['position']
            distance = math.sqrt(
                (rf_pos[0] - thermal_pos[0])**2 + 
                (rf_pos[1] - thermal_pos[1])**2
            )

            if distance <= threshold:
                correlations.append({
                    'rf_position': rf_pos,
                    'thermal_position': thermal_pos,
                    'correlation_distance': distance,
                    'hotspot_area': hotspot['area'],
                    'confidence': 1.0 - (distance / threshold)
                })

    return correlations

def log_detection(device_mac, position, detection_type, confidence):
    """Log a detection event"""
    timestamp = datetime.now().isoformat()
    log_entry = {
        'timestamp': timestamp,
        'device_mac': device_mac,
        'position': position,
        'detection_type': detection_type,
        'confidence': confidence
    }

    logging.info(f"Detection: {log_entry}")

    # Also save to CSV for analysis
    csv_file = "data/detections.csv"
    os.makedirs(os.path.dirname(csv_file), exist_ok=True)

    file_exists = os.path.isfile(csv_file)
    with open(csv_file, 'a') as f:
        if not file_exists:
            f.write("timestamp,device_mac,position_x,position_y,detection_type,confidence\n")

        pos_x = position[0] if position else 0
        pos_y = position[1] if position else 0
        f.write(f"{timestamp},{device_mac},{pos_x},{pos_y},{detection_type},{confidence}\n")

def cleanup_old_data(retention_days=30):
    """Clean up old detection data"""
    cutoff_time = time.time() - (retention_days * 24 * 60 * 60)

    # Clean up thermal images
    thermal_dir = "data/thermal_images"
    if os.path.exists(thermal_dir):
        for filename in os.listdir(thermal_dir):
            filepath = os.path.join(thermal_dir, filename)
            if os.path.getctime(filepath) < cutoff_time:
                os.remove(filepath)
                logging.info(f"Cleaned up old thermal image: {filename}")

def convert_servo_angle(x, y, image_width=32, image_height=24, 
                       servo_range_x=180, servo_range_y=180):
    """
    Convert image coordinates to servo angles for laser pointing
    """
    # Convert image coordinates to servo angles
    angle_x = int((x / image_width) * servo_range_x)
    angle_y = int((y / image_height) * servo_range_y)

    # Clamp to servo range
    angle_x = max(0, min(angle_x, servo_range_x))
    angle_y = max(0, min(angle_y, servo_range_y))

    return angle_x, angle_y
