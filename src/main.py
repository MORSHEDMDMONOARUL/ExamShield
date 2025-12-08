"""
ExamShield - AI-Powered Exam Proctoring System
Version: 2.2.2
Author: Morshed MD Monoarul
"""

import cv2
import os
import time
import torch
import numpy as np
from datetime import datetime
from collections import deque
from ultralytics import YOLO
import threading
import queue
import logging
import subprocess
import sys

# Intel Arc GPU support (falls back to CPU if not available)
try:
    import torch_directml
    DIRECTML_AVAILABLE = True
except ImportError:
    DIRECTML_AVAILABLE = False

# ============================================================================
# LOGGING SETUP
# ============================================================================

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename='logs/examshield.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """System configuration - all settings in one place"""
    # Model and file paths
    DETECTION_MODEL = "runs/detect/examshield_yolov8s/weights/best.pt"
    LOG_FILE = "logs/detection_log.csv"
    PROOF_DIR = "proofs/alerts"
    REPORT_FILE = "session_report.txt"
    
    # AI detection
    IMG_SIZE = 416
    CONFIDENCE_THRESHOLD = 0.30
    
    # thresholds
    ALERT_THRESHOLD = {
        "phone": 0.45,
        "earphone": 0.30,
        "smartwatch": 0.50,
        "headrotation": 0.55,
        "paperpassing": 0.60
    }
    
    # Calibration multipliers
    CONFIDENCE_CALIBRATION = {
        "phone": 1.0,
        "earphone": 1.0,
        "smartwatch": 1.0,
        "headrotation": 1.2,
        "paperpassing": 1.3
    }
    
    # Video settings
    FRAME_WIDTH = 1280
    FRAME_HEIGHT = 720
    TARGET_FPS = 30
    FPS_WARNING_THRESHOLD = 15
    
    # Alert management
    ALERT_COOLDOWN = 10
    MAX_PHOTOS_PER_ALERT = 3
    PHOTO_INTERVAL = 2
    ALERT_FLASH_DURATION = 2.0
    
    # Behavioral detection
    HEAD_ROTATION_DURATION = 5
    EARPHONE_MIN_DETECTIONS = 3
    
    # UI settings
    SHOW_CONTROLS = True
    SHOW_STATS = True
    MAX_TIMELINE_ITEMS = 5
    
    # Keyboard controls
    SCREENSHOT_KEY = ord('s')
    HIDE_UI_KEY = ord('h')
    QUIT_KEY = ord('q')
    
    # Detection classes
    CHEATING_CLASSES = {
        "phone": {"priority": 1, "description": "Mobile phone usage"},
        "earphone": {"priority": 1, "description": "Earphone/earbud detected"},
        "smartwatch": {"priority": 2, "description": "Smartwatch usage"},
        "headrotation": {"priority": 2, "description": "Suspicious head movement"},
        "paperpassing": {"priority": 3, "description": "Paper exchange detected"}
    }
    
    # Ignore classes(maybe a new feature for calling proctor)
    IGNORED_CLASSES = ["hand_gestures", "handgesture", "hand_gesture"]
    
    # Multi-student tracking parameters
    PERSON_CLASS_ID = 0
    PERSON_CONFIDENCE = 0.5
    TRACKING_MAX_DISTANCE = 150 #(i will increase this value in the future)
    TRACKING_TIMEOUT = 3.0
    MAX_ASSOCIATION_DISTANCE = 300

    # UI colors (BGR format)
    COLOR_BG_DARK = (25, 25, 25)
    COLOR_BG_LIGHT = (40, 40, 40)
    COLOR_ACCENT = (198, 184, 50)
    COLOR_SUCCESS = (80, 175, 76)
    COLOR_WARNING = (0, 152, 255)
    COLOR_DANGER = (54, 67, 244)
    COLOR_TEXT_PRIMARY = (255, 255, 255)
    COLOR_TEXT_SECONDARY = (189, 189, 189)
    COLOR_SAFE = COLOR_SUCCESS
    COLOR_INFO = COLOR_ACCENT

# ============================================================================
# CAMERA HANDLER
# ============================================================================

class CameraHandler:
    """
    Threaded camera capture for better performance
    Uses a background thread to continuously read frames from camera.
    Main program just grabs latest frame when needed - no waiting!
    """
    
    def __init__(self):
        self.running = True
        self.frame_queue = queue.Queue(maxsize=2)  # just store latest 3 frames
        self._initialize_camera()
        self._start_capture_thread()
    
    def _initialize_camera(self):
        #Try different backends until camera works
        logging.info("Initializing camera...")
        
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        self.cap = None
        
        for backend in backends:
            self.cap = cv2.VideoCapture(0, backend)
            if self.cap.isOpened():
                break
        
        if not self.cap or not self.cap.isOpened():
            logging.error("Failed to initialize camera")
            raise RuntimeError("Failed to initialize camera")
        
        # Configure camera settings
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, 60)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Small buffer = less lag
        
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logging.info(f"Camera initialized: {width}x{height}")
    
    def _start_capture_thread(self):
        #Start background thread for frame capture
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
    
    def _capture_loop(self):
       #Runs in background and continuously grabs frames
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                try:
                    self.frame_queue.put_nowait(frame)  # Add to queue if not full
                except queue.Full:
                    pass  # Discard frame if queue is full
    
    def read(self):
        #Get latest frame from queue
        try:
            return self.frame_queue.get(timeout=0.2)
        except queue.Empty:
            return None
    
    def release(self):
        #Clean up camera resources
        self.running = False
        time.sleep(0.1)
        if self.cap:
            self.cap.release()
        logging.info("Camera released")

# ============================================================================
# PERSON TRACKER
# ============================================================================

class PersonTracker:
    """
    Tracks multiple students using centroid matching
    working method:
    - Calculate center point of each person's bounding box
    - Match people across frames by finding nearest centroids
    - Assign unique IDs that persist across frames
    """
    
    def __init__(self):
        self.next_id = 1
        self.persons = {}  # {person_id: {'bbox', 'centroid', 'last_seen'}}
    
    def update(self, person_boxes):
        #Update tracking with new person detections from current frame
        current_time = time.time()
        
        # Remove persons that haven't been seen recently (timeout)
        self.persons = {
            pid: data for pid, data in self.persons.items()
            if current_time - data['last_seen'] < Config.TRACKING_TIMEOUT
        }
        
        if len(person_boxes) == 0:
            return self.persons
        
        # Calculate centroids for new detections
        new_centroids = []
        for box in person_boxes:
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            new_centroids.append((cx, cy, box))
        
        # Match new detections to existing persons
        if len(self.persons) == 0:
            # First time - assign new IDs to everyone
            for cx, cy, box in new_centroids:
                self.persons[self.next_id] = {
                    'bbox': box,
                    'centroid': (cx, cy),
                    'last_seen': current_time
                }
                self.next_id += 1
        else:
            # Match based on nearest centroid (Euclidean distance)
            existing_ids = list(self.persons.keys())
            existing_centroids = [self.persons[pid]['centroid'] for pid in existing_ids]
            
            used_ids = set()
            
            for cx, cy, box in new_centroids:
                # Find closest existing person
                min_distance = float('inf')
                nearest_id = None
                
                for pid, (ex, ey) in zip(existing_ids, existing_centroids):
                    if pid in used_ids:
                        continue
                    distance = np.sqrt((cx - ex)**2 + (cy - ey)**2)
                    if distance < min_distance:
                        min_distance = distance
                        nearest_id = pid
                
                # Update existing or create new
                if nearest_id is not None and min_distance < Config.TRACKING_MAX_DISTANCE:
                    self.persons[nearest_id] = {
                        'bbox': box,
                        'centroid': (cx, cy),
                        'last_seen': current_time
                    }
                    used_ids.add(nearest_id)
                else:
                    # Too far - must be a new person
                    self.persons[self.next_id] = {
                        'bbox': box,
                        'centroid': (cx, cy),
                        'last_seen': current_time
                    }
                    self.next_id += 1
        
        return self.persons
    
    def get_person_count(self):
        return len(self.persons)
    
    def get_nearest_person(self, detection_box):
        #Find which student is closest to a detected object
        if len(self.persons) == 0:
            return None
        
        x1, y1, x2, y2 = detection_box
        det_cx = (x1 + x2) / 2
        det_cy = (y1 + y2) / 2
        
        # Find nearest person using distance formula
        min_distance = float('inf')
        nearest_id = None
        
        for pid, data in self.persons.items():
            px, py = data['centroid']
            distance = np.sqrt((det_cx - px)**2 + (det_cy - py)**2)
            
            if distance < min_distance:
                min_distance = distance
                nearest_id = pid
        
        if min_distance < Config.MAX_ASSOCIATION_DISTANCE:
            return nearest_id
        return None

# ============================================================================
# ALERT MANAGER
# ============================================================================

class AlertManager:
    """
    Manages alert cooldowns and photo capture
    Prevents alert spam with cooldowns, photo limits, and spacing
    """
    
    def __init__(self):
        self.last_alert_time = {}
        self.alert_photo_count = {}
        self.last_photo_time = {}
        self.current_alert_id = {}
        self.active_alerts = {} #red flash animation
    
    def can_alert(self, class_name):
        #Check if cooldown period has passed
        current_time = time.time()
        if class_name not in self.last_alert_time:
            return True
        time_elapsed = current_time - self.last_alert_time[class_name]
        return time_elapsed >= Config.ALERT_COOLDOWN
    
    def can_take_photo(self, class_name):
        #Check if we can capture another photo
        current_time = time.time()
        
        # Start new alert if cooldown passed
        if self.can_alert(class_name):
            self._start_new_alert(class_name)
            return True
        
        # Check photo limit
        photo_count = self.alert_photo_count.get(class_name, 0)
        if photo_count >= Config.MAX_PHOTOS_PER_ALERT:
            return False
        
        if class_name not in self.last_photo_time:
            return True
        
        # Check photo spacing
        time_since_photo = current_time - self.last_photo_time[class_name]
        return time_since_photo >= Config.PHOTO_INTERVAL
    
    def _start_new_alert(self, class_name):
        #Initialize new alert incident
        current_time = time.time()
        self.last_alert_time[class_name] = current_time
        self.alert_photo_count[class_name] = 0
        self.last_photo_time[class_name] = 0
        alert_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_alert_id[class_name] = alert_id
        self.active_alerts[class_name] = current_time
        return alert_id
    
    def record_photo(self, class_name):
        #Record that a photo was captured
        count = self.alert_photo_count.get(class_name, 0) + 1
        self.alert_photo_count[class_name] = count
        self.last_photo_time[class_name] = time.time()
        return count
    
    def get_alert_id(self, class_name):
        #Get current alert ID for file naming
        if class_name not in self.current_alert_id:
            return self._start_new_alert(class_name)
        return self.current_alert_id[class_name]
    
    def is_alert_active(self, class_name):
        #Check if red flash should be shown
        if class_name not in self.active_alerts:
            return False
        elapsed = time.time() - self.active_alerts[class_name]
        return elapsed < Config.ALERT_FLASH_DURATION

# ============================================================================
# STUDENT ANALYZER
# ============================================================================

class StudentAnalyzer:
    """
    Tracks and analyzes student behavior with smart detection logic
    Earphones: Needs 3+ detections | Head rotation: 5s sustained | Paper passing: High confidence
    """
    
    def __init__(self, student_id):
        self.student_id = student_id
        self.detections = deque(maxlen=30) #last 30 detections
        self.earphone_history = deque(maxlen=10)  # For averaging
        self.head_rotation_start = None
        self.last_head_rotation_time = 0
        self.last_seen = time.time()
        self.risk_level = "SAFE"
        self.total_detections = 0
    
    def add_detection(self, class_name, confidence):
        #Record a new detection for this student
        self.detections.append({
            'class': class_name,
            'confidence': confidence,
            'timestamp': time.time()
        })
        
        self.total_detections += 1
        
        #Special tracking for earphones (need multiple detections)
        if class_name == "earphone":
            self.earphone_history.append(confidence)
        
        #Track head rotation duration
        if class_name == "headrotation":
            self.last_head_rotation_time = time.time()
            if self.head_rotation_start is None:
                self.head_rotation_start = time.time()
        
        self.last_seen = time.time()
    
    def reset_head_rotation(self):
        #Reset head rotation timer if head returns to normal
        current_time = time.time()
        if current_time - self.last_head_rotation_time > 2.0:
            self.head_rotation_start = None
    
    def get_avg_confidence(self):
        #Calculate average confidence of recent detections
        if not self.detections:
            return 0.0
        confidences = [d['confidence'] for d in self.detections]
        return np.mean(confidences)
    
    def get_earphone_avg(self):
        #Calculate average earphone detection confidence
        if not self.earphone_history:
            return 0.0
        return np.mean(list(self.earphone_history))
    
    def should_alert_earphone(self):
        #Check if earphone alert should trigger (needs 3+ detections)
        if len(self.earphone_history) < Config.EARPHONE_MIN_DETECTIONS:
            msg = f"Monitoring ({len(self.earphone_history)}/{Config.EARPHONE_MIN_DETECTIONS})"
            return False, msg
        
        avg_confidence = self.get_earphone_avg()
        threshold = Config.ALERT_THRESHOLD["earphone"]
        
        if avg_confidence >= threshold:
            return True, f"Earphone detected (Avg: {avg_confidence:.1%})"
        return False, f"Low confidence ({avg_confidence:.1%})"
    
    def should_alert_head_rotation(self):
        #Check if head rotation alert should trigger (needs sustained 5s)
        if self.head_rotation_start is None:
            return False, "Monitoring head position..."
        
        duration = time.time() - self.head_rotation_start
        
        if duration >= Config.HEAD_ROTATION_DURATION:
            return True, f"Head turned away for {duration:.0f}s"
        
        msg = f"Duration: {duration:.0f}s / {Config.HEAD_ROTATION_DURATION}s"
        return False, msg
    
    def should_alert_paper_passing(self, confidence):
        #Check if paper passing alert should trigger (needs high confidence)
        threshold = Config.ALERT_THRESHOLD["paperpassing"]
        
        if confidence >= threshold:
            return True, f"Paper exchange detected ({confidence:.0%})"
        return False, f"Insufficient confidence ({confidence:.0%})"
    
    def get_risk_score(self):
        #Calculate overall risk score (0-100)
        #Uses weighted average based on priority
        if not self.detections:
            return 0.0
        
        current_time = time.time()
        recent = [d for d in self.detections 
                 if current_time - d['timestamp'] < 30]
        
        weighted_sum = 0
        total_weight = 0
        
        for detection in recent:
            class_name = detection['class']
            confidence = detection['confidence']
            
            if class_name in Config.CHEATING_CLASSES:
                priority = Config.CHEATING_CLASSES[class_name]['priority']
                weight = 4 - priority #Priority 1 gets weight 3
                weighted_sum += confidence * weight
                total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        score = (weighted_sum / total_weight) * 100
        
        #Assign risk level
        if score < 25:
            self.risk_level = "SAFE"
        elif score < 50:
            self.risk_level = "LOW"
        elif score < 75:
            self.risk_level = "MEDIUM"
        else:
            self.risk_level = "HIGH"
        
        return score
    
    def get_recent_detections(self, max_items=5):
        #Get recent detections for timeline display
        current_time = time.time()
        recent = []
        
        for det in list(self.detections)[-max_items:]:
            time_ago = int(current_time - det['timestamp'])
            recent.append({
                'class': det['class'],
                'conf': det['confidence'],
                'time_ago': time_ago,
                'priority': Config.CHEATING_CLASSES[det['class']]['priority']
            })
        
        return recent
    
    def is_active(self):
        #Check if student is currently visible (seen in last 5 seconds)
        return time.time() - self.last_seen < 5.0

# ============================================================================
# UI RENDERER
# ============================================================================

class UIRenderer:
    #Handles all UI rendering operations
    
    @staticmethod
    def show_loading_screen(message):
        #Display loading screen
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        img[:] = Config.COLOR_BG_DARK
        
        cv2.putText(img, "EXAMSHIELD", (450, 300),
                   cv2.FONT_HERSHEY_SIMPLEX, 2.0, Config.COLOR_ACCENT, 3)
        cv2.putText(img, message, (500, 400),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, Config.COLOR_TEXT_SECONDARY, 2)
        
        cv2.imshow("ExamShield", img)
        cv2.waitKey(1)
    
    @staticmethod
    def draw_header(frame):
        #Draw application header
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 60), Config.COLOR_BG_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
        cv2.putText(frame, "EXAMSHIELD - AI PROCTORING", (20, 35),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, Config.COLOR_ACCENT, 3)
        return frame
    
    @staticmethod
    def draw_alert_flash(frame, alert_manager):
        #Flash red border when alert active
        h, w = frame.shape[:2]
        alert_active = False
        active_class = None
        
        for class_name in Config.CHEATING_CLASSES.keys():
            if alert_manager.is_alert_active(class_name):
                alert_active = True
                active_class = class_name
                break
        
        if alert_active:
            thickness = 15
            cv2.rectangle(frame, (0, 0), (w, h), Config.COLOR_DANGER, thickness)
            
            text = f"ALERT: {active_class.upper()} DETECTED"
            text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)[0]
            text_x = (w - text_size[0]) // 2
            
            cv2.putText(frame, text, (text_x, 100),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.2, Config.COLOR_DANGER, 3)
        
        return frame
    
    @staticmethod
    def draw_detection_timeline(frame, recent_detections):
        #Show recent detection history
        if not recent_detections:
            return frame
        
        h, w = frame.shape[:2]
        x, y = 20, 80
        max_items = min(len(recent_detections), Config.MAX_TIMELINE_ITEMS)
        
        overlay = frame.copy()
        cv2.rectangle(overlay, (x-5, y-25), (x+350, y+max_items*30+10),
                     Config.COLOR_BG_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)
        
        cv2.putText(frame, "Recent Detections:", (x, y-10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, Config.COLOR_ACCENT, 1)
        
        for i, det in enumerate(recent_detections[-max_items:]):
            y_pos = y + i * 30
            time_ago = det['time_ago']
            text = f"{det['class']}: {det['conf']:.0%} ({time_ago}s ago)"
            
            color = (Config.COLOR_DANGER if det['priority'] == 1 else
                    Config.COLOR_WARNING if det['priority'] == 2 else
                    Config.COLOR_TEXT_SECONDARY)
            
            cv2.putText(frame, text, (x, y_pos),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        
        return frame
    
    @staticmethod
    def draw_stats_panel(frame, fps, alert_count, device, student_count=0):
        #Draw statistics panel with student count
        h, w = frame.shape[:2]
        panel_x = w - 280
        
        overlay = frame.copy()
        cv2.rectangle(overlay, (panel_x, 70), (w - 10, 280),
                     Config.COLOR_BG_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)
        
        y = 95
        
        # FPS indicator
        fps_color = (Config.COLOR_SUCCESS if fps > 30 else 
                    Config.COLOR_WARNING if fps > Config.FPS_WARNING_THRESHOLD else 
                    Config.COLOR_DANGER)
        cv2.putText(frame, f"FPS: {fps:.1f}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, fps_color, 2)
        
        # Low FPS warning
        if fps < Config.FPS_WARNING_THRESHOLD:
            cv2.putText(frame, "! LOW FPS !", (panel_x + 150, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_DANGER, 1)
        
        y += 30
        cv2.putText(frame, f"Device: {device}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_ACCENT, 1)
        y += 30
        
        # Student count (multi-student support)
        student_color = (Config.COLOR_SUCCESS if student_count == 1 else
                        Config.COLOR_WARNING if student_count > 1 else
                        Config.COLOR_DANGER)
        cv2.putText(frame, f"Students: {student_count}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, student_color, 1)
        y += 30
        
        alert_color = (Config.COLOR_DANGER if alert_count > 5 else
                      Config.COLOR_WARNING if alert_count > 0 else
                      Config.COLOR_SUCCESS)
        cv2.putText(frame, f"Alerts: {alert_count}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, alert_color, 1)
        
        return frame
    
    @staticmethod
    def draw_session_stats(frame, stats):
        #Show overall session statistics
        h, w = frame.shape[:2]
        x, y = 20, h - 150
        
        overlay = frame.copy()
        cv2.rectangle(overlay, (x-5, y-25), (x+250, y+120),
                     Config.COLOR_BG_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.8, frame, 0.2, 0)
        
        cv2.putText(frame, "Session Stats:", (x, y-10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, Config.COLOR_ACCENT, 1)
        
        runtime = stats['runtime']
        stats_text = [
            f"Runtime: {runtime//60:.0f}m {runtime%60:.0f}s",
            f"Frames: {stats['frames']}",
            f"Detections: {stats['total_detections']}",
            f"Alerts: {stats['alerts']}",
            f"Avg FPS: {stats['avg_fps']:.1f}"
        ]
        
        for i, text in enumerate(stats_text):
            cv2.putText(frame, text, (x, y + i*25),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_TEXT_PRIMARY, 1)
        
        return frame
    
    @staticmethod
    def draw_controls_help(frame):
        #Show keyboard shortcuts
        h, w = frame.shape[:2]
        y = h - 30
        
        controls = "[Q]uit | [S]creenshot | [H]ide UI"
        cv2.putText(frame, controls, (10, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_TEXT_SECONDARY, 1)
        return frame
    
    @staticmethod
    def draw_person_boxes(frame, persons):
        #Draw bounding boxes around tracked persons with IDs
        # Color palette for different persons
        person_colors = [
            (255, 100, 100),  # Light blue
            (100, 255, 100),  # Light green
            (100, 100, 255),  # Light red
            (255, 255, 100),  # Cyan
            (255, 100, 255),  # Magenta
        ]
        
        for person_id, data in persons.items():
            x1, y1, x2, y2 = map(int, data['bbox'])
            color = person_colors[(person_id - 1) % len(person_colors)]
            
            # Draw thick bounding box
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
            
            # Draw person ID label
            label = f"Student #{person_id}"
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            
            # Background for label
            cv2.rectangle(frame, (x1, y1 - label_h - 15), (x1 + label_w + 10, y1), color, -1)
            
            # Label text
            cv2.putText(frame, label, (x1 + 5, y1 - 8),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        
        return frame
    
    @staticmethod
    def draw_detections(frame, boxes, names, person_associations=None):
        #Manually draw detection boxes, filtering out ignored classes
        for i, box in enumerate(boxes):
            class_id = int(box.cls)
            class_name = names[class_id]
            
            # Skip only ignored classes (by name, not ID)
            # Custom model has different class IDs than COCO
            if class_name in Config.IGNORED_CLASSES:
                continue
            
            confidence = float(box.conf)
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            
            # Draw bounding box
            color = (0, 255, 0)  # Green
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Draw label with person association if available
            label = f"{class_name} {confidence:.2f}"
            if person_associations and i < len(person_associations):
                person_id = person_associations[i]
                if person_id is not None:
                    label += f" (Student #{person_id})"
            
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)


            
            # Draw label text
            cv2.putText(frame, label, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        return frame

# ============================================================================
# MAIN APPLICATION
# ============================================================================

class ExamShield:
    """
    Main application class - orchestrates the entire proctoring system
    Components: CameraHandler, YOLO model, PersonTracker, StudentAnalyzer, AlertManager, UIRenderer
    """
    
    def __init__(self):
        #Initialize ExamShield application
        self.camera = None
        self.model = None
        self.alert_manager = AlertManager()
        self.person_tracker = PersonTracker()
        self.students = {}  # {student_id: StudentAnalyzer}
        
        # Statistics
        self.alert_count = 0
        self.total_photos = 0
        self.fps_tracker = deque(maxlen=30)
        self.start_time = None
        self.frame_count = 0
        self.ui_visible = True
        
        self._setup_directories()
        self._initialize_log()
    
    def _setup_directories(self):
        #Create necessary directories
        os.makedirs(Config.PROOF_DIR, exist_ok=True)
        log_dir = os.path.dirname(Config.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    def _initialize_log(self):
        #Initialize CSV log file
        if not os.path.exists(Config.LOG_FILE):
            with open(Config.LOG_FILE, 'w') as f:
                f.write("timestamp,student_id,class,priority,confidence,avg_confidence,"\
                       "risk_score,photo_number,description\n")
    
    def _load_model(self):
        #Load detection model
        UIRenderer.show_loading_screen("Loading AI model...")
        logging.info("Loading detection model...")
        
        try:
            self.model = YOLO(Config.DETECTION_MODEL)
            
            # Device priority: CUDA (NVIDIA) > DirectML (Intel Arc) > CPU
            if torch.cuda.is_available():
                device = '0'
                device_name = 'CUDA (NVIDIA GPU)'
                logging.info("CUDA GPU detected")
            elif DIRECTML_AVAILABLE:
                try:
                    device = torch_directml.device()
                    device_name = 'DirectML (Intel Arc GPU)'
                    logging.info("DirectML GPU detected")
                except Exception as e:
                    logging.warning(f"DirectML initialization failed: {e}, falling back to CPU")
                    device = 'cpu'
                    device_name = 'CPU'
            else:
                device = 'cpu'
                device_name = 'CPU'
                logging.info("No GPU detected, using CPU")
            
            self.model.to(device)
            logging.info(f"Model loaded successfully (Device: {device_name})")
            print(f"🚀 Acceleration: {device_name}")
            return device_name
        except Exception as e:
            logging.error(f"Failed to load model: {e}")
            raise RuntimeError(f"Failed to load model: {e}")
    
    def _should_alert(self, class_name, confidence, student):
        #Determine if alert should be triggered based on class type
        calibrated_conf = confidence * Config.CONFIDENCE_CALIBRATION.get(class_name, 1.0)
        
        if class_name == "headrotation":
            return student.should_alert_head_rotation()
        elif class_name == "paperpassing":
            return student.should_alert_paper_passing(calibrated_conf)
        else:
            # phone, earphone, smartwatch use simple threshold check
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.45)
            if calibrated_conf >= threshold:
                return True, f"{class_name}: {confidence:.0%}"
            return False, f"Low confidence ({confidence:.0%})"
    
    def _process_detection(self, class_name, confidence, frame, person_id=0):
        #Process a single detection with student association
        # Use person_id as student_id (default to 0 if no person detected)
        student_id = person_id if person_id is not None else 0
        
        if student_id not in self.students:
            self.students[student_id] = StudentAnalyzer(student_id)
        
        student = self.students[student_id]
        student.add_detection(class_name, confidence)
        student.reset_head_rotation()
        
        should_alert, reason = self._should_alert(class_name, confidence, student)
        
        # DEBUG: Enhanced earphone logging
        if class_name == "earphone":
            history_len = len(student.earphone_history)
            avg_conf = student.get_earphone_avg() if history_len > 0 else 0
            print(f"[Frame {self.frame_count}] Earphone detected: {confidence:.0%} | "
                  f"History: {history_len}/3 | Avg: {avg_conf:.0%} | "
                  f"Should Alert: {should_alert} | Reason: {reason}")
        
        # DEBUG: Phone detection logging
        if class_name == "phone":
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.45)
            print(f"[Frame {self.frame_count}] Phone detected: {confidence:.0%} | "
                  f"Threshold: {threshold:.0%} | Should Alert: {should_alert} | "
                  f"Reason: {reason}")
            if should_alert:
                can_photo = self.alert_manager.can_take_photo(class_name)
                print(f"     can_take_photo={can_photo}")
        
        # DEBUG: Smartwatch detection logging
        if class_name == "smartwatch":
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.50)
            print(f"[Frame {self.frame_count}] Smartwatch detected: {confidence:.0%} | "
                  f"Threshold: {threshold:.0%} | Should Alert: {should_alert} | "
                  f"Reason: {reason}")
            if should_alert:
                can_photo = self.alert_manager.can_take_photo(class_name)
                print(f"     can_take_photo={can_photo}")
        
        # DEBUG: Head rotation logging
        if class_name == "headrotation":
            if student.head_rotation_start:
                duration = time.time() - student.head_rotation_start
                print(f"[Frame {self.frame_count}] HeadRotation detected: {confidence:.0%} | "
                      f"Duration: {duration:.1f}s / {Config.HEAD_ROTATION_DURATION}s | "
                      f"Should Alert: {should_alert} | Reason: {reason}")
            else:
                print(f"[Frame {self.frame_count}] HeadRotation detected: {confidence:.0%} | "
                      f"Timer: Not started | Should Alert: {should_alert}")
            if should_alert:
                can_photo = self.alert_manager.can_take_photo(class_name)
                print(f"     can_take_photo={can_photo}")
        
        # DEBUG: Paper passing logging
        if class_name == "paperpassing":
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.60)
            calibrated = confidence * Config.CONFIDENCE_CALIBRATION.get(class_name, 1.0)
            print(f"[Frame {self.frame_count}] PaperPassing detected: {confidence:.0%} → "
                  f"Calibrated: {calibrated:.0%} | Threshold: {threshold:.0%} | "
                  f"Should Alert: {should_alert} | Reason: {reason}")
            if should_alert:
                can_photo = self.alert_manager.can_take_photo(class_name)
                print(f"     can_take_photo={can_photo}")
        
        if should_alert and self.alert_manager.can_take_photo(class_name):
            self._save_alert_photo(class_name, confidence, frame, student, reason)
    
    def _save_alert_photo(self, class_name, confidence, frame, student, reason):
        #Save alert photo and log entry
        alert_id = self.alert_manager.get_alert_id(class_name)
        photo_num = self.alert_manager.record_photo(class_name)
        
        if photo_num == 1:
            self.alert_count += 1
        
        self.total_photos += 1
        
        # Include student ID in filename
        student_id = student.student_id
        filename = f"Student{student_id}_{class_name}_{alert_id}_{photo_num}.jpg"
        filepath = os.path.join(Config.PROOF_DIR, filename)
        cv2.imwrite(filepath, frame)
        
        priority = Config.CHEATING_CLASSES[class_name]['priority']
        description = Config.CHEATING_CLASSES[class_name]['description']
        
        # Include student_id in CSV log
        with open(Config.LOG_FILE, 'a') as f:
            avg_conf = student.get_avg_confidence()
            risk = student.get_risk_score()
            f.write(f"{alert_id},{student_id},{class_name},{priority},{confidence:.2f},"\
                   f"{avg_conf:.2f},{risk:.0f},{photo_num},{description}\n")
        
        priority_symbol = "🔴" if priority == 1 else "🟡" if priority == 2 else "⚪"
        print(f"{priority_symbol} Alert #{self.alert_count} [Student #{student_id}]: {reason} "\
              f"(Photo {photo_num}/{Config.MAX_PHOTOS_PER_ALERT})")
        
        logging.warning(f"Alert [Student #{student_id}]: {class_name} - {reason}")
    
    def _save_screenshot(self, frame):
        #Save screenshot
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.jpg"
        filepath = os.path.join("screenshots", filename)
        os.makedirs("screenshots", exist_ok=True)
        cv2.imwrite(filepath, frame)
        print(f"📸 Screenshot saved: {filename}")
        logging.info(f"Screenshot saved: {filename}")
    
    def _generate_report(self):
        #Generate session report
        try:
            runtime = time.time() - self.start_time
            avg_fps = np.mean(self.fps_tracker) if self.fps_tracker else 0
            
            with open(Config.REPORT_FILE, 'w') as f:
                f.write("="*60 + "\n")
                f.write("EXAMSHIELD - SESSION REPORT\n")
                f.write("="*60 + "\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Duration: {runtime//60:.0f}m {runtime%60:.0f}s\n\n")
                f.write(f"Total Frames Processed: {self.frame_count}\n")
                f.write(f"Average FPS: {avg_fps:.1f}\n\n")
                f.write(f"Alert Incidents: {self.alert_count}\n")
                f.write(f"Photos Captured: {self.total_photos}\n")
                
                if self.alert_count > 0:
                    avg_photos = self.total_photos / self.alert_count
                    f.write(f"Avg Photos per Alert: {avg_photos:.1f}\n")
                
                f.write("\n" + "="*60 + "\n")
                f.write("DETECTION CLASSES\n")
                f.write("="*60 + "\n")
                
                for class_name, info in sorted(Config.CHEATING_CLASSES.items(),
                                              key=lambda x: x[1]['priority']):
                    priority = info['priority']
                    threshold = Config.ALERT_THRESHOLD[class_name]
                    f.write(f"\n{class_name}:\n")
                    f.write(f"  Priority: {priority}\n")
                    f.write(f"  Threshold: {threshold:.0%}\n")
                    f.write(f"  Description: {info['description']}\n")
                
                if self.students:
                    student = self.students[0]
                    f.write("\n" + "="*60 + "\n")
                    f.write("STUDENT ANALYSIS\n")
                    f.write("="*60 + "\n")
                    f.write(f"Total Detections: {student.total_detections}\n")
                    f.write(f"Final Risk Score: {student.get_risk_score():.1f}%\n")
                    f.write(f"Risk Level: {student.risk_level}\n")
                
                f.write("\n" + "="*60 + "\n")
                f.write("End of Report\n")
                f.write("="*60 + "\n")
            
            print(f"\n📄 Report generated: {Config.REPORT_FILE}")
            logging.info("Session report generated")
        
        except Exception as e:
            logging.error(f"Failed to generate report: {e}")
    
    def run(self):
        #Main application loop
        print("=" * 80)
        print("EXAMSHIELD - AI-POWERED EXAM PROCTORING SYSTEM")
        print("=" * 80)
        
        try:
            device = self._load_model()
            UIRenderer.show_loading_screen("Initializing camera...")
            self.camera = CameraHandler()
            
            self.start_time = time.time()
            
            print("\n" + "=" * 80)
            print("SYSTEM ACTIVE")
            print("=" * 80)
            print(f"Resolution: {Config.FRAME_WIDTH}x{Config.FRAME_HEIGHT}")
            print("\nDetection Classes (by priority):")
            
            for class_name, info in sorted(Config.CHEATING_CLASSES.items(), 
                                          key=lambda x: x[1]['priority']):
                priority = info['priority']
                symbol = "🔴" if priority == 1 else "🟡" if priority == 2 else "⚪"
                threshold = Config.ALERT_THRESHOLD[class_name]
                print(f"  {symbol} {class_name}: {info['description']} "
                      f"(threshold: {threshold:.0%})")
            
            print("\nSpecial Detection Logic:")
            print(f"  • headrotation: Must sustain for {Config.HEAD_ROTATION_DURATION}s")
            print(f"  • paperpassing: Requires {Config.ALERT_THRESHOLD['paperpassing']:.0%} confidence")
            
            print("\nKeyboard Controls:")
            print("  [Q] Quit | [S] Screenshot | [H] Hide/Show UI")
            print("=" * 80 + "\n")
            
            logging.info(f"System started - Device: {device}")
            
            while True:
                frame = self.camera.read()
                if frame is None:
                    continue
                
                self.frame_count += 1
                start_time = time.time()
                
                # Run detection
                results = self.model.predict(
                    frame,
                    imgsz=Config.IMG_SIZE,
                    verbose=False,
                    conf=Config.CONFIDENCE_THRESHOLD,
                    half=False
                )
                
                # Process all cheating detections (phones, earphones, etc.)
                boxes = results[0].boxes
                
                # DEBUG: Print what model detects (remove after debugging)
                if len(boxes) > 0 and self.frame_count % 30 == 0:  # Print every 30 frames
                    print(f"\n--- Frame {self.frame_count} Detections ---")
                    for box in boxes:
                        class_id = int(box.cls)
                        class_name = results[0].names[class_id]
                        confidence = float(box.conf)
                        print(f"  {class_name} (ID:{class_id}): {confidence:.2%}")
                
                for box in boxes:
                    class_id = int(box.cls)
                    class_name = results[0].names[class_id].lower()  # Convert to lowercase for consistency
                    confidence = float(box.conf)
                    
                    # FILTER: Skip only ignored classes (by name, not ID)
                    if class_name in Config.IGNORED_CLASSES:
                        continue
                    
                    # Process cheating detections (multiple devices supported)
                    if (class_name in Config.CHEATING_CLASSES and 
                        confidence > Config.CONFIDENCE_THRESHOLD):
                        self._process_detection(class_name, confidence, frame, person_id=0)
                
                # Draw detections (no person boxes)
                annotated = frame.copy()
                annotated = UIRenderer.draw_detections(annotated, boxes, results[0].names, person_associations=None)
                
                if self.ui_visible:
                    annotated = UIRenderer.draw_header(annotated)
                    annotated = UIRenderer.draw_alert_flash(annotated, self.alert_manager)
                    
                    active_students = {sid: s for sid, s in self.students.items() 
                                     if s.is_active()}
                    
                    # Calculate FPS
                    self.fps_tracker.append(time.time() - start_time)
                    fps = 1 / (sum(self.fps_tracker) / len(self.fps_tracker))
                    
                    annotated = UIRenderer.draw_stats_panel(
                        annotated, fps, self.alert_count, device.upper(), student_count=0
                    )
                    
                    # Session stats
                    runtime = time.time() - self.start_time
                    avg_fps = np.mean(self.fps_tracker) if self.fps_tracker else 0
                    total_detections = sum(s.total_detections for s in self.students.values())
                    
                    stats = {
                        'runtime': runtime,
                        'frames': self.frame_count,
                        'total_detections': total_detections,
                        'alerts': self.alert_count,
                        'avg_fps': avg_fps
                    }
                    annotated = UIRenderer.draw_session_stats(annotated, stats)
                    
                    if 0 in active_students:
                        recent = active_students[0].get_recent_detections()
                        annotated = UIRenderer.draw_detection_timeline(annotated, recent)
                    
                    if Config.SHOW_CONTROLS:
                        annotated = UIRenderer.draw_controls_help(annotated)
                
                cv2.imshow("ExamShield", annotated)
                
                key = cv2.waitKey(1) & 0xFF
                if key == Config.QUIT_KEY:
                    break
                elif key == Config.SCREENSHOT_KEY:
                    self._save_screenshot(annotated)
                elif key == Config.HIDE_UI_KEY:
                    self.ui_visible = not self.ui_visible
                    status = "visible" if self.ui_visible else "hidden"
                    print(f"UI {status}")
            
        except KeyboardInterrupt:
            print("\nInterrupted by user")
            logging.info("System interrupted by user")
        except Exception as e:
            print(f"\nError: {e}")
            logging.error(f"System error: {e}")
        finally:
            self._cleanup()
    
    def _cleanup(self):
        #Clean up resources
        if self.camera:
            self.camera.release()
        cv2.destroyAllWindows()
        
        # Generate report
        self._generate_report()
        
        print("\n" + "=" * 80)
        print("SESSION SUMMARY")
        print("=" * 80)
        print(f"Alert incidents: {self.alert_count}")
        print(f"Total photos: {self.total_photos}")
        if self.alert_count > 0:
            avg_photos = self.total_photos / self.alert_count
            print(f"Average photos per alert: {avg_photos:.1f}")
        
        runtime = time.time() - self.start_time if self.start_time else 0
        print(f"Total runtime: {runtime//60:.0f}m {runtime%60:.0f}s")
        print(f"Report saved: {Config.REPORT_FILE}")
        print("=" * 80)
        
        logging.info("System shutdown complete")
        
        # Keep console window open
        input("\nPress Enter to exit...")

# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    #Application entry point
    
    # Launch ESP32 Monitor GUI in separate process
    esp32_gui_path = os.path.join(os.path.dirname(__file__), "esp32_monitor_gui.py")
    esp32_process = None
    if os.path.exists(esp32_gui_path):
        try:
            esp32_process = subprocess.Popen(
                [sys.executable, esp32_gui_path],
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            print("📡 ESP32 Monitor GUI launched in separate window")
        except Exception as e:
            print(f"⚠️ Could not launch ESP32 Monitor: {e}")
    
    app = ExamShield()
    app.run()
    
    # Cleanup ESP32 GUI when main app closes
    if esp32_process:
        esp32_process.terminate()

if __name__ == "__main__":
    main()
