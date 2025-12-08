"""
ExamShield ENTERPRISE - AI-Powered Exam Proctoring System (16-Camera Edition)
Version: 2.2.2-ENTERPRISE
Author: Morshed MD Monoarul
Supports: Up to 16 independent camera feeds for large-scale exam monitoring
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
    filename='logs/examshield_enterprise.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    """System configuration for enterprise multi-camera setup"""
    # Model and file paths
    DETECTION_MODEL = "runs/detect/examshield_yolov8s/weights/best.pt"
    LOG_FILE = "logs/detection_log_enterprise.csv"
    PROOF_DIR = "proofs/alerts_enterprise"
    REPORT_FILE = "session_report_enterprise.txt"
    
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
    
    # Enterprise multi-camera settings
    MAX_CAMERAS = 16
    # Auto-detect available cameras (can specify manually: [0,1,2,3,...])
    CAMERA_INDICES = list(range(MAX_CAMERAS))
    GRID_ROWS = 4
    GRID_COLS = 4
    
    # Video settings (per camera - good quality for enterprise)
    FRAME_WIDTH = 640  # Same as Pro for quality
    FRAME_HEIGHT = 480
    TARGET_FPS = 15  # Lower FPS for resource optimization
    FPS_WARNING_THRESHOLD = 10
    
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
    MAX_TIMELINE_ITEMS = 3  # Reduced for space
    
    # Keyboard controls
    SCREENSHOT_KEY = ord('s')
    HIDE_UI_KEY = ord('h')
    QUIT_KEY = ord('q')
    GRID_VIEW_KEY = ord('g')  # Toggle grid view
    CAMERA_SELECT_KEYS = [ord(str(i)) for i in range(10)]  # 0-9 to select cameras
    
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

# ============================================================================
# ENTERPRISE CAMERA HANDLER
# ============================================================================

class EnterpriseCameraHandler:
    """Optimized camera handler for enterprise deployment"""
    
    def __init__(self, camera_index):
        self.camera_index = camera_index
        self.running = True
        self.frame_queue = queue.Queue(maxsize=1)  # Smaller queue for resource optimization
        self.active = False
        self._initialize_camera()
        if self.active:
            self._start_capture_thread()
    
    def _initialize_camera(self):
        #Try to initialize camera
        logging.info(f"Attempting Camera {self.camera_index}...")
        
        try:
            self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            
            if not self.cap.isOpened():
                logging.warning(f"Camera {self.camera_index} not available")
                self.active = False
                return
            
            # Test read
            ret, frame = self.cap.read()
            if not ret:
                logging.warning(f"Camera {self.camera_index} cannot read frames")
                self.cap.release()
                self.active = False
                return
            
            # Configure camera
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, Config.FRAME_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, Config.FRAME_HEIGHT)
            self.cap.set(cv2.CAP_PROP_FPS, Config.TARGET_FPS)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            self.active = True
            logging.info(f"Camera {self.camera_index} active: {width}x{height}")
            
        except Exception as e:
            logging.error(f"Camera {self.camera_index} error: {e}")
            self.active = False
    
    def _start_capture_thread(self):
        #Start background thread
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
    
    def _capture_loop(self):
        #Runs in background
        while self.running and self.active:
            ret, frame = self.cap.read()
            if ret:
                try:
                    self.frame_queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self.frame_queue.get_nowait()  # Remove old frame
                        self.frame_queue.put_nowait(frame)  # Add new frame
                    except:
                        pass
            else:
                time.sleep(0.1)  # Camera issue, wait before retry
    
    def read(self):
        #Get latest frame
        if not self.active:
            return None
        try:
            return self.frame_queue.get(timeout=0.1)
        except queue.Empty:
            return None
    
    def release(self):
        #Clean up
        self.running = False
        time.sleep(0.05)
        if self.cap and self.active:
            self.cap.release()
        logging.info(f"Camera {self.camera_index} released")

# Include helper classes (same as Pro version but optimized)

class AlertManager:
    """Manages alert cooldowns and photo capture"""
    
    def __init__(self):
        self.last_alert_time = {}
        self.alert_photo_count = {}
        self.last_photo_time = {}
        self.current_alert_id = {}
        self.active_alerts = {}
    
    def can_alert(self, class_name):
        current_time = time.time()
        if class_name not in self.last_alert_time:
            return True
        time_elapsed = current_time - self.last_alert_time[class_name]
        return time_elapsed >= Config.ALERT_COOLDOWN
    
    def can_take_photo(self, class_name):
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
        current_time = time.time()
        self.last_alert_time[class_name] = current_time
        self.alert_photo_count[class_name] = 0
        self.last_photo_time[class_name] = 0
        alert_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_alert_id[class_name] = alert_id
        self.active_alerts[class_name] = current_time
        return alert_id
    
    def record_photo(self, class_name):
        count = self.alert_photo_count.get(class_name, 0) + 1
        self.alert_photo_count[class_name] = count
        self.last_photo_time[class_name] = time.time()
        return count
    
    def get_alert_id(self, class_name):
        if class_name not in self.current_alert_id:
            return self._start_new_alert(class_name)
        return self.current_alert_id[class_name]
    
    def is_alert_active(self, class_name):
        if class_name not in self.active_alerts:
            return False
        elapsed = time.time() - self.active_alerts[class_name]
        return elapsed < Config.ALERT_FLASH_DURATION

class StudentAnalyzer:
    """Lightweight student analyzer for enterprise"""
    
    def __init__(self, student_id):
        self.student_id = student_id
        self.detections = deque(maxlen=20)  # Reduced for memory
        self.earphone_history = deque(maxlen=10)
        self.head_rotation_start = None
        self.last_head_rotation_time = 0
        self.last_seen = time.time()
        self.risk_level = "SAFE"
        self.total_detections = 0
    
    def add_detection(self, class_name, confidence):
        self.detections.append({
            'class': class_name,
            'confidence': confidence,
            'timestamp': time.time()
        })
        
        self.total_detections += 1
        
        if class_name == "earphone":
            self.earphone_history.append(confidence)
        
        if class_name == "headrotation":
            self.last_head_rotation_time = time.time()
            if self.head_rotation_start is None:
                self.head_rotation_start = time.time()
        
        self.last_seen = time.time()
    
    def reset_head_rotation(self):
        current_time = time.time()
        if current_time - self.last_head_rotation_time > 2.0:
            self.head_rotation_start = None
    
    def get_avg_confidence(self):
        if not self.detections:
            return 0.0
        confidences = [d['confidence'] for d in self.detections]
        return np.mean(confidences)
    
    def get_earphone_avg(self):
        if not self.earphone_history:
            return 0.0
        return np.mean(list(self.earphone_history))
    
    def should_alert_earphone(self):
        if len(self.earphone_history) < Config.EARPHONE_MIN_DETECTIONS:
            msg = f"Monitoring ({len(self.earphone_history)}/{Config.EARPHONE_MIN_DETECTIONS})"
            return False, msg
        
        avg_confidence = self.get_earphone_avg()
        threshold = Config.ALERT_THRESHOLD["earphone"]
        
        if avg_confidence >= threshold:
            return True, f"Earphone detected (Avg: {avg_confidence:.1%})"
        return False, f"Low confidence ({avg_confidence:.1%})"
    
    def should_alert_head_rotation(self):
        if self.head_rotation_start is None:
            return False, "Monitoring head position..."
        
        duration = time.time() - self.head_rotation_start
        
        if duration >= Config.HEAD_ROTATION_DURATION:
            return True, f"Head turned away for {duration:.0f}s"
        
        msg = f"Duration: {duration:.0f}s / {Config.HEAD_ROTATION_DURATION}s"
        return False, msg
    
    def should_alert_paper_passing(self, confidence):
        threshold = Config.ALERT_THRESHOLD["paperpassing"]
        
        if confidence >= threshold:
            return True, f"Paper exchange detected ({confidence:.0%})"
        return False, f"Insufficient confidence ({confidence:.0%})"
    
    def get_risk_score(self):
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
                weight = 4 - priority
                weighted_sum += confidence * weight
                total_weight += weight
        
        if total_weight == 0:
            return 0.0
        
        score = (weighted_sum / total_weight) * 100
        
        if score < 25:
            self.risk_level = "SAFE"
        elif score < 50:
            self.risk_level = "LOW"
        elif score < 75:
            self.risk_level = "MEDIUM"
        else:
            self.risk_level = "HIGH"
        
        return score
    
    def is_active(self):
        return time.time() - self.last_seen < 5.0

# ============================================================================
# MAIN APPLICATION - ENTERPRISE VERSION (16 Cameras)
# ============================================================================

class ExamShieldEnterprise:
    """
    Enterprise-grade multi-camera proctoring system
    Supports up to 16 cameras with grid display and resource optimization
    """
    
    def __init__(self):
        #Initialize ExamShield ENTERPRISE
        self.cameras = []
        self.model = None
        self.alert_managers = []
        self.students = []
        
        # Statistics
        self.alert_counts = []
        self.total_photos = []
        self.frame_counts = []
        
        # Global
        self.start_time = None
        self.ui_visible = True
        self.grid_view = True
        
        self._setup_directories()
        self._initialize_log()
    
    def _setup_directories(self):
        os.makedirs(Config.PROOF_DIR, exist_ok=True)
        log_dir = os.path.dirname(Config.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    def _initialize_log(self):
        if not os.path.exists(Config.LOG_FILE):
            with open(Config.LOG_FILE, 'w') as f:
                f.write("timestamp,camera_id,student_id,class,priority,confidence,avg_confidence,"
                       "risk_score,photo_number,description\n")
    
    def _load_model(self):
        #Load detection model
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
        alert_manager = self.alert_managers[camera_id]
        alert_id = alert_manager.get_alert_id(class_name)
        photo_num = alert_manager.record_photo(class_name)
        
        if photo_num == 1:
            self.alert_counts[camera_id] += 1
        
        self.total_photos[camera_id] += 1
        
        student_id = student.student_id
        filename = f"Cam{camera_id+1:02d}_Student{student_id}_{class_name}_{alert_id}_{photo_num}.jpg"
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
        print(f"{priority_symbol} CAM{camera_id+1:02d} Alert: {reason}")
        
        logging.warning(f"CAM{camera_id+1:02d} Alert: {class_name} - {reason}")
    
    def run(self):
        #Main enterprise application loop
        print("=" * 80)
        print("EXAMSHIELD ENTERPRISE - MULTI-CAMERA AI PROCTORING SYSTEM")
        print("=" * 80)
        
        try:
            device = self._load_model()
            
            # Initialize cameras
            print("\nScanning for cameras...")
            for cam_index in Config.CAMERA_INDICES:
                cam = EnterpriseCameraHandler(cam_index)
                if cam.active:
                    self.cameras.append(cam)
                    self.alert_managers.append(AlertManager())
                    self.students.append({})
                    self.alert_counts.append(0)
                    self.total_photos.append(0)
                    self.frame_counts.append(0)
                    print(f"✓ Camera {len(self.cameras)} (Index {cam_index}) active")
                
                if len(self.cameras) >= Config.MAX_CAMERAS:
                    break
            
            if len(self.cameras) == 0:
                raise RuntimeError("No cameras detected!")
            
            self.start_time = time.time()
            
            print("\n" + "=" * 80)
            print(f"SYSTEM ACTIVE - ENTERPRISE MODE ({len(self.cameras)} CAMERAS)")
            print("=" * 80)
            print(f"Grid Layout: {Config.GRID_ROWS}x{Config.GRID_COLS}")
            print(f"Resolution: {Config.FRAME_WIDTH}x{Config.FRAME_HEIGHT} per camera")
            print("\nKeyboard Controls:")
            print("  [Q] Quit | [S] Screenshot | [H] Hide/Show UI | [G] Toggle Grid")
            print("=" * 80 + "\n")
            
            logging.info(f"ENTERPRISE System started - {len(self.cameras)} cameras - Device: {device}")
            
            while True:
                grid_frames = []
                
                # Process each camera
                for cam_id, camera in enumerate(self.cameras):
                    frame = camera.read()
                    
                    if frame is None:
                        # Blank frame for inactive camera
                        frame = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)
                        cv2.putText(frame, f"CAM {cam_id+1:02d}", (Config.FRAME_WIDTH//2-40, Config.FRAME_HEIGHT//2),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (100, 100, 100), 2)
                        grid_frames.append(frame)
                        continue
                    
                    # CRITICAL: Resize frame to exact configured dimensions
                    # This ensures all frames match for grid layout
                    frame = cv2.resize(frame, (Config.FRAME_WIDTH, Config.FRAME_HEIGHT))
                    
                    self.frame_counts[cam_id] += 1
                    
                    # Run detection every N frames for optimization
                    if self.frame_counts[cam_id] % 2 == 0:  # Process every 2nd frame
                        try:
                            results = self.model.predict(
                                frame,
                                imgsz=Config.IMG_SIZE,
                                verbose=False,
                                conf=Config.CONFIDENCE_THRESHOLD,
                                half=False
                            )
                            
                            boxes = results[0].boxes
                            
                            # Process detections
                            for box in boxes:
                                class_id = int(box.cls)
                                class_name = results[0].names[class_id].lower()
                                confidence = float(box.conf)
                                
                                if class_name in Config.IGNORED_CLASSES:
                                    continue
                                
                                if (class_name in Config.CHEATING_CLASSES and 
                                    confidence > Config.CONFIDENCE_THRESHOLD):
                                    self._process_detection(cam_id, class_name, confidence, frame, person_id=0)
                            
                            # Draw detections (minimal for performance)
                            for box in boxes:
                                class_id = int(box.cls)
                                class_name = results[0].names[class_id]
                                
                                if class_name.lower() in Config.IGNORED_CLASSES:
                                    continue
                                
                                confidence = float(box.conf)
                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                                
                                color = (0, 255, 0) if class_name.lower() not in Config.CHEATING_CLASSES else (0, 0, 255)
                                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
                        except Exception as e:
                            logging.error(f"CAM{cam_id+1} detection error: {e}")
                    
                    # Add camera label
                    if self.ui_visible:
                        cv2.rectangle(frame, (0, 0), (100, 25), (0, 0, 0), -1)
                        cv2.putText(frame, f"CAM {cam_id+1:02d}", (5, 18),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                    
                    grid_frames.append(frame)
                
                # Create dynamic grid layout based on number of cameras
                num_cams = len(grid_frames)
                
                # Determine optimal grid size
                if num_cams <= 1:
                    grid_rows, grid_cols = 1, 1
                elif num_cams <= 4:
                    grid_rows, grid_cols = 2, 2
                elif num_cams <= 9:
                    grid_rows, grid_cols = 3, 3
                else:
                    grid_rows, grid_cols = 4, 4
                
                # Ensure all frames are exactly the same size
                resized_frames = []
                for frame in grid_frames:
                    if frame.shape[0] != Config.FRAME_HEIGHT or frame.shape[1] != Config.FRAME_WIDTH:
                        frame = cv2.resize(frame, (Config.FRAME_WIDTH, Config.FRAME_HEIGHT))
                    resized_frames.append(frame)
                
                # Build grid
                rows = []
                for r in range(grid_rows):
                    row_frames = []
                    for c in range(grid_cols):
                        idx = r * grid_cols + c
                        if idx < len(resized_frames):
                            row_frames.append(resized_frames[idx])
                        else:
                            # Empty slot with exact dimensions
                            blank = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)
                            row_frames.append(blank)
                    
                    if row_frames:
                        rows.append(np.hstack(row_frames))
                
                if rows:
                    combined = np.vstack(rows)
                else:
                    combined = np.zeros((Config.FRAME_HEIGHT, Config.FRAME_WIDTH, 3), dtype=np.uint8)
                
                cv2.imshow("ExamShield ENTERPRISE - Multi-Camera Grid", combined)
                
                key = cv2.waitKey(1) & 0xFF
                if key == Config.QUIT_KEY:
                    break
                elif key == Config.SCREENSHOT_KEY:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"screenshot_enterprise_{timestamp}.jpg"
                    os.makedirs("screenshots", exist_ok=True)
                    cv2.imwrite(f"screenshots/{filename}", combined)
                    print(f"📸 Screenshot saved: {filename}")
                elif key == Config.HIDE_UI_KEY:
                    self.ui_visible = not self.ui_visible
        
        except KeyboardInterrupt:
            print("\nInterrupted by user")
            logging.info("ENTERPRISE System interrupted by user")
        except Exception as e:
            print(f"\nError: {e}")
            logging.error(f"ENTERPRISE System error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._cleanup()
    
    def _cleanup(self):
        #Clean up resources
        for i, camera in enumerate(self.cameras):
            camera.release()
        
        cv2.destroyAllWindows()
        
        print("\n" + "=" * 80)
        print(f"SESSION SUMMARY - ENTERPRISE ({len(self.cameras)} CAMERAS)")
        print("=" * 80)
        
        total_alerts = sum(self.alert_counts)
        total_photos_all = sum(self.total_photos)
        
        for i in range(len(self.cameras)):
            print(f"Camera {i+1:02d}: {self.alert_counts[i]} alerts, {self.total_photos[i]} photos")
        
        print(f"\nTotal Alerts: {total_alerts}")
        print(f"Total Photos: {total_photos_all}")
        
        runtime = time.time() - self.start_time if self.start_time else 0
        print(f"Total runtime: {runtime//60:.0f}m {runtime%60:.0f}s")
        print(f"Report saved: {Config.REPORT_FILE}")
        print("=" * 80)
        
        logging.info("ENTERPRISE System shutdown complete")
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
    
    app = ExamShieldEnterprise()
    app.run()
    
    # Cleanup ESP32 GUI when main app closes
    if esp32_process:
        esp32_process.terminate()

if __name__ == "__main__":
    main()
