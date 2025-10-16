"""
ExamShield Main Control System
Coordinates all modules and provides central control
"""

import time
import threading
import signal
import sys
import logging
from datetime import datetime

# Import our modules
from utils import load_config, setup_logging, correlate_rf_thermal, log_detection
from rf_receiver import RFReceiver
from thermal_detection import ThermalDetection
from alert_system import AlertSystem
from gui_dashboard import ExamShieldDashboard

class ExamShieldSystem:
    def __init__(self, config_path="config.json"):
        # Load configuration
        self.config = load_config(config_path)
        if not self.config:
            print("ERROR: Failed to load configuration!")
            sys.exit(1)

        # Setup logging
        self.logger = setup_logging(
            self.config['system']['log_level'],
            "data/detections.log"
        )

        self.logger.info("ExamShield System Initializing...")

        # Initialize modules
        self.rf_receiver = RFReceiver(self.config)
        self.thermal_detection = ThermalDetection(self.config)
        self.alert_system = AlertSystem(self.config)

        # System state
        self.running = False
        self.detection_thread = None
        self.gui_thread = None

        # Detection parameters
        self.correlation_threshold = self.config['detection']['correlation_distance_threshold']
        self.confidence_threshold = self.config['detection']['confidence_threshold']
        self.min_detection_time = self.config['detection']['min_detection_time']

        # Active detections tracking
        self.active_detections = {}

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.stop()
        sys.exit(0)

    def start(self, with_gui=True):
        """Start the ExamShield system"""
        try:
            self.logger.info("Starting ExamShield System...")

            # Start RF receiver
            if not self.rf_receiver.start():
                self.logger.error("Failed to start RF receiver")
                return False

            # Start thermal detection
            if not self.thermal_detection.start():
                self.logger.error("Failed to start thermal detection")
                return False

            # Start alert system
            if not self.alert_system.start():
                self.logger.error("Failed to start alert system")
                return False

            # Start detection correlation thread
            self.running = True
            self.detection_thread = threading.Thread(target=self._detection_loop)
            self.detection_thread.daemon = True
            self.detection_thread.start()

            self.logger.info("All modules started successfully")

            # Start GUI if requested
            if with_gui:
                self.start_gui()
            else:
                # Run in console mode
                self.console_mode()

            return True

        except Exception as e:
            self.logger.error(f"Failed to start system: {e}")
            return False

    def start_gui(self):
        """Start GUI dashboard in separate thread"""
        def run_gui():
            try:
                dashboard = ExamShieldDashboard(
                    self.config,
                    self.rf_receiver,
                    self.thermal_detection,
                    self.alert_system
                )
                dashboard.start()
            except Exception as e:
                self.logger.error(f"GUI error: {e}")

        self.gui_thread = threading.Thread(target=run_gui)
        self.gui_thread.daemon = True
        self.gui_thread.start()

        # Keep main thread alive while GUI is running
        try:
            while self.running and self.gui_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt received")
        finally:
            self.stop()

    def console_mode(self):
        """Run system in console mode without GUI"""
        self.logger.info("Running in console mode. Press Ctrl+C to stop.")

        try:
            while self.running:
                # Print status every 10 seconds
                self.print_status()
                time.sleep(10)

        except KeyboardInterrupt:
            self.logger.info("Console mode interrupted")
        finally:
            self.stop()

    def print_status(self):
        """Print current system status to console"""
        try:
            # RF status
            rf_devices = self.rf_receiver.get_detected_devices()
            rf_positions = self.rf_receiver.get_estimated_positions()

            # Thermal status
            thermal_stats = self.thermal_detection.get_statistics()
            hotspots = self.thermal_detection.detect_hotspots()

            # Alert status
            alert_status = self.alert_system.get_status()

            print(f"\n=== ExamShield Status - {datetime.now().strftime('%H:%M:%S')} ===")
            print(f"RF Devices: {len(rf_devices)} detected, {len(rf_positions)} positioned")

            if thermal_stats:
                print(f"Thermal: {thermal_stats['min_temp']:.1f}-{thermal_stats['max_temp']:.1f}Â°C, "
                      f"{len(hotspots)} hotspots")

            print(f"Alerts: {'ACTIVE' if alert_status['alert_active'] else 'Inactive'}")
            print(f"Active Detections: {len(self.active_detections)}")

        except Exception as e:
            self.logger.error(f"Error printing status: {e}")

    def _detection_loop(self):
        """Main detection correlation loop"""
        self.logger.info("Detection loop started")

        while self.running:
            try:
                self.process_detections()
                time.sleep(1)  # Check every second

            except Exception as e:
                self.logger.error(f"Error in detection loop: {e}")
                time.sleep(1)

    def process_detections(self):
        """Process and correlate RF and thermal detections"""
        try:
            # Get current RF positions
            rf_positions = self.rf_receiver.get_estimated_positions()

            # Get current thermal hotspots
            thermal_hotspots = self.thermal_detection.detect_hotspots()

            if not rf_positions and not thermal_hotspots:
                return

            # Extract position data for correlation
            rf_pos_list = [pos_data['position'] for pos_data in rf_positions]

            # Correlate RF and thermal detections
            correlations = correlate_rf_thermal(
                rf_pos_list,
                thermal_hotspots,
                self.correlation_threshold
            )

            # Process correlations
            for correlation in correlations:
                self.handle_correlation(correlation, rf_positions, thermal_hotspots)

            # Handle RF-only detections (devices in airplane mode or hidden)
            self.handle_rf_only_detections(rf_positions, correlations)

            # Handle thermal-only detections (devices without RF signature)
            self.handle_thermal_only_detections(thermal_hotspots, correlations)

            # Clean up old detections
            self.cleanup_old_detections()

        except Exception as e:
            self.logger.error(f"Error processing detections: {e}")

    def handle_correlation(self, correlation, rf_positions, thermal_hotspots):
        """Handle correlated RF+thermal detection"""
        rf_pos = correlation['rf_position']
        thermal_pos = correlation['thermal_position']
        confidence = correlation['confidence']

        # Find the corresponding RF device
        rf_device = None
        for pos_data in rf_positions:
            if pos_data['position'] == rf_pos:
                rf_device = pos_data
                break

        if rf_device and confidence >= self.confidence_threshold:
            device_id = rf_device['mac_address']

            # Update or create detection record
            if device_id not in self.active_detections:
                self.active_detections[device_id] = {
                    'first_detected': time.time(),
                    'last_updated': time.time(),
                    'positions': [],
                    'detection_type': 'rf_thermal_correlation',
                    'confidence_scores': [],
                    'alert_triggered': False
                }

            detection = self.active_detections[device_id]
            detection['last_updated'] = time.time()
            detection['positions'].append(thermal_pos)  # Use thermal position (more accurate)
            detection['confidence_scores'].append(confidence)

            # Keep only recent positions
            cutoff_time = time.time() - 30  # Last 30 seconds
            detection['positions'] = [
                pos for i, pos in enumerate(detection['positions'])
                if detection['last_updated'] - (len(detection['positions']) - i) <= 30
            ]
            detection['confidence_scores'] = detection['confidence_scores'][-len(detection['positions']):]

            # Check if detection qualifies for alert
            if self.should_trigger_alert(detection):
                self.trigger_device_alert(device_id, detection)

    def handle_rf_only_detections(self, rf_positions, correlations):
        """Handle RF detections without thermal correlation"""
        correlated_rf_positions = [corr['rf_position'] for corr in correlations]

        for pos_data in rf_positions:
            if pos_data['position'] not in correlated_rf_positions:
                device_id = pos_data['mac_address']
                position = pos_data['position']
                confidence = pos_data['confidence'] * 0.7  # Lower confidence for RF-only

                if confidence >= self.confidence_threshold:
                    if device_id not in self.active_detections:
                        self.active_detections[device_id] = {
                            'first_detected': time.time(),
                            'last_updated': time.time(),
                            'positions': [],
                            'detection_type': 'rf_only',
                            'confidence_scores': [],
                            'alert_triggered': False
                        }

                    detection = self.active_detections[device_id]
                    detection['last_updated'] = time.time()
                    detection['positions'].append(position)
                    detection['confidence_scores'].append(confidence)

                    if self.should_trigger_alert(detection):
                        self.trigger_device_alert(device_id, detection)

    def handle_thermal_only_detections(self, thermal_hotspots, correlations):
        """Handle thermal detections without RF correlation"""
        correlated_thermal_positions = [corr['thermal_position'] for corr in correlations]

        for hotspot in thermal_hotspots:
            if hotspot['position'] not in correlated_thermal_positions:
                # Create pseudo device ID based on position
                device_id = f"thermal_{hotspot['position'][0]}_{hotspot['position'][1]}"
                position = hotspot['position']
                confidence = hotspot['confidence'] * 0.6  # Lower confidence for thermal-only

                if confidence >= self.confidence_threshold:
                    if device_id not in self.active_detections:
                        self.active_detections[device_id] = {
                            'first_detected': time.time(),
                            'last_updated': time.time(),
                            'positions': [],
                            'detection_type': 'thermal_only',
                            'confidence_scores': [],
                            'alert_triggered': False
                        }

                    detection = self.active_detections[device_id]
                    detection['last_updated'] = time.time()
                    detection['positions'].append(position)
                    detection['confidence_scores'].append(confidence)

                    if self.should_trigger_alert(detection):
                        self.trigger_device_alert(device_id, detection)

    def should_trigger_alert(self, detection):
        """Determine if detection should trigger an alert"""
        # Check if already alerted
        if detection['alert_triggered']:
            return False

        # Check minimum detection time
        detection_duration = time.time() - detection['first_detected']
        if detection_duration < self.min_detection_time:
            return False

        # Check confidence consistency
        if len(detection['confidence_scores']) < 3:
            return False

        avg_confidence = sum(detection['confidence_scores'][-3:]) / 3
        return avg_confidence >= self.confidence_threshold

    def trigger_device_alert(self, device_id, detection):
        """Trigger alert for detected device"""
        try:
            # Get most recent position
            if not detection['positions']:
                return

            latest_position = detection['positions'][-1]
            avg_confidence = sum(detection['confidence_scores'][-3:]) / 3

            # Determine alert type based on confidence
            alert_type = "high_confidence" if avg_confidence > 0.8 else "device_detected"

            # Trigger alert
            self.alert_system.trigger_alert(
                latest_position,
                alert_type,
                self.config['alert']['alert_duration']
            )

            # Mark as alerted
            detection['alert_triggered'] = True

            # Log the detection
            log_detection(
                device_id,
                latest_position,
                detection['detection_type'],
                avg_confidence
            )

            self.logger.info(
                f"ALERT: Device {device_id} detected at {latest_position} "
                f"(confidence: {avg_confidence:.2f}, type: {detection['detection_type']})"
            )

        except Exception as e:
            self.logger.error(f"Error triggering alert: {e}")

    def cleanup_old_detections(self):
        """Remove old detection records"""
        current_time = time.time()
        timeout = 30  # Remove detections older than 30 seconds

        expired_detections = [
            device_id for device_id, detection in self.active_detections.items()
            if current_time - detection['last_updated'] > timeout
        ]

        for device_id in expired_detections:
            del self.active_detections[device_id]

    def stop(self):
        """Stop the ExamShield system"""
        self.logger.info("Stopping ExamShield System...")
        self.running = False

        # Stop modules
        try:
            self.rf_receiver.stop()
        except:
            pass

        try:
            self.thermal_detection.stop()
        except:
            pass

        try:
            self.alert_system.stop()
        except:
            pass

        # Wait for threads
        if self.detection_thread:
            self.detection_thread.join(timeout=2)

        self.logger.info("ExamShield System stopped")

    def get_system_status(self):
        """Get comprehensive system status"""
        try:
            rf_devices = self.rf_receiver.get_detected_devices()
            rf_positions = self.rf_receiver.get_estimated_positions()
            thermal_stats = self.thermal_detection.get_statistics()
            hotspots = self.thermal_detection.detect_hotspots()
            alert_status = self.alert_system.get_status()

            return {
                'running': self.running,
                'rf_devices_count': len(rf_devices),
                'rf_positioned_count': len(rf_positions),
                'thermal_stats': thermal_stats,
                'hotspots_count': len(hotspots),
                'alert_active': alert_status['alert_active'],
                'active_detections_count': len(self.active_detections),
                'uptime': time.time() - (thermal_stats['frame_count'] / 4 if thermal_stats else 0)
            }
        except Exception as e:
            self.logger.error(f"Error getting system status: {e}")
            return {'error': str(e)}

def main():
    """Main function to run ExamShield system"""
    import argparse

    parser = argparse.ArgumentParser(description='ExamShield - Smart Device Detection System')
    parser.add_argument('--config', default='config.json', help='Configuration file path')
    parser.add_argument('--no-gui', action='store_true', help='Run without GUI dashboard')
    parser.add_argument('--test-mode', action='store_true', help='Run in test mode (simulated data)')

    args = parser.parse_args()

    if args.test_mode:
        print("Test mode not implemented yet")
        return

    # Create and start system
    system = ExamShieldSystem(args.config)

    try:
        if system.start(with_gui=not args.no_gui):
            print("ExamShield system started successfully")
        else:
            print("Failed to start ExamShield system")
            sys.exit(1)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
