"""
ExamShield PRO - AI-Powered Exam Proctoring System (4-Camera Edition)
Version: 2.2.2-PRO
Author: Morshed MD Monoarul
Supports: 4 independent camera feeds for comprehensive monitoring
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

# Intel Arc GPU support
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
    filename='logs/examshield_pro.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """System configuration for 4-camera setup"""
    # Model and file paths
    DETECTION_MODEL = "runs/detect/examshield_yolov8s/weights/best.pt"
    LOG_FILE = "logs/detection_log_pro.csv"
    PROOF_DIR = "proofs/alerts_pro"
    REPORT_FILE = "session_report_pro.txt"
    
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
    
    # Multi-camera settings
    NUM_CAMERAS = 4
    CAMERA_INDICES = [0, 1, 2, 3]  # Camera device indices
    
    # Video settings (per camera)
    FRAME_WIDTH = 640  # Reduced for dual view
    FRAME_HEIGHT = 480
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
    SWITCH_CAMERA_KEY = ord('c')  # Switch between cameras
    
    # Detection classes
    CHEATING_CLASSES = {
        "phone": {"priority": 1, "description": "Mobile phone usage"},
        "earphone": {"priority": 1, "description": "Earphone/earbud detected"},
        "smartwatch": {"priority": 2, "description": "Smartwatch usage"},
        "headrotation": {"priority": 2, "description": "Suspicious head movement"},
        "paperpassing": {"priority": 3, "description": "Paper exchange detected"}
    }
    
    # Ignore classes
    IGNORED_CLASSES = ["hand_gestures", "handgesture", "hand_gesture"]
    
    # Multi-student tracking parameters
    PERSON_CLASS_ID = 0
    PERSON_CONFIDENCE = 0.5
    TRACKING_MAX_DISTANCE = 150
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
# MULTI-CAMERA HANDLER
# ============================================================================

class MultiCameraHandler:
    """Handles multiple camera feeds with independent threading"""
    
    def __init__(self, camera_index):
        self.camera_index = camera_index
        self.running = True
        self.frame_queue = queue.Queue(maxsize=2)
        self._initialize_camera()
        self._start_capture_thread()
    
    def _initialize_camera(self):
        #Try different backends for this camera
        logging.info(f"Initializing Camera {self.camera_index}...")
        
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        self.cap = None
        
        for backend in backends:
            self.cap = cv2.VideoCapture(self.camera_index, backend)
            if self.cap.isOpened():
                break
        
        if not self.cap or not self.cap.isOpened():
            logging.error(f"Failed to initialize Camera {self.camera_index}")
            raise RuntimeError(f"Failed to initialize Camera {self.camera_index}")
        
        # Configure camera
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, 60)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logging.info(f"Camera {self.camera_index} initialized: {width}x{height}")
    
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
                    self.frame_queue.put_nowait(frame)
                except queue.Full:
                    pass
    
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
        logging.info(f"Camera {self.camera_index} released")

# Note: PersonTracker, AlertManager, StudentAnalyzer classes remain the same
# I'll include them here for completeness

class PersonTracker:
    """Tracks multiple students using centroid matching"""
    
    def __init__(self):
        self.next_id = 1
        self.persons = {}
    
    def update(self, person_boxes):
        #Update tracking with new person detections
        current_time = time.time()
        
        self.persons = {
            pid: data for pid, data in self.persons.items()
            if current_time - data['last_seen'] < Config.TRACKING_TIMEOUT
        }
        
        if len(person_boxes) == 0:
            return self.persons
        
        new_centroids = []
        for box in person_boxes:
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            new_centroids.append((cx, cy, box))
        
        if len(self.persons) == 0:
            for cx, cy, box in new_centroids:
                self.persons[self.next_id] = {
                    'bbox': box,
                    'centroid': (cx, cy),
                    'last_seen': current_time
                }
                self.next_id += 1
        else:
            existing_ids = list(self.persons.keys())
            existing_centroids = [self.persons[pid]['centroid'] for pid in existing_ids]
            
            used_ids = set()
            
            for cx, cy, box in new_centroids:
                min_distance = float('inf')
                nearest_id = None
                
                for pid, (ex, ey) in zip(existing_ids, existing_centroids):
                    if pid in used_ids:
                        continue
                    distance = np.sqrt((cx - ex)**2 + (cy - ey)**2)
                    if distance < min_distance:
                        min_distance = distance
                        nearest_id = pid
                
                if nearest_id is not None and min_distance < Config.TRACKING_MAX_DISTANCE:
                    self.persons[nearest_id] = {
                        'bbox': box,
                        'centroid': (cx, cy),
                        'last_seen': current_time
                    }
                    used_ids.add(nearest_id)
                else:
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

class AlertManager:
    """Manages alert cooldowns and photo capture"""
    
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
        
        if self.can_alert(class_name):
            self._start_new_alert(class_name)
            return True
        
        photo_count = self.alert_photo_count.get(class_name, 0)
        if photo_count >= Config.MAX_PHOTOS_PER_ALERT:
            return False
        
        if class_name not in self.last_photo_time:
            return True
        
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

class StudentAnalyzer:
    """Tracks and analyzes student behavior with smart detection logic"""
    
    def __init__(self, student_id):
        self.student_id = student_id
        self.detections = deque(maxlen=30) #last 30 detections
        self.earphone_history = deque(maxlen=10)
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
# MAIN APPLICATION - PRO VERSION (4 Cameras)
# ============================================================================

class ExamShieldPro:
    """
    Main application class for 4-camera proctoring
    Components: 4x CameraHandler, YOLO model, PersonTracker, StudentAnalyzer, AlertManager
    """
    
    def __init__(self):
        #Initialize ExamShield PRO application
        self.cameras = []  # List of camera handlers
        self.model = None
        self.alert_managers = [AlertManager(), AlertManager(), AlertManager(), AlertManager()]  # One per camera
        self.person_trackers = [PersonTracker(), PersonTracker(), PersonTracker(), PersonTracker()]  # One per camera
        self.students = [{}, {}, {}, {}]  # Separate student tracking per camera
        
        # Statistics per camera
        self.alert_counts = [0, 0, 0, 0]
        self.total_photos = [0, 0, 0, 0]
        self.fps_trackers = [deque(maxlen=30), deque(maxlen=30), deque(maxlen=30), deque(maxlen=30)]
        self.frame_counts = [0, 0, 0, 0]
        
        # Global
        self.start_time = None
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
                f.write("timestamp,camera_id,student_id,class,priority,confidence,avg_confidence,"
                       "risk_score,photo_number,description\n")
    
    def _load_model(self):
        #Load detection model (shared across cameras)
        print("Loading AI model...")
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
        #Determine if alert should be triggered
        calibrated_conf = confidence * Config.CONFIDENCE_CALIBRATION.get(class_name, 1.0)
        
        if class_name == "headrotation":
            return student.should_alert_head_rotation()
        elif class_name == "paperpassing":
            return student.should_alert_paper_passing(calibrated_conf)
        else:
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.45)
            if calibrated_conf >= threshold:
                return True, f"{class_name}: {confidence:.0%}"
            return False, f"Low confidence ({confidence:.0%})"
    
    def _process_detection(self, camera_id, class_name, confidence, frame, person_id=0):
        #Process detection for specific camera
        student_id = person_id if person_id is not None else 0
        
        if student_id not in self.students[camera_id]:
            self.students[camera_id][student_id] = StudentAnalyzer(student_id)
        
        student = self.students[camera_id][student_id]
        student.add_detection(class_name, confidence)
        student.reset_head_rotation()
        
        should_alert, reason = self._should_alert(class_name, confidence, student)
        
        if should_alert and self.alert_managers[camera_id].can_take_photo(class_name):
            self._save_alert_photo(camera_id, class_name, confidence, frame, student, reason)
    
    def _save_alert_photo(self, camera_id, class_name, confidence, frame, student, reason):
        #Save alert photo with camera ID
        alert_manager = self.alert_managers[camera_id]
        alert_id = alert_manager.get_alert_id(class_name)
        photo_num = alert_manager.record_photo(class_name)
        
        if photo_num == 1:
            self.alert_counts[camera_id] += 1
        
        self.total_photos[camera_id] += 1
        
        student_id = student.student_id
        filename = f"Cam{camera_id+1}_Student{student_id}_{class_name}_{alert_id}_{photo_num}.jpg"
        filepath = os.path.join(Config.PROOF_DIR, filename)
        cv2.imwrite(filepath, frame)
        
        priority = Config.CHEATING_CLASSES[class_name]['priority']
        description = Config.CHEATING_CLASSES[class_name]['description']
        
        with open(Config.LOG_FILE, 'a') as f:
            avg_conf = student.get_avg_confidence()
            risk = student.get_risk_score()
            f.write(f"{alert_id},{camera_id+1},{student_id},{class_name},{priority},{confidence:.2f},"
                   f"{avg_conf:.2f},{risk:.0f},{photo_num},{description}\n")
        
        priority_symbol = "🔴" if priority == 1 else "🟡" if priority == 2 else "⚪"
        print(f"{priority_symbol} CAM{camera_id+1} Alert #{self.alert_counts[camera_id]} "
              f"[Student #{student_id}]: {reason} (Photo {photo_num}/{Config.MAX_PHOTOS_PER_ALERT})")
        
        logging.warning(f"CAM{camera_id+1} Alert [Student #{student_id}]: {class_name} - {reason}")
    
    def run(self):
        #Main application loop for dual cameras
        print("=" * 80)
        print("EXAMSHIELD PRO - 4-CAMERA AI PROCTORING SYSTEM")
        print("=" * 80)
        
        try:
            device = self._load_model()
            
            # Initialize both cameras
            print("\nInitializing cameras...")
            for i, cam_index in enumerate(Config.CAMERA_INDICES):
                try:
                    cam = MultiCameraHandler(cam_index)
                    self.cameras.append(cam)
                    print(f"✓ Camera {i+1} (Index {cam_index}) initialized")
                except Exception as e:
                    print(f"✗ Camera {i+1} (Index {cam_index}) failed: {e}")
                    if len(self.cameras) == 0:
                        raise RuntimeError("No cameras available!")
            
            self.start_time = time.time()
            
            print("\n" + "=" * 80)
            print("SYSTEM ACTIVE - 4-CAMERA MODE")
            print("=" * 80)
            print(f"Active Cameras: {len(self.cameras)}")
            print(f"Resolution: {Config.FRAME_WIDTH}x{Config.FRAME_HEIGHT} per camera")
            print("\nKeyboard Controls:")
            print("  [Q] Quit | [S] Screenshot | [H] Hide/Show UI")
            print("=" * 80 + "\n")
            
            logging.info(f"PRO System started - {len(self.cameras)} cameras - Device: {device}")
            
            while True:
                frames = []
                annotated_frames = []
                
                # Process each camera
                for cam_id, camera in enumerate(self.cameras):
                    frame = camera.read()
                    if frame is None:
                        # Create blank frame if camera fails
                        frame = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)
                        cv2.putText(frame, f"Camera {cam_id+1} Error", (50, 240),
                                   cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                    
                    frames.append(frame)
                    self.frame_counts[cam_id] += 1
                    
                    start_time = time.time()
                    
                    # Run detection on this camera's frame
                    results = self.model.predict(
                        frame,
                        imgsz=Config.IMG_SIZE,
                        verbose=False,
                        conf=Config.CONFIDENCE_THRESHOLD,
                        half=False
                    )
                    
                    boxes = results[0].boxes
                    
                    # Process detections for this camera
                    for box in boxes:
                        class_id = int(box.cls)
                        class_name = results[0].names[class_id].lower()
                        confidence = float(box.conf)
                        
                        if class_name in Config.IGNORED_CLASSES:
                            continue
                        
                        if (class_name in Config.CHEATING_CLASSES and 
                            confidence > Config.CONFIDENCE_THRESHOLD):
                            self._process_detection(cam_id, class_name, confidence, frame, person_id=0)
                    
                    # Create annotated frame
                    annotated = frame.copy()
                    
                    # Draw detections
                    for i, box in enumerate(boxes):
                        class_id = int(box.cls)
                        class_name = results[0].names[class_id]
                        
                        if  class_name.lower() in Config.IGNORED_CLASSES:
                            continue
                        
                        confidence = float(box.conf)
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        
                        color = (0, 255, 0)
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                        
                        label = f"{class_name} {confidence:.2f}"
                        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        cv2.rectangle(annotated, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
                        cv2.putText(annotated, label, (x1, y1 - 5),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
                    
                    if self.ui_visible:
                        # Add camera label
                        cv2.rectangle(annotated, (0, 0), (200, 40), (0, 0, 0), -1)
                        cv2.putText(annotated, f"CAMERA {cam_id+1}", (10, 28),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                        
                        # FPS
                        self.fps_trackers[cam_id].append(time.time() - start_time)
                        if len(self.fps_trackers[cam_id]) > 0:
                            fps = 1 / (sum(self.fps_trackers[cam_id]) / len(self.fps_trackers[cam_id]))
                            cv2.putText(annotated, f"FPS: {fps:.1f}", (10, Config.FRAME_HEIGHT - 10),
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    
                    annotated_frames.append(annotated)
                
                # Create 2x2 grid view for 4 cameras
                if len(annotated_frames) == 4:
                    # Create 2x2 grid
                    top_row = np.hstack([annotated_frames[0], annotated_frames[1]])
                    bottom_row = np.hstack([annotated_frames[2], annotated_frames[3]])
                    combined = np.vstack([top_row, bottom_row])
                elif len(annotated_frames) == 3:
                    # 3 cameras: 2 on top, 1 on bottom (centered with black padding)
                    top_row = np.hstack([annotated_frames[0], annotated_frames[1]])
                    blank = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)
                    bottom_row = np.hstack([annotated_frames[2], blank])
                    combined = np.vstack([top_row, bottom_row])
                elif len(annotated_frames) == 2:
                    # 2 cameras: side by side on top, blank on bottom
                    top_row = np.hstack([annotated_frames[0], annotated_frames[1]])
                    blank = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH * 2, 3), dtype=np.uint8)
                    combined = np.vstack([top_row, blank])
                elif len(annotated_frames) == 1:
                    # 1 camera: top-left, rest blank
                    top_row = np.hstack([annotated_frames[0], np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)])
                    blank = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH * 2, 3), dtype=np.uint8)
                    combined = np.vstack([top_row, blank])
                else:
                    # No cameras: all blank
                    combined = np.zeros((Config.FRAME_HEIGHT * 2, Config.FRAME_WIDTH * 2, 3), dtype=np.uint8)
                
                cv2.imshow("ExamShield PRO - 4-Camera Grid", combined)
                
                key = cv2.waitKey(1) & 0xFF
                if key == Config.QUIT_KEY:
                    break
                elif key == Config.SCREENSHOT_KEY:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"screenshot_pro_{timestamp}.jpg"
                    os.makedirs("screenshots", exist_ok=True)
                    cv2.imwrite(f"screenshots/{filename}", combined)
                    print(f"📸 Screenshot saved: {filename}")
                elif key == Config.HIDE_UI_KEY:
                    self.ui_visible = not self.ui_visible
        
        except KeyboardInterrupt:
            print("\nInterrupted by user")
            logging.info("PRO System interrupted by user")
        except Exception as e:
            print(f"\nError: {e}")
            logging.error(f"PRO System error: {e}")
        finally:
            self._cleanup()
    
    def _cleanup(self):
        #Clean up resources
        for i, camera in enumerate(self.cameras):
            camera.release()
            print(f"Camera {i+1} released")
        
        cv2.destroyAllWindows()
        
        print("\n" + "=" * 80)
        print("SESSION SUMMARY - PRO (4-CAMERA)")
        print("=" * 80)
        for i in range(len(self.cameras)):
            print(f"\nCamera {i+1}:")
            print(f"  Alert incidents: {self.alert_counts[i]}")
            print(f"  Total photos: {self.total_photos[i]}")
        
        runtime = time.time() - self.start_time if self.start_time else 0
        print(f"\nTotal runtime: {runtime//60:.0f}m {runtime%60:.0f}s")
        print(f"Report saved: {Config.REPORT_FILE}")
        print("=" * 80)
        
        logging.info("PRO System shutdown complete")
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
    
    app = ExamShieldPro()
    app.run()
    
    # Cleanup ESP32 GUI when main app closes
    if esp32_process:
        esp32_process.terminate()

if __name__ == "__main__":
    main()
