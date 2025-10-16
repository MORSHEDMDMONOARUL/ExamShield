#!/usr/bin/env python3
"""
ExamShield Hardware Test Script
Tests all hardware components to ensure proper operation
"""

import sys
import time
import logging
from utils import load_config, setup_logging

def test_thermal_sensor():
    """Test MLX90640 thermal sensor"""
    print("\n=== Testing Thermal Sensor (MLX90640) ===")

    try:
        import board
        import busio
        import adafruit_mlx90640

        # Initialize I2C
        i2c = busio.I2C(board.SCL, board.SDA, frequency=1000000)

        # Initialize MLX90640
        mlx = adafruit_mlx90640.MLX90640(i2c)
        mlx.refresh_rate = adafruit_mlx90640.RefreshRate.REFRESH_4_HZ

        print("âœ“ MLX90640 sensor initialized successfully")

        # Test frame capture
        frame = [0] * 768  # 32x24 = 768 pixels
        mlx.getFrame(frame)

        min_temp = min(frame)
        max_temp = max(frame)
        avg_temp = sum(frame) / len(frame)

        print(f"âœ“ Frame captured successfully")
        print(f"  Temperature range: {min_temp:.1f}Â°C - {max_temp:.1f}Â°C")
        print(f"  Average temperature: {avg_temp:.1f}Â°C")

        return True

    except ImportError as e:
        print(f"âœ— Import error: {e}")
        print("  Install with: pip install adafruit-circuitpython-mlx90640")
        return False
    except Exception as e:
        print(f"âœ— Thermal sensor test failed: {e}")
        print("  Check I2C connections and run 'sudo i2cdetect -y 1'")
        return False

def test_i2c_connection():
    """Test I2C connection and detect devices"""
    print("\n=== Testing I2C Connection ===")

    try:
        import subprocess
        result = subprocess.run(['sudo', 'i2cdetect', '-y', '1'], 
                              capture_output=True, text=True)

        if result.returncode == 0:
            output = result.stdout
            print("âœ“ I2C bus scan successful")
            print("I2C devices detected:")
            print(output)

            # Check for MLX90640 at address 0x33
            if "33" in output:
                print("âœ“ MLX90640 thermal sensor detected at address 0x33")
                return True
            else:
                print("âœ— MLX90640 thermal sensor not found at address 0x33")
                return False
        else:
            print(f"âœ— I2C scan failed: {result.stderr}")
            return False

    except FileNotFoundError:
        print("âœ— i2cdetect command not found")
        print("  Install with: sudo apt install i2c-tools")
        return False
    except Exception as e:
        print(f"âœ— I2C test failed: {e}")
        return False

def test_gpio_access():
    """Test GPIO access and pins"""
    print("\n=== Testing GPIO Access ===")

    try:
        import RPi.GPIO as GPIO

        # Test GPIO setup
        GPIO.setmode(GPIO.BOARD)

        # Test pins used by alert system
        test_pins = [11, 13, 15, 16, 18]  # Servo X, Servo Y, Laser, Buzzer, LED

        for pin in test_pins:
            try:
                GPIO.setup(pin, GPIO.OUT)
                GPIO.output(pin, GPIO.LOW)
                print(f"âœ“ GPIO pin {pin} accessible")
            except Exception as e:
                print(f"âœ— GPIO pin {pin} failed: {e}")
                return False

        GPIO.cleanup()
        print("âœ“ GPIO access test successful")
        return True

    except ImportError:
        print("âœ— RPi.GPIO not available")
        print("  Install with: pip install RPi.GPIO")
        return False
    except Exception as e:
        print(f"âœ— GPIO test failed: {e}")
        print("  Try running with sudo or add user to gpio group")
        return False

def test_servos():
    """Test servo motor control"""
    print("\n=== Testing Servo Motors ===")

    try:
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BOARD)

        # Servo pins from config
        servo_pin_x = 11
        servo_pin_y = 13

        GPIO.setup(servo_pin_x, GPIO.OUT)
        GPIO.setup(servo_pin_y, GPIO.OUT)

        # Create PWM instances
        servo_x = GPIO.PWM(servo_pin_x, 50)  # 50Hz
        servo_y = GPIO.PWM(servo_pin_y, 50)

        servo_x.start(7.5)  # Center position
        servo_y.start(7.5)

        print("âœ“ Servos initialized at center position")

        # Test movement
        print("  Testing servo movement...")
        positions = [2.5, 7.5, 12.5, 7.5]  # 0Â°, 90Â°, 180Â°, 90Â°

        for i, duty in enumerate(positions):
            servo_x.ChangeDutyCycle(duty)
            servo_y.ChangeDutyCycle(duty)
            print(f"    Position {i+1}/4 ({duty} duty cycle)")
            time.sleep(1)

        servo_x.stop()
        servo_y.stop()
        GPIO.cleanup()

        print("âœ“ Servo test completed successfully")
        return True

    except Exception as e:
        print(f"âœ— Servo test failed: {e}")
        return False

def test_laser_buzzer_led():
    """Test laser, buzzer, and LED"""
    print("\n=== Testing Laser, Buzzer, and LED ===")

    try:
        import RPi.GPIO as GPIO

        GPIO.setmode(GPIO.BOARD)

        # Pins from config
        laser_pin = 15
        buzzer_pin = 16
        led_pin = 18

        GPIO.setup(laser_pin, GPIO.OUT)
        GPIO.setup(buzzer_pin, GPIO.OUT)
        GPIO.setup(led_pin, GPIO.OUT)

        # Test each component
        components = [
            (laser_pin, "Laser"),
            (buzzer_pin, "Buzzer"), 
            (led_pin, "LED")
        ]

        for pin, name in components:
            print(f"  Testing {name}...")
            GPIO.output(pin, GPIO.HIGH)
            time.sleep(1)
            GPIO.output(pin, GPIO.LOW)
            print(f"âœ“ {name} test completed")
            time.sleep(0.5)

        GPIO.cleanup()
        print("âœ“ All alert components tested successfully")
        return True

    except Exception as e:
        print(f"âœ— Alert components test failed: {e}")
        return False

def test_usb_devices():
    """Test USB serial connections for ESP32s"""
    print("\n=== Testing USB Serial Connections ===")

    try:
        import os
        import serial

        # Look for USB devices
        usb_devices = []
        for device in os.listdir('/dev/'):
            if device.startswith('ttyUSB') or device.startswith('ttyACM'):
                usb_devices.append(f'/dev/{device}')

        if not usb_devices:
            print("âœ— No USB serial devices found")
            print("  Connect ESP32 boards via USB")
            return False

        print(f"âœ“ Found {len(usb_devices)} USB device(s): {usb_devices}")

        # Test each device
        working_devices = []
        for device in usb_devices:
            try:
                ser = serial.Serial(device, 115200, timeout=1)
                ser.close()
                working_devices.append(device)
                print(f"âœ“ {device} accessible")
            except Exception as e:
                print(f"âœ— {device} failed: {e}")

        if len(working_devices) >= 4:
            print(f"âœ“ All 4 required ESP32 connections available")
            return True
        else:
            print(f"âš  Only {len(working_devices)}/4 ESP32 connections available")
            print("  Connect all 4 ESP32 boards for full functionality")
            return len(working_devices) > 0

    except Exception as e:
        print(f"âœ— USB test failed: {e}")
        return False

def test_python_dependencies():
    """Test Python module imports"""
    print("\n=== Testing Python Dependencies ===")

    required_modules = [
        ('numpy', 'Numerical computing'),
        ('cv2', 'Computer vision (opencv-python)'),
        ('matplotlib', 'Plotting and visualization'),
        ('serial', 'Serial communication (pyserial)'),
        ('scipy', 'Scientific computing'),
        ('RPi.GPIO', 'Raspberry Pi GPIO control'),
        ('PIL', 'Image processing (Pillow)'),
        ('tkinter', 'GUI framework (usually built-in)')
    ]

    failed_imports = []

    for module_name, description in required_modules:
        try:
            __import__(module_name)
            print(f"âœ“ {module_name} - {description}")
        except ImportError:
            print(f"âœ— {module_name} - {description} (MISSING)")
            failed_imports.append(module_name)

    # Test Adafruit libraries separately
    try:
        import adafruit_mlx90640
        print("âœ“ adafruit_mlx90640 - Thermal sensor library")
    except ImportError:
        print("âœ— adafruit_mlx90640 - Thermal sensor library (MISSING)")
        failed_imports.append('adafruit_mlx90640')

    if failed_imports:
        print(f"\nâš  {len(failed_imports)} missing dependencies")
        print("Install missing packages in virtual environment:")
        print("  source .venv/bin/activate")
        print("  pip install -r requirements.txt")
        return False
    else:
        print("\nâœ“ All Python dependencies available")
        return True

def run_comprehensive_test():
    """Run all hardware tests"""
    print("ExamShield Hardware Test Suite")
    print("=" * 50)

    test_results = {
        'Python Dependencies': test_python_dependencies(),
        'I2C Connection': test_i2c_connection(),
        'GPIO Access': test_gpio_access(),
        'Thermal Sensor': test_thermal_sensor(),
        'Servo Motors': test_servos(),
        'Alert Components': test_laser_buzzer_led(),
        'USB Serial': test_usb_devices()
    }

    print("\n" + "=" * 50)
    print("TEST RESULTS SUMMARY")
    print("=" * 50)

    passed = 0
    total = len(test_results)

    for test_name, result in test_results.items():
        status = "PASS" if result else "FAIL"
        symbol = "âœ“" if result else "âœ—"
        print(f"{symbol} {test_name}: {status}")
        if result:
            passed += 1

    print(f"\nOverall: {passed}/{total} tests passed")

    if passed == total:
        print("\nðŸŽ‰ All tests passed! ExamShield hardware is ready.")
        return True
    else:
        print(f"\nâš  {total - passed} test(s) failed. Check hardware connections and dependencies.")
        return False

def main():
    """Main test function"""
    if len(sys.argv) > 1:
        test_name = sys.argv[1].lower()

        if test_name == 'thermal':
            test_thermal_sensor()
        elif test_name == 'i2c':
            test_i2c_connection()
        elif test_name == 'gpio':
            test_gpio_access()
        elif test_name == 'servo':
            test_servos()
        elif test_name == 'alert':
            test_laser_buzzer_led()
        elif test_name == 'usb':
            test_usb_devices()
        elif test_name == 'python':
            test_python_dependencies()
        else:
            print(f"Unknown test: {test_name}")
            print("Available tests: thermal, i2c, gpio, servo, alert, usb, python")
    else:
        # Run comprehensive test
        success = run_comprehensive_test()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
