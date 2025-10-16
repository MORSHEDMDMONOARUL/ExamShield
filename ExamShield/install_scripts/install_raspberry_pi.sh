#!/bin/bash

# ExamShield Installation Script for Raspberry Pi
# This script sets up the complete ExamShield system

set -e  # Exit on any error

echo "==============================================="
echo "ExamShield Installation Script"
echo "Setting up Smart Device Detection System"
echo "==============================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Raspberry Pi
check_raspberry_pi() {
    print_info "Checking if running on Raspberry Pi..."

    if ! grep -q "Raspberry Pi" /proc/cpuinfo; then
        print_error "This script must be run on a Raspberry Pi!"
        exit 1
    fi

    print_success "Raspberry Pi detected"
}

# Update system packages
update_system() {
    print_info "Updating system packages..."

    sudo apt update
    sudo apt upgrade -y

    print_success "System packages updated"
}

# Install required system packages
install_system_packages() {
    print_info "Installing required system packages..."

    sudo apt install -y \
        python3 \
        python3-pip \
        python3-venv \
        i2c-tools \
        git \
        curl \
        build-essential \
        python3-dev \
        libjpeg-dev \
        zlib1g-dev \
        libfreetype6-dev \
        liblcms2-dev \
        libopenblas-dev \
        libatlas-base-dev \
        gfortran \
        libhdf5-dev \
        libhdf5-serial-dev \
        python3-h5py \
        pkg-config

    print_success "System packages installed"
}

# Enable I2C interface
enable_i2c() {
    print_info "Enabling I2C interface..."

    # Check if I2C is already enabled
    if grep -q "dtparam=i2c_arm=on" /boot/config.txt; then
        print_success "I2C already enabled"
    else
        # Enable I2C in config.txt
        echo "dtparam=i2c_arm=on" | sudo tee -a /boot/config.txt

        # Load I2C modules
        echo "i2c-dev" | sudo tee -a /etc/modules

        print_success "I2C enabled (reboot required)"
    fi
}

# Create project directory structure
create_directory_structure() {
    print_info "Creating project directory structure..."

    # Create main project directory
    mkdir -p /home/pi/ExamShield
    cd /home/pi/ExamShield

    # Create subdirectories
    mkdir -p raspberry_pi
    mkdir -p esp32
    mkdir -p data
    mkdir -p data/thermal_images
    mkdir -p install_scripts

    print_success "Directory structure created"
}

# Setup Python virtual environment
setup_virtual_environment() {
    print_info "Setting up Python virtual environment..."

    cd /home/pi/ExamShield

    # Create virtual environment with system site packages
    python3 -m venv --system-site-packages .venv

    # Activate virtual environment
    source .venv/bin/activate

    # Upgrade pip
    pip install --upgrade pip

    print_success "Virtual environment created"
}

# Install Python dependencies
install_python_dependencies() {
    print_info "Installing Python dependencies..."

    cd /home/pi/ExamShield
    source .venv/bin/activate

    # Install packages individually to handle potential conflicts
    pip install numpy>=1.21.0
    pip install opencv-python>=4.5.0
    pip install matplotlib>=3.3.0
    pip install pyserial>=3.5
    pip install scipy>=1.7.0

    # Install Adafruit libraries
    pip install adafruit-circuitpython-mlx90640>=1.2.0
    pip install adafruit-blinka>=6.0.0
    pip install adafruit-circuitpython-busdevice>=5.0.0
    pip install adafruit-circuitpython-register>=1.9.0

    # Install RPi.GPIO
    pip install RPi.GPIO>=0.7.0

    # PIL for image processing
    pip install Pillow

    print_success "Python dependencies installed"
}

# Test hardware connections
test_hardware() {
    print_info "Testing hardware connections..."

    # Test I2C connection
    print_info "Scanning I2C bus..."
    if command -v i2cdetect >/dev/null 2>&1; then
        i2c_output=$(sudo i2cdetect -y 1 2>/dev/null || true)
        if echo "$i2c_output" | grep -q "33"; then
            print_success "MLX90640 thermal sensor detected at address 0x33"
        else
            print_warning "MLX90640 thermal sensor not detected. Check I2C connections."
        fi
    else
        print_warning "i2cdetect not available"
    fi

    # Test USB devices (ESP32s)
    print_info "Checking for ESP32 devices..."
    usb_devices=$(ls /dev/ttyUSB* 2>/dev/null || true)
    if [ -n "$usb_devices" ]; then
        print_success "USB devices found: $usb_devices"
    else
        print_warning "No USB devices found. Connect ESP32 boards."
    fi

    # Test GPIO access
    if [ -c /dev/gpiomem ]; then
        print_success "GPIO access available"
    else
        print_warning "GPIO access may require root privileges"
    fi
}

# Configure system services
configure_services() {
    print_info "Configuring system services..."

    # Add user to required groups
    sudo usermod -a -G gpio,i2c,spi,dialout pi

    # Create udev rules for USB devices
    cat << EOF | sudo tee /etc/udev/rules.d/99-examshield.rules
# ExamShield ESP32 devices
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE="0666", GROUP="dialout"
EOF

    # Reload udev rules
    sudo udevadm control --reload-rules
    sudo udevadm trigger

    print_success "System services configured"
}

# Create desktop shortcut
create_desktop_shortcut() {
    print_info "Creating desktop shortcut..."

    cat << EOF > /home/pi/Desktop/ExamShield.desktop
[Desktop Entry]
Name=ExamShield
Comment=Smart Device Detection System
Icon=/home/pi/ExamShield/icon.png
Exec=lxterminal -e "cd /home/pi/ExamShield && source .venv/bin/activate && python main.py"
Type=Application
Encoding=UTF-8
Terminal=false
Categories=Application;
EOF

    chmod +x /home/pi/Desktop/ExamShield.desktop

    print_success "Desktop shortcut created"
}

# Create startup script
create_startup_script() {
    print_info "Creating startup script..."

    cat << 'EOF' > /home/pi/ExamShield/start_examshield.sh
#!/bin/bash
# ExamShield startup script

cd /home/pi/ExamShield
source .venv/bin/activate

# Wait for USB devices to be ready
sleep 5

# Start ExamShield system
python main.py --no-gui
EOF

    chmod +x /home/pi/ExamShield/start_examshield.sh

    print_success "Startup script created"
}

# Main installation function
main() {
    echo
    print_info "Starting ExamShield installation..."
    echo

    check_raspberry_pi
    update_system
    install_system_packages
    enable_i2c
    create_directory_structure
    setup_virtual_environment
    install_python_dependencies
    configure_services
    test_hardware
    create_desktop_shortcut
    create_startup_script

    echo
    print_success "ExamShield installation completed successfully!"
    echo
    print_warning "IMPORTANT: Please reboot your Raspberry Pi to ensure all changes take effect."
    print_info "After reboot, you can:"
    print_info "  1. Run 'cd /home/pi/ExamShield && source .venv/bin/activate && python main.py' to start the system"
    print_info "  2. Use the desktop shortcut 'ExamShield'"
    print_info "  3. Upload the ESP32 firmware using Arduino IDE"
    echo
    print_info "For troubleshooting and configuration, see README.md"
    echo

    read -p "Would you like to reboot now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Rebooting system..."
        sudo reboot
    else
        print_info "Please remember to reboot later: sudo reboot"
    fi
}

# Run main function
main "$@"
