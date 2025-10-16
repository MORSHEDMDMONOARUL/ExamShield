"""
ExamShield GUI Dashboard
Real-time monitoring interface for the detection system
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import cv2
import numpy as np
from PIL import Image, ImageTk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import logging

class ExamShieldDashboard:
    def __init__(self, config, rf_receiver=None, thermal_detection=None, alert_system=None):
        self.config = config
        self.rf_receiver = rf_receiver
        self.thermal_detection = thermal_detection
        self.alert_system = alert_system
        self.logger = logging.getLogger(__name__)

        # GUI state
        self.running = False
        self.update_thread = None

        # Create main window
        self.root = tk.Tk()
        self.root.title("ExamShield - Smart Device Detection System")
        self.root.geometry("1200x800")
        self.root.configure(bg='#2c3e50')

        # Variables for display
        self.detected_devices = tk.StringVar(value="0")
        self.active_alerts = tk.StringVar(value="0")
        self.system_status = tk.StringVar(value="Initializing...")
        self.thermal_temp_range = tk.StringVar(value="--")

        # Setup GUI components
        self.setup_gui()

        # Bind close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_gui(self):
        """Setup GUI layout and components"""
        # Main frame
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Title
        title_label = tk.Label(main_frame, text="ExamShield Dashboard", 
                             font=('Arial', 24, 'bold'), 
                             bg='#2c3e50', fg='#ecf0f1')
        title_label.pack(pady=(0, 20))

        # Status bar
        self.create_status_bar(main_frame)

        # Create notebook for tabs
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill='both', expand=True, pady=(20, 0))

        # Overview tab
        self.create_overview_tab(notebook)

        # Thermal view tab
        self.create_thermal_tab(notebook)

        # RF Detection tab
        self.create_rf_tab(notebook)

        # System Control tab
        self.create_control_tab(notebook)

    def create_status_bar(self, parent):
        """Create status information bar"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill='x', pady=(0, 10))

        # System status
        ttk.Label(status_frame, text="System Status:", font=('Arial', 12, 'bold')).grid(row=0, column=0, sticky='w')
        status_label = ttk.Label(status_frame, textvariable=self.system_status, font=('Arial', 12))
        status_label.grid(row=0, column=1, sticky='w', padx=(10, 20))

        # Detected devices
        ttk.Label(status_frame, text="Detected Devices:", font=('Arial', 12, 'bold')).grid(row=0, column=2, sticky='w')
        devices_label = ttk.Label(status_frame, textvariable=self.detected_devices, font=('Arial', 12))
        devices_label.grid(row=0, column=3, sticky='w', padx=(10, 20))

        # Active alerts
        ttk.Label(status_frame, text="Active Alerts:", font=('Arial', 12, 'bold')).grid(row=0, column=4, sticky='w')
        alerts_label = ttk.Label(status_frame, textvariable=self.active_alerts, font=('Arial', 12))
        alerts_label.grid(row=0, column=5, sticky='w', padx=(10, 0))

    def create_overview_tab(self, notebook):
        """Create overview tab with real-time information"""
        overview_frame = ttk.Frame(notebook)
        notebook.add(overview_frame, text="Overview")

        # Left panel - Detection map
        left_frame = ttk.LabelFrame(overview_frame, text="Detection Map", padding=10)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))

        # Canvas for detection map
        self.map_canvas = tk.Canvas(left_frame, bg='white', width=400, height=300)
        self.map_canvas.pack(fill='both', expand=True)

        # Right panel - Statistics and logs
        right_frame = ttk.Frame(overview_frame)
        right_frame.pack(side='right', fill='both', expand=True, padx=(5, 0))

        # Statistics frame
        stats_frame = ttk.LabelFrame(right_frame, text="System Statistics", padding=10)
        stats_frame.pack(fill='x', pady=(0, 5))

        self.stats_text = tk.Text(stats_frame, height=8, state='disabled')
        stats_scrollbar = ttk.Scrollbar(stats_frame, orient='vertical', command=self.stats_text.yview)
        self.stats_text.configure(yscrollcommand=stats_scrollbar.set)
        self.stats_text.pack(side='left', fill='both', expand=True)
        stats_scrollbar.pack(side='right', fill='y')

        # Recent detections frame
        detections_frame = ttk.LabelFrame(right_frame, text="Recent Detections", padding=10)
        detections_frame.pack(fill='both', expand=True, pady=(5, 0))

        # Treeview for detections
        columns = ('Time', 'Type', 'Position', 'Confidence')
        self.detections_tree = ttk.Treeview(detections_frame, columns=columns, show='headings', height=10)

        for col in columns:
            self.detections_tree.heading(col, text=col)
            self.detections_tree.column(col, width=100)

        detections_scrollbar = ttk.Scrollbar(detections_frame, orient='vertical', command=self.detections_tree.yview)
        self.detections_tree.configure(yscrollcommand=detections_scrollbar.set)

        self.detections_tree.pack(side='left', fill='both', expand=True)
        detections_scrollbar.pack(side='right', fill='y')

    def create_thermal_tab(self, notebook):
        """Create thermal imaging tab"""
        thermal_frame = ttk.Frame(notebook)
        notebook.add(thermal_frame, text="Thermal View")

        # Thermal image display
        image_frame = ttk.LabelFrame(thermal_frame, text="Thermal Camera Feed", padding=10)
        image_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))

        self.thermal_label = tk.Label(image_frame, text="Thermal feed will appear here", bg='black', fg='white')
        self.thermal_label.pack(fill='both', expand=True)

        # Thermal controls and info
        control_frame = ttk.Frame(thermal_frame)
        control_frame.pack(side='right', fill='y', padx=(5, 0))

        # Temperature info
        temp_frame = ttk.LabelFrame(control_frame, text="Temperature Info", padding=10)
        temp_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(temp_frame, text="Range:").pack(anchor='w')
        ttk.Label(temp_frame, textvariable=self.thermal_temp_range).pack(anchor='w')

        # Hotspot detection controls
        hotspot_frame = ttk.LabelFrame(control_frame, text="Detection Settings", padding=10)
        hotspot_frame.pack(fill='x', pady=(0, 10))

        ttk.Label(hotspot_frame, text="Temperature Threshold:").pack(anchor='w')
        self.temp_threshold_var = tk.DoubleVar(value=self.config['thermal']['temp_threshold'])
        temp_scale = ttk.Scale(hotspot_frame, from_=20, to=40, orient='horizontal', 
                              variable=self.temp_threshold_var, command=self.update_temp_threshold)
        temp_scale.pack(fill='x')

        self.temp_threshold_label = ttk.Label(hotspot_frame, text=f"{self.temp_threshold_var.get():.1f}Â°C")
        self.temp_threshold_label.pack(anchor='w')

        # Hotspot list
        hotspot_list_frame = ttk.LabelFrame(control_frame, text="Detected Hotspots", padding=10)
        hotspot_list_frame.pack(fill='both', expand=True)

        self.hotspot_listbox = tk.Listbox(hotspot_list_frame)
        self.hotspot_listbox.pack(fill='both', expand=True)

    def create_rf_tab(self, notebook):
        """Create RF detection tab"""
        rf_frame = ttk.Frame(notebook)
        notebook.add(rf_frame, text="RF Detection")

        # Device list frame
        devices_frame = ttk.LabelFrame(rf_frame, text="Detected Devices", padding=10)
        devices_frame.pack(side='left', fill='both', expand=True, padx=(0, 5))

        # Treeview for RF devices
        rf_columns = ('MAC Address', 'Type', 'RSSI', 'Last Seen', 'Position')
        self.rf_devices_tree = ttk.Treeview(devices_frame, columns=rf_columns, show='headings')

        for col in rf_columns:
            self.rf_devices_tree.heading(col, text=col)
            self.rf_devices_tree.column(col, width=120)

        rf_scrollbar = ttk.Scrollbar(devices_frame, orient='vertical', command=self.rf_devices_tree.yview)
        self.rf_devices_tree.configure(yscrollcommand=rf_scrollbar.set)

        self.rf_devices_tree.pack(side='left', fill='both', expand=True)
        rf_scrollbar.pack(side='right', fill='y')

        # ESP32 status frame
        esp32_frame = ttk.LabelFrame(rf_frame, text="ESP32 Scanner Status", padding=10)
        esp32_frame.pack(side='right', fill='y', padx=(5, 0))

        self.esp32_status_text = tk.Text(esp32_frame, width=30, height=15, state='disabled')
        esp32_status_text_scroll = ttk.Scrollbar(esp32_frame, orient='vertical', command=self.esp32_status_text.yview)
        self.esp32_status_text.configure(yscrollcommand=esp32_status_text_scroll.set)

        self.esp32_status_text.pack(side='left', fill='both', expand=True)
        esp32_status_text_scroll.pack(side='right', fill='y')

    def create_control_tab(self, notebook):
        """Create system control tab"""
        control_frame = ttk.Frame(notebook)
        notebook.add(control_frame, text="System Control")

        # Alert system controls
        alert_frame = ttk.LabelFrame(control_frame, text="Alert System Control", padding=20)
        alert_frame.pack(fill='x', pady=(0, 20))

        alert_buttons_frame = ttk.Frame(alert_frame)
        alert_buttons_frame.pack()

        ttk.Button(alert_buttons_frame, text="Test Laser", command=self.test_laser).pack(side='left', padx=5)
        ttk.Button(alert_buttons_frame, text="Test Buzzer", command=self.test_buzzer).pack(side='left', padx=5)
        ttk.Button(alert_buttons_frame, text="Test LED", command=self.test_led).pack(side='left', padx=5)
        ttk.Button(alert_buttons_frame, text="Center Servos", command=self.center_servos).pack(side='left', padx=5)
        ttk.Button(alert_buttons_frame, text="Emergency Stop", command=self.emergency_stop).pack(side='left', padx=5)

        # System controls
        system_frame = ttk.LabelFrame(control_frame, text="System Control", padding=20)
        system_frame.pack(fill='x', pady=(0, 20))

        system_buttons_frame = ttk.Frame(system_frame)
        system_buttons_frame.pack()

        self.start_stop_button = ttk.Button(system_buttons_frame, text="Stop System", command=self.toggle_system)
        self.start_stop_button.pack(side='left', padx=5)

        ttk.Button(system_buttons_frame, text="Save Config", command=self.save_config).pack(side='left', padx=5)
        ttk.Button(system_buttons_frame, text="Export Logs", command=self.export_logs).pack(side='left', padx=5)

        # Manual alert test
        manual_frame = ttk.LabelFrame(control_frame, text="Manual Alert Test", padding=20)
        manual_frame.pack(fill='x')

        ttk.Label(manual_frame, text="Test Position (X, Y):").pack(anchor='w')

        pos_frame = ttk.Frame(manual_frame)
        pos_frame.pack(fill='x', pady=5)

        ttk.Label(pos_frame, text="X:").pack(side='left')
        self.test_x_var = tk.IntVar(value=16)
        ttk.Entry(pos_frame, textvariable=self.test_x_var, width=5).pack(side='left', padx=(5, 10))

        ttk.Label(pos_frame, text="Y:").pack(side='left')
        self.test_y_var = tk.IntVar(value=12)
        ttk.Entry(pos_frame, textvariable=self.test_y_var, width=5).pack(side='left', padx=(5, 10))

        ttk.Button(pos_frame, text="Trigger Test Alert", command=self.trigger_test_alert).pack(side='left', padx=10)

    def start(self):
        """Start the dashboard"""
        self.running = True
        self.system_status.set("Running")

        # Start update thread
        self.update_thread = threading.Thread(target=self._update_loop)
        self.update_thread.daemon = True
        self.update_thread.start()

        # Start GUI main loop
        self.root.mainloop()

    def _update_loop(self):
        """Main update loop for dashboard data"""
        while self.running:
            try:
                self.update_overview_data()
                self.update_thermal_display()
                self.update_rf_data()
                time.sleep(1)  # Update every second
            except Exception as e:
                self.logger.error(f"Error in dashboard update: {e}")
                time.sleep(1)

    def update_overview_data(self):
        """Update overview tab data"""
        try:
            # Update device count
            if self.rf_receiver:
                active_devices = self.rf_receiver.get_detected_devices()
                self.detected_devices.set(str(len(active_devices)))

            # Update alert count
            if self.alert_system:
                status = self.alert_system.get_status()
                alert_count = 1 if status['alert_active'] else 0
                self.active_alerts.set(str(alert_count))

            # Update statistics
            self.update_statistics()

            # Update detection map
            self.update_detection_map()

        except Exception as e:
            self.logger.error(f"Error updating overview data: {e}")

    def update_statistics(self):
        """Update system statistics text"""
        try:
            stats_text = ""

            # Thermal statistics
            if self.thermal_detection:
                thermal_stats = self.thermal_detection.get_statistics()
                if thermal_stats:
                    stats_text += f"Thermal Frames: {thermal_stats['frame_count']}\n"
                    stats_text += f"Temperature: {thermal_stats['min_temp']:.1f} - {thermal_stats['max_temp']:.1f}Â°C\n"
                    stats_text += f"Avg Temperature: {thermal_stats['avg_temp']:.1f}Â°C\n"
                    stats_text += f"Hotspots: {thermal_stats['hotspots_detected']}\n"

                    self.thermal_temp_range.set(f"{thermal_stats['min_temp']:.1f} - {thermal_stats['max_temp']:.1f}Â°C")

            # RF statistics
            if self.rf_receiver:
                active_devices = self.rf_receiver.get_detected_devices()
                stats_text += f"\nActive RF Devices: {len(active_devices)}\n"

                for mac, device in active_devices.items():
                    time_since = time.time() - device['last_seen']
                    stats_text += f"  {mac[:8]}... ({time_since:.0f}s ago)\n"

            # Update text widget
            self.stats_text.config(state='normal')
            self.stats_text.delete(1.0, tk.END)
            self.stats_text.insert(tk.END, stats_text)
            self.stats_text.config(state='disabled')

        except Exception as e:
            self.logger.error(f"Error updating statistics: {e}")

    def update_detection_map(self):
        """Update the detection map visualization"""
        try:
            self.map_canvas.delete("all")

            # Draw room outline
            self.map_canvas.create_rectangle(50, 50, 350, 250, outline='black', width=2)

            # Draw ESP32 positions
            esp32_positions = [(75, 75), (325, 75), (75, 225), (325, 225)]
            for i, (x, y) in enumerate(esp32_positions):
                self.map_canvas.create_oval(x-10, y-10, x+10, y+10, fill='blue', outline='darkblue')
                self.map_canvas.create_text(x, y-20, text=f"ESP32-{i+1}", font=('Arial', 8))

            # Draw detected device positions
            if self.rf_receiver:
                positions = self.rf_receiver.get_estimated_positions()
                for pos_data in positions:
                    x, y = pos_data['position']
                    # Scale to canvas coordinates
                    canvas_x = 50 + (x / 100) * 300
                    canvas_y = 50 + (y / 100) * 200

                    confidence = pos_data['confidence']
                    color = 'red' if confidence > 0.7 else 'orange' if confidence > 0.4 else 'yellow'

                    self.map_canvas.create_oval(canvas_x-8, canvas_y-8, canvas_x+8, canvas_y+8, 
                                              fill=color, outline='darkred')
                    self.map_canvas.create_text(canvas_x, canvas_y-15, 
                                              text=f"{confidence:.2f}", font=('Arial', 7))

        except Exception as e:
            self.logger.error(f"Error updating detection map: {e}")

    def update_thermal_display(self):
        """Update thermal imaging display"""
        try:
            if self.thermal_detection:
                thermal_image = self.thermal_detection.get_thermal_image_for_display()

                if thermal_image is not None:
                    # Convert OpenCV image to PIL format
                    image_rgb = cv2.cvtColor(thermal_image, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(image_rgb)

                    # Resize for display
                    pil_image = pil_image.resize((400, 300), Image.Resampling.LANCZOS)

                    # Convert to PhotoImage
                    photo = ImageTk.PhotoImage(pil_image)

                    # Update label
                    self.thermal_label.configure(image=photo)
                    self.thermal_label.image = photo  # Keep a reference

                # Update hotspot list
                hotspots = self.thermal_detection.detect_hotspots()
                self.hotspot_listbox.delete(0, tk.END)

                for i, hotspot in enumerate(hotspots):
                    pos = hotspot['position']
                    temp = hotspot['avg_temp']
                    conf = hotspot['confidence']
                    self.hotspot_listbox.insert(tk.END, 
                        f"Hotspot {i+1}: ({pos[0]}, {pos[1]}) {temp:.1f}Â°C ({conf:.2f})")

        except Exception as e:
            self.logger.error(f"Error updating thermal display: {e}")

    def update_rf_data(self):
        """Update RF detection data"""
        try:
            if self.rf_receiver:
                # Clear existing data
                for item in self.rf_devices_tree.get_children():
                    self.rf_devices_tree.delete(item)

                # Add current devices
                active_devices = self.rf_receiver.get_detected_devices()
                for mac, device in active_devices.items():
                    last_seen = time.time() - device['last_seen']
                    position = device.get('estimated_position', ('--', '--'))

                    # Get latest detection for device type and RSSI
                    latest_detection = device['detections'][-1] if device['detections'] else {}
                    device_type = latest_detection.get('device_type', 'Unknown')
                    rssi = latest_detection.get('rssi', '--')

                    self.rf_devices_tree.insert('', tk.END, values=(
                        mac[:17], device_type, f"{rssi} dBm", f"{last_seen:.0f}s", 
                        f"({position[0]:.1f}, {position[1]:.1f})" if position != ('--', '--') else "--"
                    ))

                # Update ESP32 status
                esp32_status = "ESP32 Scanner Status:\n\n"
                for i in range(4):
                    esp32_status += f"ESP32 #{i+1}: Active\n"

                self.esp32_status_text.config(state='normal')
                self.esp32_status_text.delete(1.0, tk.END)
                self.esp32_status_text.insert(tk.END, esp32_status)
                self.esp32_status_text.config(state='disabled')

        except Exception as e:
            self.logger.error(f"Error updating RF data: {e}")

    def update_temp_threshold(self, value):
        """Update temperature threshold"""
        threshold = float(value)
        self.temp_threshold_label.configure(text=f"{threshold:.1f}Â°C")
        self.config['thermal']['temp_threshold'] = threshold

    # Control button callbacks
    def test_laser(self):
        """Test laser"""
        if self.alert_system:
            self.alert_system.test_laser()

    def test_buzzer(self):
        """Test buzzer"""
        if self.alert_system:
            self.alert_system.test_buzzer()

    def test_led(self):
        """Test LED"""
        if self.alert_system:
            self.alert_system.test_led()

    def center_servos(self):
        """Center servos"""
        if self.alert_system:
            self.alert_system.center_servos()

    def emergency_stop(self):
        """Emergency stop all alerts"""
        if self.alert_system:
            self.alert_system.emergency_stop()
            messagebox.showinfo("Emergency Stop", "All alerts have been stopped!")

    def trigger_test_alert(self):
        """Trigger a test alert at specified position"""
        if self.alert_system:
            x = self.test_x_var.get()
            y = self.test_y_var.get()
            self.alert_system.trigger_alert((x, y), "test_alert", 3)

    def toggle_system(self):
        """Toggle system start/stop"""
        # This would be implemented to start/stop the entire system
        if self.start_stop_button.cget('text') == 'Stop System':
            self.start_stop_button.configure(text='Start System')
            self.system_status.set("Stopped")
        else:
            self.start_stop_button.configure(text='Stop System')
            self.system_status.set("Running")

    def save_config(self):
        """Save current configuration"""
        try:
            import json
            with open('config.json', 'w') as f:
                json.dump(self.config, f, indent=4)
            messagebox.showinfo("Config Saved", "Configuration saved successfully!")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save config: {e}")

    def export_logs(self):
        """Export detection logs"""
        try:
            from tkinter import filedialog
            filename = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
            if filename:
                # Copy detection logs to selected file
                import shutil
                shutil.copy("data/detections.csv", filename)
                messagebox.showinfo("Export Complete", f"Logs exported to {filename}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export logs: {e}")

    def on_closing(self):
        """Handle window closing"""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=1)
        self.root.destroy()

# Test function
def test_dashboard():
    """Test dashboard without hardware"""
    from utils import load_config, setup_logging

    config = load_config()
    if not config:
        print("Failed to load config")
        return

    setup_logging(config['system']['log_level'])

    dashboard = ExamShieldDashboard(config)
    dashboard.start()

if __name__ == "__main__":
    test_dashboard()
