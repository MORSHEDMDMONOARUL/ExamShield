"""
ExamShield - Video Detection Module
"""

import cv2
import os
import time
import torch
import numpy as np
from datetime import datetime
from collections import deque

# DirectML for Intel Arc GPU support
try:
    import torch_directml
    DIRECTML_AVAILABLE = True
except ImportError:
    DIRECTML_AVAILABLE = False
from ultralytics import YOLO
import logging
from tkinter import Tk, filedialog

# ============================================================================
# LOGGING SETUP
# ============================================================================

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    filename='logs/videodetect.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============================================================================
# CONFIGURATION (Copied from main.py)
# ============================================================================

class Config:
    """System configuration parameters"""
    
    # Model paths
    DETECTION_MODEL = "runs/detect/examshield_yolov8s/weights/best.pt"
    
    # Output paths
    LOG_FILE = "logs/detection_log_video.csv" # Separate log for video
    PROOF_DIR = "proofs/video_alerts" # Separate proofs for video
    REPORT_FILE = "video_report.txt"
    
    # Detection parameters
    IMG_SIZE = 416
    CONFIDENCE_THRESHOLD = 0.30
    
    # Class-specific thresholds
    ALERT_THRESHOLD = {
        "phone": 0.45,
        "earphone": 0.30,
        "smartwatch": 0.50,
        "headrotation": 0.55,
        "paperpassing": 0.60
    }
    
    # Confidence calibration
    CONFIDENCE_CALIBRATION = {
        "phone": 1.0,
        "earphone": 1.0,
        "smartwatch": 1.0,
        "headrotation": 1.2,
        "paperpassing": 1.3
    }
    
    # Video parameters (Target for resizing)
    FRAME_WIDTH = 1280
    FRAME_HEIGHT = 720
    FPS_WARNING_THRESHOLD = 15
    
    # Alert management
    ALERT_COOLDOWN = 10
    MAX_PHOTOS_PER_ALERT = 3
    PHOTO_INTERVAL = 2
    ALERT_FLASH_DURATION = 2.0
    
    # Behavioral detection parameters
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
    
    # Ignored classes
    IGNORED_CLASSES = ["hand_gestures", "HandGesture", "hand_gesture"]
    
    # Colors
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
# ALERT MANAGER (Copied from main.py)
# ============================================================================

class AlertManager:
    """Manages alert cooldowns and photo capture"""
    
    def __init__(self):
        self.last_alert_time = {}
        self.alert_photo_count = {}
        self.last_photo_time = {}
        self.current_alert_id = {}
        self.active_alerts = {}
    
    def can_alert(self, class_name):
        """Check if enough time has passed for new alert"""
        current_time = time.time()
        if class_name not in self.last_alert_time:
            return True
        time_elapsed = current_time - self.last_alert_time[class_name]
        return time_elapsed >= Config.ALERT_COOLDOWN
    
    def can_take_photo(self, class_name):
        """Check if another photo can be captured"""
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
        """Initialize new alert incident"""
        current_time = time.time()
        self.last_alert_time[class_name] = current_time
        self.alert_photo_count[class_name] = 0
        self.last_photo_time[class_name] = 0
        alert_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_alert_id[class_name] = alert_id
        self.active_alerts[class_name] = current_time
        return alert_id
    
    def record_photo(self, class_name):
        """Record that a photo was captured"""
        count = self.alert_photo_count.get(class_name, 0) + 1
        self.alert_photo_count[class_name] = count
        self.last_photo_time[class_name] = time.time()
        return count
    
    def get_alert_id(self, class_name):
        """Get current alert ID for file naming"""
        if class_name not in self.current_alert_id:
            return self._start_new_alert(class_name)
        return self.current_alert_id[class_name]
    
    def is_alert_active(self, class_name):
        """Check if alert flash should be shown"""
        if class_name not in self.active_alerts:
            return False
        elapsed = time.time() - self.active_alerts[class_name]
        return elapsed < Config.ALERT_FLASH_DURATION

# ============================================================================
# STUDENT ANALYZER (Copied from main.py)
# ============================================================================

class StudentAnalyzer:
    """Tracks and analyzes student behavior with smart detection logic"""
    
    def __init__(self, student_id):
        self.student_id = student_id
        self.detections = deque(maxlen=30)
        self.earphone_history = deque(maxlen=10)
        self.head_rotation_start = None
        self.last_head_rotation_time = 0
        self.last_seen = time.time()
        self.risk_level = "SAFE"
        self.total_detections = 0
    
    def add_detection(self, class_name, confidence):
        """Record a new detection"""
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
        """Reset head rotation tracking when head returns to normal"""
        current_time = time.time()
        if current_time - self.last_head_rotation_time > 2.0:
            self.head_rotation_start = None
    
    def get_avg_confidence(self):
        """Calculate average detection confidence"""
        if not self.detections:
            return 0.0
        confidences = [d['confidence'] for d in self.detections]
        return np.mean(confidences)
    
    def get_earphone_avg(self):
        """Calculate average earphone detection confidence"""
        if not self.earphone_history:
            return 0.0
        return np.mean(list(self.earphone_history))
    
    def should_alert_earphone(self):
        """Determine if earphone alert should be triggered"""
        if len(self.earphone_history) < Config.EARPHONE_MIN_DETECTIONS:
            return False, f"Monitoring ({len(self.earphone_history)}/{Config.EARPHONE_MIN_DETECTIONS})"
        
        avg_confidence = self.get_earphone_avg()
        threshold = Config.ALERT_THRESHOLD["earphone"]
        
        if avg_confidence >= threshold:
            return True, f"Earphone detected (Avg: {avg_confidence:.1%})"
        return False, f"Low confidence ({avg_confidence:.1%})"
    
    def should_alert_head_rotation(self):
        """Determine if head rotation alert should be triggered (sustained turn only)"""
        if self.head_rotation_start is None:
            return False, "Monitoring head position..."
        
        duration = time.time() - self.head_rotation_start
        
        if duration >= Config.HEAD_ROTATION_DURATION:
            return True, f"Head turned away for {duration:.0f}s"
        
        return False, f"Duration: {duration:.0f}s / {Config.HEAD_ROTATION_DURATION}s"
    
    def should_alert_paper_passing(self, confidence):
        """Paper passing requires very high confidence"""
        threshold = Config.ALERT_THRESHOLD["paperpassing"]
        
        if confidence >= threshold:
            return True, f"Paper exchange detected ({confidence:.0%})"
        return False, f"Insufficient confidence ({confidence:.0%})"
    
    def get_risk_score(self):
        """Calculate overall risk score"""
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
    
    def get_recent_detections(self, max_items=5):
        """Get recent detections for timeline"""
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
        """Check if student is currently visible"""
        return time.time() - self.last_seen < 5.0

# ============================================================================
# UI RENDERER (Copied from main.py)
# ============================================================================

class UIRenderer:
    """Handles all UI rendering operations"""
    
    @staticmethod
    def show_loading_screen(message):
        """Display loading screen"""
        img = np.zeros((720, 1280, 3), dtype=np.uint8)
        img[:] = Config.COLOR_BG_DARK
        
        cv2.putText(img, "EXAMSHIELD", (450, 300),
                   cv2.FONT_HERSHEY_SIMPLEX, 2.0, Config.COLOR_ACCENT, 3)
        cv2.putText(img, message, (500, 400),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, Config.COLOR_TEXT_SECONDARY, 2)
        
        cv2.imshow("ExamShield Video", img)
        cv2.waitKey(1)
    
    @staticmethod
    def draw_header(frame):
        """Draw application header"""
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 60), Config.COLOR_BG_DARK, -1)
        frame = cv2.addWeighted(overlay, 0.7, frame, 0.3, 0)
        cv2.putText(frame, "EXAMSHIELD - VIDEO ANALYSIS", (20, 35),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, Config.COLOR_ACCENT, 3)
        return frame
    
    @staticmethod
    def draw_alert_flash(frame, alert_manager):
        """Flash red border when alert active"""
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
        """Show recent detection history"""
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
        """Draw statistics panel with student count"""
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
        cv2.putText(frame, f"Proc FPS: {fps:.1f}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, fps_color, 2)
        
        # Low FPS warning
        if fps < Config.FPS_WARNING_THRESHOLD:
            cv2.putText(frame, "! LOW FPS !", (panel_x + 150, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_DANGER, 1)
        
        y += 30
        cv2.putText(frame, f"Source: {device}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_ACCENT, 1)
        y += 30
        
        # Show detections count instead of student count for video
        cv2.putText(frame, f"Devices: {student_count}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, Config.COLOR_INFO, 1)
        y += 30
        
        alert_color = (Config.COLOR_DANGER if alert_count > 5 else
                      Config.COLOR_WARNING if alert_count > 0 else
                      Config.COLOR_SUCCESS)
        cv2.putText(frame, f"Alerts: {alert_count}", (panel_x + 15, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, alert_color, 1)
        
        return frame
    
    @staticmethod
    def draw_session_stats(frame, stats):
        """Show overall session statistics"""
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
        """Show keyboard shortcuts"""
        h, w = frame.shape[:2]
        y = h - 30
        
        controls = "[Q]uit | [S]creenshot | [H]ide UI"
        cv2.putText(frame, controls, (10, y),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, Config.COLOR_TEXT_SECONDARY, 1)
        return frame
    
    @staticmethod
    def draw_detections(frame, boxes, names):
        """Manually draw detection boxes - FIXED: Check class name not ID"""
        for box in boxes:
            class_id = int(box.cls)
            class_name = names[class_id]
            
            # Skip only ignored classes (by name, not ID)
            # Custom model has different class IDs than COCO
            if class_name in Config.IGNORED_CLASSES:
                continue
            
            confidence = float(box.conf)
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            
            # Color coding by priority
            if class_name in Config.CHEATING_CLASSES:
                priority = Config.CHEATING_CLASSES[class_name]['priority']
                color = (Config.COLOR_DANGER if priority == 1 else
                        Config.COLOR_WARNING if priority == 2 else
                        Config.COLOR_INFO)
            else:
                color = (0, 255, 0)
            
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            label = f"{class_name} {confidence:.2f}"
            (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (x1, y1 - label_h - 10), (x1 + label_w, y1), color, -1)
            
            cv2.putText(frame, label, (x1, y1 - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        
        return frame

# ============================================================================
# VIDEO DETECTOR
# ============================================================================

class VideoDetector:
    """Main application class for video processing"""
    
    def __init__(self):
        self.model = None
        self.alert_manager = AlertManager()
        self.students = {}
        self.alert_count = 0
        self.total_photos = 0
        self.fps_tracker = deque(maxlen=30)
        self.start_time = None
        self.frame_count = 0
        self.ui_visible = True
        
        self._setup_directories()
        self._initialize_log()
    
    def _setup_directories(self):
        """Create necessary directories"""
        os.makedirs(Config.PROOF_DIR, exist_ok=True)
        log_dir = os.path.dirname(Config.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    def _initialize_log(self):
        """Initialize CSV log file"""
        if not os.path.exists(Config.LOG_FILE):
            with open(Config.LOG_FILE, 'w') as f:
                f.write("timestamp,student_id,class,priority,confidence,avg_confidence,"\
                       "risk_score,photo_number,description\n")
    
    def _load_model(self):
        """Load detection model"""
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
        """Determine if alert should be triggered based on class type"""
        calibrated_conf = confidence * Config.CONFIDENCE_CALIBRATION.get(class_name, 1.0)
        
        if class_name == "earphone":
            return student.should_alert_earphone()
        elif class_name == "headrotation":
            return student.should_alert_head_rotation()
        elif class_name == "paperpassing":
            return student.should_alert_paper_passing(calibrated_conf)
        else:
            threshold = Config.ALERT_THRESHOLD.get(class_name, 0.45)
            if calibrated_conf >= threshold:
                return True, f"{class_name}: {confidence:.0%}"
            return False, f"Low confidence ({confidence:.0%})"
    
    def _process_detection(self, class_name, confidence, frame):
        """Process a single detection"""
        student_id = 0
        
        if student_id not in self.students:
            self.students[student_id] = StudentAnalyzer(student_id)
        
        student = self.students[student_id]
        student.add_detection(class_name, confidence)
        student.reset_head_rotation()
        
        should_alert, reason = self._should_alert(class_name, confidence, student)
        
        if should_alert and self.alert_manager.can_take_photo(class_name):
            self._save_alert_photo(class_name, confidence, frame, student, reason)
    
    def _save_alert_photo(self, class_name, confidence, frame, student, reason):
        """Save alert photo and log entry"""
        alert_id = self.alert_manager.get_alert_id(class_name)
        photo_num = self.alert_manager.record_photo(class_name)
        
        if photo_num == 1:
            self.alert_count += 1
        
        self.total_photos += 1
        
        filename = f"{class_name}_{alert_id}_{photo_num}.jpg"
        filepath = os.path.join(Config.PROOF_DIR, filename)
        cv2.imwrite(filepath, frame)
        
        priority = Config.CHEATING_CLASSES[class_name]['priority']
        description = Config.CHEATING_CLASSES[class_name]['description']
        
        with open(Config.LOG_FILE, 'a') as f:
            avg_conf = student.get_avg_confidence()
            risk = student.get_risk_score()
            f.write(f"{alert_id},{class_name},{priority},{confidence:.2f},"
                   f"{avg_conf:.2f},{risk:.0f},{photo_num},{description}\n")
        
        priority_symbol = "🔴" if priority == 1 else "🟡" if priority == 2 else "⚪"
        print(f"{priority_symbol} Alert #{self.alert_count}: {reason} "
              f"(Photo {photo_num}/{Config.MAX_PHOTOS_PER_ALERT})")
        
        logging.warning(f"Alert: {class_name} - {reason}")
    
    def _save_screenshot(self, frame):
        """Save screenshot"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.jpg"
        filepath = os.path.join("screenshots", filename)
        os.makedirs("screenshots", exist_ok=True)
        cv2.imwrite(filepath, frame)
        print(f"📸 Screenshot saved: {filename}")
        logging.info(f"Screenshot saved: {filename}")
    
    def _generate_report(self):
        """Generate session report"""
        try:
            runtime = time.time() - self.start_time
            avg_fps = self.frame_count / runtime if runtime > 0 else 0
            
            with open(Config.REPORT_FILE, 'w') as f:
                f.write("="*60 + "\n")
                f.write("EXAMSHIELD - VIDEO ANALYSIS REPORT\n")
                f.write("="*60 + "\n\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Duration: {runtime//60:.0f}m {runtime%60:.0f}s\n\n")
                f.write(f"Total Frames Processed: {self.frame_count}\n")
                f.write(f"Average Processing FPS: {avg_fps:.1f}\n\n")
                f.write(f"Alert Incidents: {self.alert_count}\n")
                f.write(f"Photos Captured: {self.total_photos}\n")
                
                if self.alert_count > 0:
                    avg_photos = self.total_photos / self.alert_count
                    f.write(f"Avg Photos per Alert: {avg_photos:.1f}\n")
                
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

    def select_file(self):
        """Open file dialog to select video"""
        root = Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title='Select Video File',
            filetypes=[('Video Files', '*.mp4 *.avi *.mov *.mkv'), ('All Files', '*.*')]
        )
        return file_path

    def process_video(self, video_path):
        """Main video processing loop"""
        print("=" * 80)
        print("EXAMSHIELD - VIDEO ANALYSIS MODE")
        print("=" * 80)
        
        try:
            device = self._load_model()
            
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                print("Error: Could not open video.")
                return

            # Get video properties
            orig_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            orig_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            orig_fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            print(f"\nProcessing video: {video_path}")
            print(f"Original Resolution: {orig_w}x{orig_h}, FPS: {orig_fps:.2f}, Frames: {total_frames}")
            
            # Output setup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"processed_{timestamp}.mp4"
            output_path = os.path.join("runs/detect", output_filename)
            os.makedirs("runs/detect", exist_ok=True)
            
            # Resize to Config dimensions for consistent UI
            target_w = Config.FRAME_WIDTH
            target_h = Config.FRAME_HEIGHT
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, orig_fps, (target_w, target_h))
            
            self.start_time = time.time()
            
            print("\nStarting analysis... Press 'Q' to abort.")
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Resize for consistent UI
                frame = cv2.resize(frame, (target_w, target_h))
                
                self.frame_count += 1
                loop_start = time.time()
                
                # Run detection
                results = self.model.predict(
                    frame,
                    imgsz=Config.IMG_SIZE,
                    verbose=False,
                    conf=Config.CONFIDENCE_THRESHOLD,
                    half=False
                )
                
                # Process all cheating detections (FIXED: removed person ID filter)
                boxes = results[0].boxes
                device_count = 0
                
                for box in boxes:
                    class_id = int(box.cls)
                    class_name = results[0].names[class_id]
                    confidence = float(box.conf)
                    
                    # Skip only ignored classes (by name, not ID)
                    if class_name in Config.IGNORED_CLASSES:
                        continue
                    
                    # Process cheating detections (multiple devices supported)
                    if (class_name in Config.CHEATING_CLASSES and 
                        confidence > Config.CONFIDENCE_THRESHOLD):
                        device_count += 1
                        self._process_detection(class_name, confidence, frame)
                
                # Draw UI
                annotated = frame.copy()
                annotated = UIRenderer.draw_detections(annotated, boxes, results[0].names)
                
                if self.ui_visible:
                    annotated = UIRenderer.draw_header(annotated)
                    annotated = UIRenderer.draw_alert_flash(annotated, self.alert_manager)
                    
                    active_students = {sid: s for sid, s in self.students.items() if s.is_active()}
                    
                    # FPS (Processing FPS)
                    proc_fps = 1.0 / (time.time() - loop_start + 1e-6)
                    self.fps_tracker.append(proc_fps)
                    avg_fps = np.mean(self.fps_tracker)
                    
                    annotated = UIRenderer.draw_stats_panel(
                        annotated, avg_fps, self.alert_count, "VIDEO", device_count
                    )
                    
                    # Session stats
                    runtime = time.time() - self.start_time
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
                
                # Show preview
                cv2.imshow("ExamShield Video Analysis", annotated)
                out.write(annotated)
                
                # Progress indicator
                if self.frame_count % 30 == 0:
                    progress = (self.frame_count / total_frames) * 100
                    print(f"\rProgress: {progress:.1f}% ({self.frame_count}/{total_frames})", end="")
                
                key = cv2.waitKey(1) & 0xFF
                if key == Config.QUIT_KEY:
                    print("\nAborted by user.")
                    break
                elif key == Config.SCREENSHOT_KEY:
                    self._save_screenshot(annotated)
                elif key == Config.HIDE_UI_KEY:
                    self.ui_visible = not self.ui_visible
            
            cap.release()
            out.release()
            cv2.destroyAllWindows()
            print(f"\n\nProcessing complete. Output saved to:\n{output_path}")
            self._generate_report()
            
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"\nError: {e}")
            logging.error(f"System error: {e}")

# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Application entry point"""
    detector = VideoDetector()
    video_path = detector.select_file()
    
    if video_path:
        detector.process_video(video_path)
    else:
        print("No file selected.")

if __name__ == "__main__":
    main()
