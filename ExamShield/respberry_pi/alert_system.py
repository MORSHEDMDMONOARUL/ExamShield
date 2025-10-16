"""
ExamShield Alert System Module
Controls laser pointer, buzzer, LED, and servo motors for alerts
"""

import RPi.GPIO as GPIO
import time
import threading
import logging
import math
from queue import Queue

class AlertSystem:
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)

        # GPIO pins from config
        self.servo_pin_x = config['alert']['servo_pin_x']
        self.servo_pin_y = config['alert']['servo_pin_y']
        self.laser_pin = config['alert']['laser_pin']
        self.buzzer_pin = config['alert']['buzzer_pin']
        self.led_pin = config['alert']['led_pin']

        # Alert state
        self.alert_active = False
        self.current_target = None
        self.alert_thread = None
        self.running = False

        # Servo control
        self.servo_x = None
        self.servo_y = None
        self.servo_frequency = 50  # 50Hz for standard servos

        # Alert queue for multiple simultaneous alerts
        self.alert_queue = Queue()

        # Servo position limits and calibration
        self.servo_min_duty = 2.5   # 0 degrees
        self.servo_max_duty = 12.5  # 180 degrees
        self.servo_center_duty = 7.5 # 90 degrees

        # Current servo positions
        self.current_x_angle = 90
        self.current_y_angle = 90

    def initialize(self):
        """Initialize GPIO pins and PWM"""
        try:
            # Setup GPIO mode
            GPIO.setmode(GPIO.BOARD)

            # Setup output pins
            GPIO.setup(self.servo_pin_x, GPIO.OUT)
            GPIO.setup(self.servo_pin_y, GPIO.OUT)
            GPIO.setup(self.laser_pin, GPIO.OUT)
            GPIO.setup(self.buzzer_pin, GPIO.OUT)
            GPIO.setup(self.led_pin, GPIO.OUT)

            # Initialize servo PWM
            self.servo_x = GPIO.PWM(self.servo_pin_x, self.servo_frequency)
            self.servo_y = GPIO.PWM(self.servo_pin_y, self.servo_frequency)

            # Start PWM with center position
            self.servo_x.start(self.servo_center_duty)
            self.servo_y.start(self.servo_center_duty)

            # Initialize all outputs to OFF
            GPIO.output(self.laser_pin, GPIO.LOW)
            GPIO.output(self.buzzer_pin, GPIO.LOW)
            GPIO.output(self.led_pin, GPIO.LOW)

            # Small delay for servo initialization
            time.sleep(1)

            self.logger.info("Alert system initialized")
            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize alert system: {e}")
            return False

    def start(self):
        """Start alert system"""
        if not self.initialize():
            return False

        self.running = True

        # Start alert processing thread
        self.alert_thread = threading.Thread(target=self._process_alerts)
        self.alert_thread.daemon = True
        self.alert_thread.start()

        self.logger.info("Alert system started")
        return True

    def _process_alerts(self):
        """Process alert queue continuously"""
        while self.running:
            try:
                if not self.alert_queue.empty():
                    alert_data = self.alert_queue.get()
                    self._execute_alert(alert_data)

                time.sleep(0.1)

            except Exception as e:
                self.logger.error(f"Error processing alerts: {e}")

    def trigger_alert(self, target_position, alert_type="device_detected", duration=None):
        """Queue an alert for processing"""
        if duration is None:
            duration = self.config['alert']['alert_duration']

        alert_data = {
            'target_position': target_position,
            'alert_type': alert_type,
            'duration': duration,
            'timestamp': time.time()
        }

        self.alert_queue.put(alert_data)
        self.logger.info(f"Alert queued: {alert_type} at position {target_position}")

    def _execute_alert(self, alert_data):
        """Execute a single alert"""
        target_pos = alert_data['target_position']
        alert_type = alert_data['alert_type']
        duration = alert_data['duration']

        try:
            self.alert_active = True
            self.current_target = target_pos

            # Point laser at target
            if target_pos:
                self.point_laser_at_position(target_pos)

            # Activate visual and audio alerts based on type
            if alert_type == "device_detected":
                self._device_detected_alert(duration)
            elif alert_type == "high_confidence":
                self._high_confidence_alert(duration)
            elif alert_type == "test_alert":
                self._test_alert(duration)

            self.alert_active = False
            self.current_target = None

        except Exception as e:
            self.logger.error(f"Error executing alert: {e}")
            self.alert_active = False

    def _device_detected_alert(self, duration):
        """Standard device detection alert"""
        end_time = time.time() + duration

        while time.time() < end_time and self.running:
            # Turn on laser and LED
            GPIO.output(self.laser_pin, GPIO.HIGH)
            GPIO.output(self.led_pin, GPIO.HIGH)

            # Brief buzzer beep
            GPIO.output(self.buzzer_pin, GPIO.HIGH)
            time.sleep(0.2)
            GPIO.output(self.buzzer_pin, GPIO.LOW)

            # Keep laser and LED on for visibility
            time.sleep(1.8)  # Total 2 seconds per cycle

            # Brief off period
            GPIO.output(self.laser_pin, GPIO.LOW)
            GPIO.output(self.led_pin, GPIO.LOW)
            time.sleep(0.5)

    def _high_confidence_alert(self, duration):
        """High confidence detection alert (more intense)"""
        end_time = time.time() + duration

        while time.time() < end_time and self.running:
            # Rapid flashing laser and LED with continuous buzzer
            for _ in range(5):  # 5 rapid flashes
                GPIO.output(self.laser_pin, GPIO.HIGH)
                GPIO.output(self.led_pin, GPIO.HIGH)
                GPIO.output(self.buzzer_pin, GPIO.HIGH)
                time.sleep(0.1)

                GPIO.output(self.laser_pin, GPIO.LOW)
                GPIO.output(self.led_pin, GPIO.LOW)
                GPIO.output(self.buzzer_pin, GPIO.LOW)
                time.sleep(0.1)

            # Longer pause
            time.sleep(1)

    def _test_alert(self, duration):
        """Test alert pattern"""
        # Simple on/off pattern for testing
        GPIO.output(self.laser_pin, GPIO.HIGH)
        GPIO.output(self.led_pin, GPIO.HIGH)
        GPIO.output(self.buzzer_pin, GPIO.HIGH)

        time.sleep(duration)

        GPIO.output(self.laser_pin, GPIO.LOW)
        GPIO.output(self.led_pin, GPIO.LOW)
        GPIO.output(self.buzzer_pin, GPIO.LOW)

    def point_laser_at_position(self, position, image_width=32, image_height=24):
        """Point laser at specified position using servo control"""
        try:
            x, y = position

            # Convert image coordinates to servo angles
            # Map thermal sensor coordinates (32x24) to servo range (0-180 degrees)
            angle_x = int((x / image_width) * 180)
            angle_y = int((y / image_height) * 180)

            # Clamp angles to valid range
            angle_x = max(0, min(angle_x, 180))
            angle_y = max(0, min(angle_y, 180))

            # Move servos to target position
            self.move_servo(angle_x, angle_y)

            self.logger.debug(f"Laser pointed to position ({x}, {y}) -> angles ({angle_x}, {angle_y})")

        except Exception as e:
            self.logger.error(f"Error pointing laser: {e}")

    def move_servo(self, x_angle, y_angle):
        """Move servos to specified angles"""
        try:
            # Convert angles to duty cycles
            x_duty = self._angle_to_duty_cycle(x_angle)
            y_duty = self._angle_to_duty_cycle(y_angle)

            # Smooth movement if large angle change
            if abs(x_angle - self.current_x_angle) > 30 or abs(y_angle - self.current_y_angle) > 30:
                self._smooth_servo_move(x_angle, y_angle)
            else:
                # Direct movement for small changes
                self.servo_x.ChangeDutyCycle(x_duty)
                self.servo_y.ChangeDutyCycle(y_duty)
                time.sleep(0.1)  # Allow servo to reach position

            self.current_x_angle = x_angle
            self.current_y_angle = y_angle

        except Exception as e:
            self.logger.error(f"Error moving servo: {e}")

    def _smooth_servo_move(self, target_x, target_y):
        """Smooth servo movement for large angle changes"""
        steps = 10  # Number of intermediate steps

        start_x = self.current_x_angle
        start_y = self.current_y_angle

        for i in range(steps + 1):
            progress = i / steps

            # Linear interpolation
            current_x = start_x + (target_x - start_x) * progress
            current_y = start_y + (target_y - start_y) * progress

            x_duty = self._angle_to_duty_cycle(current_x)
            y_duty = self._angle_to_duty_cycle(current_y)

            self.servo_x.ChangeDutyCycle(x_duty)
            self.servo_y.ChangeDutyCycle(y_duty)

            time.sleep(0.05)  # Small delay for smooth movement

    def _angle_to_duty_cycle(self, angle):
        """Convert servo angle (0-180) to PWM duty cycle"""
        # Linear mapping from angle to duty cycle
        duty_cycle = self.servo_min_duty + (angle / 180.0) * (self.servo_max_duty - self.servo_min_duty)
        return duty_cycle

    def center_servos(self):
        """Move servos to center position"""
        self.move_servo(90, 90)
        self.logger.info("Servos centered")

    def test_servos(self):
        """Test servo movement through full range"""
        self.logger.info("Testing servo movement...")

        # Test X-axis servo
        for angle in [0, 45, 90, 135, 180, 90]:
            self.move_servo(angle, 90)
            time.sleep(1)

        # Test Y-axis servo
        for angle in [0, 45, 90, 135, 180, 90]:
            self.move_servo(90, angle)
            time.sleep(1)

        self.logger.info("Servo test completed")

    def test_laser(self, duration=2):
        """Test laser on/off"""
        self.logger.info("Testing laser...")
        GPIO.output(self.laser_pin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(self.laser_pin, GPIO.LOW)
        self.logger.info("Laser test completed")

    def test_buzzer(self, duration=1):
        """Test buzzer"""
        self.logger.info("Testing buzzer...")
        GPIO.output(self.buzzer_pin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(self.buzzer_pin, GPIO.LOW)
        self.logger.info("Buzzer test completed")

    def test_led(self, duration=2):
        """Test LED"""
        self.logger.info("Testing LED...")
        GPIO.output(self.led_pin, GPIO.HIGH)
        time.sleep(duration)
        GPIO.output(self.led_pin, GPIO.LOW)
        self.logger.info("LED test completed")

    def emergency_stop(self):
        """Emergency stop - turn off all alerts immediately"""
        try:
            GPIO.output(self.laser_pin, GPIO.LOW)
            GPIO.output(self.buzzer_pin, GPIO.LOW)
            GPIO.output(self.led_pin, GPIO.LOW)

            # Clear alert queue
            while not self.alert_queue.empty():
                try:
                    self.alert_queue.get_nowait()
                except:
                    break

            self.alert_active = False
            self.current_target = None

            self.logger.info("Emergency stop activated")

        except Exception as e:
            self.logger.error(f"Error in emergency stop: {e}")

    def get_status(self):
        """Get current alert system status"""
        return {
            'alert_active': self.alert_active,
            'current_target': self.current_target,
            'current_x_angle': self.current_x_angle,
            'current_y_angle': self.current_y_angle,
            'queue_size': self.alert_queue.qsize()
        }

    def stop(self):
        """Stop alert system and cleanup"""
        self.running = False
        self.logger.info("Stopping alert system...")

        # Turn off all outputs
        try:
            GPIO.output(self.laser_pin, GPIO.LOW)
            GPIO.output(self.buzzer_pin, GPIO.LOW)
            GPIO.output(self.led_pin, GPIO.LOW)
        except:
            pass

        # Stop PWM
        try:
            if self.servo_x:
                self.servo_x.stop()
            if self.servo_y:
                self.servo_y.stop()
        except:
            pass

        # Wait for thread to finish
        if self.alert_thread:
            self.alert_thread.join(timeout=2)

        # Cleanup GPIO
        try:
            GPIO.cleanup()
        except:
            pass

        self.logger.info("Alert system stopped")

# Test function
def test_alert_system():
    """Test alert system functionality"""
    from utils import load_config, setup_logging

    config = load_config()
    if not config:
        print("Failed to load config")
        return

    setup_logging(config['system']['log_level'])

    alert_system = AlertSystem(config)

    try:
        if alert_system.start():
            print("Alert system started")

            # Test individual components
            print("Testing servos...")
            alert_system.test_servos()

            print("Testing laser...")
            alert_system.test_laser()

            print("Testing buzzer...")
            alert_system.test_buzzer()

            print("Testing LED...")
            alert_system.test_led()

            # Test alert at specific position
            print("Testing alert at position (16, 12)...")
            alert_system.trigger_alert((16, 12), "test_alert", 3)
            time.sleep(4)

            print("Test completed")
        else:
            print("Failed to start alert system")

    except KeyboardInterrupt:
        print("\nTest interrupted")
    finally:
        alert_system.stop()

if __name__ == "__main__":
    test_alert_system()
