"""
ExamShield Thermal Detection Module
Handles MLX90640 thermal sensor and hotspot detection
"""

import time
import numpy as np
import cv2
import logging
import threading
from queue import Queue
import os
from datetime import datetime

try:
    import board
    import busio
    import adafruit_mlx90640
except ImportError as e:
    print(f"Warning: Adafruit MLX90640 libraries not available: {e}")
    print("Install with: pip install adafruit-circuitpython-mlx90640")

class ThermalDetection:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.mlx = None
        self.frame_queue = Queue(maxsize=10)
        self.running = False
        self.capture_thread = None

        # Thermal image parameters
        self.width = 32
        self.height = 24
        self.frame_count = 0

        # Detection parameters
        self.temp_threshold = config['thermal']['temp_threshold']
        self.hotspot_min_size = config['thermal']['hotspot_min_size']
        self.hotspot_max_size = config['thermal']['hotspot_max_size']

        # Background subtraction for better hotspot detection
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            detectShadows=False,
            varThreshold=16
        )

        # Store recent frames for analysis
        self.recent_frames = []
        self.max_recent_frames = 10

    def initialize_sensor(self):
        """Initialize MLX90640 thermal sensor"""
        try:
            # Initialize I2C
            i2c = busio.I2C(board.SCL, board.SDA, frequency=1000000)

            # Initialize MLX90640
            self.mlx = adafruit_mlx90640.MLX90640(i2c)

            # Set refresh rate
            refresh_rate = self.config['thermal']['refresh_rate']
            if refresh_rate == 1:
                self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_1_HZ
            elif refresh_rate == 2:
                self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_2_HZ
            elif refresh_rate == 4:
                self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ
            elif refresh_rate == 8:
                self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_8_HZ
            else:
                self.mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ

            self.logger.info(f"MLX90640 initialized with {refresh_rate}Hz refresh rate")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize MLX90640: {e}")
            return False

    def start(self):
        """Start thermal detection"""
        if not self.initialize_sensor():
            self.logger.error("Cannot start thermal detection - sensor initialization failed")
            return False

        self.running = True

        # Start capture thread
        self.capture_thread = threading.Thread(target=self._capture_frames)
        self.capture_thread.daemon = True
        self.capture_thread.start()

        self.logger.info("Thermal detection started")
        return True

    def _capture_frames(self):
        """Capture thermal frames continuously"""
        frame_buffer = [0] * (self.width * self.height)

        while self.running:
            try:
                # Get thermal frame
                self.mlx.getFrame(frame_buffer)

                # Convert to numpy array and reshape
                frame = np.array(frame_buffer).reshape((self.height, self.width))

                # Add timestamp
                frame_data = {
                    'frame': frame,
                    'timestamp': time.time(),
                    'frame_id': self.frame_count
                }

                # Add to queue if not full
                if not self.frame_queue.full():
                    self.frame_queue.put(frame_data)
                else:
                    # Remove oldest frame and add new one
                    try:
                        self.frame_queue.get_nowait()
                        self.frame_queue.put(frame_data)
                    except:
                        pass

                # Store for recent frames analysis
                self._update_recent_frames(frame)

                self.frame_count += 1

                # Save frame periodically if in debug mode
                if self.config['system']['debug_mode'] and self.frame_count % 50 == 0:
                    self._save_thermal_frame(frame, self.frame_count)

                # Small delay based on refresh rate
                time.sleep(1.0 / self.config['thermal']['refresh_rate'])

            except Exception as e:
                self.logger.error(f"Error capturing thermal frame: {e}")
                time.sleep(0.5)

    def _update_recent_frames(self, frame):
        """Update recent frames for background analysis"""
        self.recent_frames.append(frame.copy())

        # Keep only recent frames
        if len(self.recent_frames) > self.max_recent_frames:
            self.recent_frames.pop(0)

    def get_latest_frame(self):
        """Get the most recent thermal frame"""
        try:
            frame_data = self.frame_queue.get_nowait()
            return frame_data
        except:
            return None

    def detect_hotspots(self, frame_data=None):
        """Detect potential device hotspots in thermal image"""
        if frame_data is None:
            frame_data = self.get_latest_frame()

        if frame_data is None:
            return []

        frame = frame_data['frame']
        hotspots = []

        try:
            # Normalize frame to 8-bit for OpenCV processing
            frame_normalized = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

            # Apply Gaussian blur to reduce noise
            frame_blurred = cv2.GaussianBlur(frame_normalized, (3, 3), 0)

            # Threshold to find hot regions
            _, binary = cv2.threshold(frame_blurred, self.temp_threshold, 255, cv2.THRESH_BINARY)

            # Apply morphological operations to clean up the binary image
            kernel = np.ones((2, 2), np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

            # Find contours
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                area = cv2.contourArea(contour)

                # Filter by size (devices should be small hotspots)
                if self.hotspot_min_size <= area <= self.hotspot_max_size:
                    # Get centroid
                    M = cv2.moments(contour)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])

                        # Get average temperature in the hotspot region
                        mask = np.zeros(frame.shape, np.uint8)
                        cv2.drawContours(mask, [contour], -1, 255, -1)
                        avg_temp = cv2.mean(frame, mask=mask)[0]

                        # Calculate confidence based on temperature and size
                        temp_confidence = min((avg_temp - 25) / 15, 1.0)  # Normalize temp confidence
                        size_confidence = 1.0 - abs(area - 10) / 10  # Prefer medium-sized hotspots
                        confidence = (temp_confidence + size_confidence) / 2

                        hotspot = {
                            'position': (cx, cy),
                            'area': area,
                            'avg_temp': avg_temp,
                            'confidence': max(0.1, confidence),
                            'contour': contour,
                            'frame_id': frame_data['frame_id'],
                            'timestamp': frame_data['timestamp']
                        }
                        hotspots.append(hotspot)

            # Sort hotspots by confidence
            hotspots.sort(key=lambda x: x['confidence'], reverse=True)

            if self.config['system']['debug_mode'] and hotspots:
                self.logger.debug(f"Detected {len(hotspots)} thermal hotspots")

        except Exception as e:
            self.logger.error(f"Error detecting hotspots: {e}")

        return hotspots

    def detect_motion_hotspots(self):
        """Detect hotspots using background subtraction for motion detection"""
        frame_data = self.get_latest_frame()
        if frame_data is None:
            return []

        frame = frame_data['frame']
        hotspots = []

        try:
            # Convert to 8-bit
            frame_8bit = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

            # Apply background subtraction
            fg_mask = self.background_subtractor.apply(frame_8bit)

            # Find contours in foreground mask
            contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                area = cv2.contourArea(contour)

                if self.hotspot_min_size <= area <= self.hotspot_max_size:
                    # Get centroid
                    M = cv2.moments(contour)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])

                        # Check if this region is also hot in the thermal image
                        if cx < frame.shape[1] and cy < frame.shape[0]:
                            temp_at_point = frame[cy, cx]

                            if temp_at_point > self.temp_threshold:
                                hotspot = {
                                    'position': (cx, cy),
                                    'area': area,
                                    'avg_temp': temp_at_point,
                                    'confidence': 0.8,  # High confidence for motion + heat
                                    'detection_type': 'motion_thermal',
                                    'frame_id': frame_data['frame_id'],
                                    'timestamp': frame_data['timestamp']
                                }
                                hotspots.append(hotspot)

        except Exception as e:
            self.logger.error(f"Error in motion hotspot detection: {e}")

        return hotspots

    def get_thermal_image_for_display(self):
        """Get thermal image formatted for display"""
        frame_data = self.get_latest_frame()
        if frame_data is None:
            return None

        frame = frame_data['frame']

        try:
            # Normalize for display
            frame_normalized = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)

            # Apply colormap for better visualization
            frame_colored = cv2.applyColorMap(frame_normalized, cv2.COLORMAP_JET)

            # Resize for better display
            frame_resized = cv2.resize(frame_colored, (320, 240), interpolation=cv2.INTER_CUBIC)

            # Add hotspot overlays
            hotspots = self.detect_hotspots(frame_data)
            for hotspot in hotspots:
                pos = hotspot['position']
                # Scale position to resized image
                x = int(pos[0] * 320 / self.width)
                y = int(pos[1] * 240 / self.height)

                # Draw hotspot indicator
                cv2.circle(frame_resized, (x, y), 10, (0, 255, 0), 2)
                cv2.putText(frame_resized, f"{hotspot['avg_temp']:.1f}C", 
                           (x - 20, y - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

            return frame_resized

        except Exception as e:
            self.logger.error(f"Error preparing thermal display: {e}")
            return None

    def _save_thermal_frame(self, frame, frame_id):
        """Save thermal frame to file"""
        try:
            os.makedirs("data/thermal_images", exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"data/thermal_images/thermal_{timestamp}_{frame_id}.npy"

            # Save raw thermal data
            np.save(filename, frame)

            # Also save as image for viewing
            img_filename = filename.replace('.npy', '.png')
            frame_normalized = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            frame_colored = cv2.applyColorMap(frame_normalized, cv2.COLORMAP_JET)
            cv2.imwrite(img_filename, frame_colored)

        except Exception as e:
            self.logger.error(f"Error saving thermal frame: {e}")

    def get_statistics(self):
        """Get thermal detection statistics"""
        frame_data = self.get_latest_frame()
        if frame_data is None:
            return None

        frame = frame_data['frame']

        stats = {
            'min_temp': np.min(frame),
            'max_temp': np.max(frame),
            'avg_temp': np.mean(frame),
            'frame_count': self.frame_count,
            'hotspots_detected': len(self.detect_hotspots(frame_data))
        }

        return stats

    def stop(self):
        """Stop thermal detection"""
        self.running = False
        self.logger.info("Stopping thermal detection...")

        if self.capture_thread:
            self.capture_thread.join(timeout=2)

        self.logger.info("Thermal detection stopped")

# Test function
def test_thermal_detection():
    """Test thermal detection functionality"""
    from utils import load_config, setup_logging

    config = load_config()
    if not config:
        print("Failed to load config")
        return

    setup_logging(config['system']['log_level'])

    thermal = ThermalDetection(config)

    try:
        if thermal.start():
            print("Thermal detection started, running for 30 seconds...")

            for i in range(30):
                time.sleep(1)
                stats = thermal.get_statistics()
                if stats:
                    print(f"\rFrame: {stats['frame_count']}, "
                          f"Temp: {stats['min_temp']:.1f}-{stats['max_temp']:.1f}Â°C, "
                          f"Hotspots: {stats['hotspots_detected']}", end="")

            print("\nTest completed")
        else:
            print("Failed to start thermal detection")

    except KeyboardInterrupt:
        print("\nTest interrupted")
    finally:
        thermal.stop()

if __name__ == "__main__":
    test_thermal_detection()
