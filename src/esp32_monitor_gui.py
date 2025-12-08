"""
ESP32 Monitor GUI - BLE and WiFi Monitoring Interface
Runs alongside ExamShield for real-time ESP32 sensor data visualization
Author: Morshed MD Monoarul
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import socket
import json
import struct
import threading
import time
from datetime import datetime
import queue


class ModernStyle:
    """Dark theme styling matching ExamShield aesthetics"""
    BG_DARK = "#1a1a1a"
    BG_MEDIUM = "#2d2d2d"
    BG_LIGHT = "#3d3d3d"
    ACCENT = "#32b8c6"
    SUCCESS = "#4caf76"
    WARNING = "#ff9800"
    DANGER = "#f44336"
    TEXT_PRIMARY = "#ffffff"
    TEXT_SECONDARY = "#b0b0b0"
    FONT_FAMILY = "Segoe UI"


class BLEMonitor:
    """Handles BLE device monitoring via UDP"""
    
    def __init__(self, data_queue, status_callback):
        self.data_queue = data_queue
        self.status_callback = status_callback
        self.running = False
        self.thread = None
        self.udp_port = 12345
        self.sock = None
        self.json_buffer = ""  # Buffer for reassembling fragmented JSON
        
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
    
    def _receive_loop(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
            self.sock.settimeout(1.0)
            self.sock.bind(("0.0.0.0", self.udp_port))
            self.status_callback("BLE", f"Listening on port {self.udp_port}")
            
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                    
                    # Decode packet
                    try:
                        decoded = data.decode('utf-8')
                    except UnicodeDecodeError:
                        decoded = data.decode('latin-1')
                    
                    # Add to buffer
                    self.json_buffer += decoded
                    
                    # Check if JSON is complete by counting braces
                    open_braces = self.json_buffer.count('{')
                    close_braces = self.json_buffer.count('}')
                    
                    if open_braces > 0 and open_braces == close_braces:
                        # JSON looks complete, try to parse
                        try:
                            json_data = json.loads(self.json_buffer)
                            self.data_queue.put(("BLE", json_data))
                            self.json_buffer = ""  # Clear buffer after success
                        except json.JSONDecodeError:
                            # Parse failed, clear buffer
                            self.json_buffer = ""
                    # else: JSON incomplete, wait for more packets
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.status_callback("BLE", f"Error: {str(e)[:30]}")
                        self.json_buffer = ""  # Clear buffer on error
                        time.sleep(1)
        except Exception as e:
            self.status_callback("BLE", f"Failed: {str(e)[:30]}")
        finally:
            if self.sock:
                self.sock.close()


class WiFiMonitor:
    """Handles WiFi packet monitoring via UDP"""
    
    def __init__(self, data_queue, status_callback):
        self.data_queue = data_queue
        self.status_callback = status_callback
        self.running = False
        self.thread = None
        self.udp_port = 8888
        self.sock = None
        # Struct packet format matching ESP32
        # uint8_t mac[6], int8_t rssi, uint32_t timestamp, uint16_t packet_len,
        # uint8_t channel, uint8_t packet_type
        self.packet_format = "<6B b I H B B"
        self.packet_size = struct.calcsize(self.packet_format)
        
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
    
    def _receive_loop(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
            self.sock.settimeout(1.0)
            self.sock.bind(("0.0.0.0", self.udp_port))
            self.status_callback("WiFi", f"Listening on UDP port {self.udp_port}")
            
            packet_count = 0
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    
                    # Try to decode as binary struct first
                    if len(data) == self.packet_size:
                        pkt = struct.unpack(self.packet_format, data)
                        
                        mac = pkt[:6]
                        rssi = pkt[6]
                        timestamp = pkt[7]
                        length = pkt[8]
                        channel = pkt[9]
                        pkt_type = pkt[10]
                        
                        mac_str = ':'.join(f'{b:02X}' for b in mac)
                        
                        packet_count += 1
                        packet_data = {
                            "mac": mac_str,
                            "rssi": rssi,
                            "channel": channel,
                            "length": length,
                            "type": pkt_type,
                            "timestamp": timestamp,
                            "count": packet_count,
                            "time": datetime.now().strftime("%H:%M:%S")
                        }
                        self.data_queue.put(("WiFi", packet_data))
                    else:
                        # Fallback for text data
                        try:
                            text = data.decode().strip()
                            self.data_queue.put(("WiFi_MSG", text))
                        except:
                            pass
                            
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        self.status_callback("WiFi", f"Error: {str(e)[:30]}")
                        time.sleep(1)
        except Exception as e:
            self.status_callback("WiFi", f"Failed: {str(e)[:30]}")
        finally:
            if self.sock:
                self.sock.close()


class ESP32MonitorGUI:
    """Main GUI Application for ESP32 Monitoring"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("ESP32 Monitor - ExamShield")
        self.root.geometry("800x600")
        self.root.configure(bg=ModernStyle.BG_DARK)
        self.root.minsize(700, 500)
        
        # Data queue for thread-safe communication
        self.data_queue = queue.Queue()
        
        # Monitors
        self.ble_monitor = BLEMonitor(self.data_queue, self._update_status)
        self.wifi_monitor = WiFiMonitor(self.data_queue, self._update_status)
        
        # Device tracking
        self.ble_devices = {}
        self.wifi_devices = {}
        self.wifi_packet_count = 0
        
        # Unified device tracking for deduplication (MAC -> {sources: set, data: dict})
        self.all_devices = {}
        
        # Status variables
        self.ble_status = tk.StringVar(value="Not started")
        self.wifi_status = tk.StringVar(value="Not connected")
        
        self._setup_styles()
        self._create_widgets()
        self._start_update_loop()
        
        # Auto-start both BLE and WiFi monitoring
        self.ble_monitor.start()
        self.wifi_monitor.start()
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure notebook (tabs)
        style.configure("TNotebook", background=ModernStyle.BG_DARK)
        style.configure("TNotebook.Tab", 
                       background=ModernStyle.BG_MEDIUM,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       padding=[20, 10],
                       font=(ModernStyle.FONT_FAMILY, 11, 'bold'))
        style.map("TNotebook.Tab",
                 background=[("selected", ModernStyle.ACCENT)],
                 foreground=[("selected", ModernStyle.TEXT_PRIMARY)])
        
        # Configure frames
        style.configure("Dark.TFrame", background=ModernStyle.BG_DARK)
        style.configure("Card.TFrame", background=ModernStyle.BG_MEDIUM)
        
        # Configure labels
        style.configure("Title.TLabel",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.ACCENT,
                       font=(ModernStyle.FONT_FAMILY, 14, 'bold'))
        style.configure("Status.TLabel",
                       background=ModernStyle.BG_DARK,
                       foreground=ModernStyle.TEXT_SECONDARY,
                       font=(ModernStyle.FONT_FAMILY, 10))
        
        # Configure buttons
        style.configure("Accent.TButton",
                       background=ModernStyle.ACCENT,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       font=(ModernStyle.FONT_FAMILY, 10, 'bold'),
                       padding=[15, 8])
        
        # Configure Treeview
        style.configure("Treeview",
                       background=ModernStyle.BG_MEDIUM,
                       foreground=ModernStyle.TEXT_PRIMARY,
                       fieldbackground=ModernStyle.BG_MEDIUM,
                       font=(ModernStyle.FONT_FAMILY, 10))
        style.configure("Treeview.Heading",
                       background=ModernStyle.BG_LIGHT,
                       foreground=ModernStyle.ACCENT,
                       font=(ModernStyle.FONT_FAMILY, 10, 'bold'))
        style.map("Treeview", background=[("selected", ModernStyle.ACCENT)])
    
    def _create_widgets(self):
        # Header
        header = ttk.Frame(self.root, style="Dark.TFrame")
        header.pack(fill=tk.X, padx=20, pady=15)
        
        title = ttk.Label(header, text="📡 ESP32 SENSOR MONITOR", style="Title.TLabel")
        title.pack(side=tk.LEFT)
        
        # Notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))
        
        # BLE Tab
        self.ble_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(self.ble_frame, text="📶 BLE Devices")
        self._create_ble_tab()
        
        # WiFi Tab
        self.wifi_frame = ttk.Frame(self.notebook, style="Dark.TFrame")
        self.notebook.add(self.wifi_frame, text="📻 WiFi Packets")
        self._create_wifi_tab()
        
        # Status bar
        self._create_status_bar()
    
    def _create_ble_tab(self):
        # Controls
        ctrl_frame = ttk.Frame(self.ble_frame, style="Dark.TFrame")
        ctrl_frame.pack(fill=tk.X, pady=10)
        
        status_lbl = ttk.Label(ctrl_frame, textvariable=self.ble_status, style="Status.TLabel")
        status_lbl.pack(side=tk.LEFT)
        
        self.ble_count_var = tk.StringVar(value="Devices: 0")
        count_lbl = ttk.Label(ctrl_frame, textvariable=self.ble_count_var, style="Status.TLabel")
        count_lbl.pack(side=tk.RIGHT)
        
        # Create horizontal split: devices tree on left, activity log on right
        paned = tk.PanedWindow(self.ble_frame, orient=tk.HORIZONTAL, 
                               bg=ModernStyle.BG_DARK, bd=0, sashwidth=5)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # Left panel: BLE devices tree
        tree_frame = ttk.Frame(paned, style="Dark.TFrame")
        paned.add(tree_frame, width=500)
        
        columns = ("Rank", "Device", "MAC", "RSSI", "Distance", "Seen", "Alert")
        self.ble_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=15)
        
        self.ble_tree.heading("Rank", text="#")
        self.ble_tree.heading("Device", text="Device Name")
        self.ble_tree.heading("MAC", text="MAC Address")
        self.ble_tree.heading("RSSI", text="RSSI")
        self.ble_tree.heading("Distance", text="Distance")
        self.ble_tree.heading("Seen", text="Times")
        self.ble_tree.heading("Alert", text="Alert Level")
        
        self.ble_tree.column("Rank", width=30, anchor=tk.CENTER)
        self.ble_tree.column("Device", width=120)
        self.ble_tree.column("MAC", width=120)
        self.ble_tree.column("RSSI", width=60, anchor=tk.CENTER)
        self.ble_tree.column("Distance", width=80, anchor=tk.CENTER)
        self.ble_tree.column("Seen", width=50, anchor=tk.CENTER)
        self.ble_tree.column("Alert", width=100)
        
        # Scrollbar for tree
        ble_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.ble_tree.yview)
        self.ble_tree.configure(yscrollcommand=ble_scroll.set)
        
        self.ble_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ble_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Tag colors for alerts
        self.ble_tree.tag_configure("critical", background="#4a1a1a")
        self.ble_tree.tag_configure("high", background="#4a3a1a")
        self.ble_tree.tag_configure("medium", background="#3a3a1a")
        self.ble_tree.tag_configure("low", background=ModernStyle.BG_MEDIUM)
        
        # Right panel: Activity log
        log_frame = ttk.Frame(paned, style="Dark.TFrame")
        paned.add(log_frame, width=300)
        
        log_label = ttk.Label(log_frame, text="📜 Activity Log", style="Status.TLabel")
        log_label.pack(pady=5)
        
        self.ble_log = scrolledtext.ScrolledText(
            log_frame, 
            height=20, 
            bg=ModernStyle.BG_MEDIUM,
            fg=ModernStyle.TEXT_PRIMARY,
            font=(ModernStyle.FONT_FAMILY, 9),
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.ble_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Configure log text tags
        self.ble_log.tag_config("info", foreground=ModernStyle.TEXT_SECONDARY)
        self.ble_log.tag_config("success", foreground=ModernStyle.SUCCESS)
        self.ble_log.tag_config("warning", foreground=ModernStyle.WARNING)
        self.ble_log.tag_config("error", foreground=ModernStyle.DANGER)
    
    def _create_wifi_tab(self):
        # Controls
        ctrl_frame = ttk.Frame(self.wifi_frame, style="Dark.TFrame")
        ctrl_frame.pack(fill=tk.X, pady=10)
        
        status_lbl = ttk.Label(ctrl_frame, textvariable=self.wifi_status, style="Status.TLabel")
        status_lbl.pack(side=tk.LEFT)
        
        self.wifi_count_var = tk.StringVar(value="Packets: 0 | Unique MACs: 0")
        count_lbl = ttk.Label(ctrl_frame, textvariable=self.wifi_count_var, style="Status.TLabel")
        count_lbl.pack(side=tk.RIGHT)
        
        # WiFi packets tree
        columns = ("Time", "MAC", "RSSI", "Channel", "Length", "Type", "Distance")
        self.wifi_tree = ttk.Treeview(self.wifi_frame, columns=columns, show="headings", height=15)
        
        self.wifi_tree.heading("Time", text="Time")
        self.wifi_tree.heading("MAC", text="MAC Address")
        self.wifi_tree.heading("RSSI", text="RSSI")
        self.wifi_tree.heading("Channel", text="Channel")
        self.wifi_tree.heading("Length", text="Length")
        self.wifi_tree.heading("Type", text="Type")
        self.wifi_tree.heading("Distance", text="Est. Dist")
        
        self.wifi_tree.column("Time", width=70, anchor=tk.CENTER)
        self.wifi_tree.column("MAC", width=150)
        self.wifi_tree.column("RSSI", width=60, anchor=tk.CENTER)
        self.wifi_tree.column("Channel", width=60, anchor=tk.CENTER)
        self.wifi_tree.column("Length", width=60, anchor=tk.CENTER)
        self.wifi_tree.column("Type", width=50, anchor=tk.CENTER)
        self.wifi_tree.column("Distance", width=70, anchor=tk.CENTER)
        
        # Scrollbar
        wifi_scroll = ttk.Scrollbar(self.wifi_frame, orient=tk.VERTICAL, command=self.wifi_tree.yview)
        self.wifi_tree.configure(yscrollcommand=wifi_scroll.set)
        
        self.wifi_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        wifi_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _create_status_bar(self):
        status_bar = ttk.Frame(self.root, style="Card.TFrame")
        status_bar.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        self.main_status = tk.StringVar(value="Ready - Listening for ESP32 data...")
        status_lbl = ttk.Label(status_bar, textvariable=self.main_status, 
                               style="Status.TLabel", padding=[10, 5])
        status_lbl.pack(side=tk.LEFT)
        
        time_var = tk.StringVar()
        time_lbl = ttk.Label(status_bar, textvariable=time_var, 
                            style="Status.TLabel", padding=[10, 5])
        time_lbl.pack(side=tk.RIGHT)
        
        def update_time():
            time_var.set(datetime.now().strftime("%H:%M:%S"))
            self.root.after(1000, update_time)
        update_time()
    
    
    def _update_status(self, monitor_type, message):
        if monitor_type == "BLE":
            self.ble_status.set(f"BLE: {message}")
        elif monitor_type == "WiFi":
            self.wifi_status.set(f"WiFi: {message}")
    
    def _start_update_loop(self):
        self._process_queue()
    
    def _process_queue(self):
        try:
            while True:
                data_type, data = self.data_queue.get_nowait()
                if data_type == "BLE":
                    self._handle_ble_data(data)
                elif data_type == "WiFi":
                    self._handle_wifi_data(data)
                elif data_type == "WiFi_MSG":
                    self.main_status.set(f"ESP32: {data[:50]}")
        except queue.Empty:
            pass
        
        # Schedule next update
        self.root.after(100, self._process_queue)
    
    def _log_ble_message(self, message, tag="info"):
        """Add message to BLE activity log"""
        self.ble_log.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.ble_log.insert(tk.END, f"[{timestamp}] ", "info")
        self.ble_log.insert(tk.END, f"{message}\n", tag)
        self.ble_log.see(tk.END)
        self.ble_log.config(state=tk.DISABLED)
    
    def _handle_ble_data(self, json_data):
        event_type = json_data.get("event", "")
        
        if not event_type:
            self._log_ble_message("⚠️ Unknown packet format", "warning")
            return
        
        if event_type == "FREQUENT_DEVICES_SUMMARY":
            # Log summary event
            total_scans = json_data.get('totalScans', 0)
            total_devices = json_data.get('totalDevices', 0)
            frequent_count = json_data.get('frequentDevicesCount', 0)
            
            self._log_ble_message("=" * 40, "success")
            self._log_ble_message(f"📊 SUMMARY - Scan #{total_scans}", "success")
            self._log_ble_message(f"Total Devices Tracked: {total_devices}", "info")
            self._log_ble_message(f"Frequent Devices (5+ seen): {frequent_count}", "info")
            
            # Clear existing items
            for item in self.ble_tree.get_children():
                self.ble_tree.delete(item)
            
            devices = json_data.get("devices", [])
            
            # Count devices seen by both BLE and WiFi
            both_count = sum(1 for d in self.all_devices.values() if len(d["sources"]) > 1)
            
            self.ble_count_var.set(
                f"Devices: {len(devices)} | Scans: {total_scans} | "
                f"Both BLE+WiFi: {both_count}"
            )
            
            for device in devices:
                rank = device.get('rank', '?')
                name = device.get('name', 'Unknown')
                address = device.get('address', 'N/A')
                rssi = device.get('rssi', 0)
                distance = device.get('distance', 0)
                seen_count = device.get('seenCount', 0)
                
                # Log each device
                self._log_ble_message(
                    f"  #{rank} {name} ({address}) - {distance:.2f}m, seen {seen_count}x",
                    "info"
                )
                
                # Update unified device tracker
                if address not in self.all_devices:
                    self.all_devices[address] = {"sources": set(), "name": name, "distance": distance}
                self.all_devices[address]["sources"].add("BLE")
                self.all_devices[address]["name"] = name
                self.all_devices[address]["distance"] = min(
                    self.all_devices[address].get("distance", 999), distance
                )
                
                # Add source indicator
                source_icon = ""
                if address in self.all_devices and "WiFi" in self.all_devices[address]["sources"]:
                    source_icon = "📶+📻"  # Seen by both
                else:
                    source_icon = "📶"  # BLE only
                
                # Determine alert level
                if distance < 0.1:
                    alert = "🔴 CRITICAL"
                    tag = "critical"
                elif distance < 1.0:
                    alert = "🟠 HIGH"
                    tag = "high"
                elif distance < 3.0:
                    alert = "🟡 MEDIUM"
                    tag = "medium"
                else:
                    alert = "🟢 LOW"
                    tag = "low"
                
                self.ble_tree.insert("", tk.END, values=(
                    rank,
                    f"{source_icon} {name[:17]}" if source_icon else name[:20],
                    address,
                    f"{rssi} dBm",
                    f"{distance:.2f}m",
                    seen_count,
                    alert
                ), tags=(tag,))
            
            self._log_ble_message("=" * 40, "success")
            
        else:
            # Handle individual device detection events
            device = json_data.get("device", {})
            name = device.get('name', 'Unknown')
            address = device.get('address', 'N/A')
            rssi = device.get('rssi', 0)
            distance = device.get('distance', 0)
            seen_count = device.get('seenCount', 0)
            
            self._log_ble_message(
                f"📲 Device: {name} ({address})",
                "success"
            )
            self._log_ble_message(
                f"   RSSI: {rssi} dBm | Dist: {distance:.2f}m | Seen: {seen_count}x",
                "info"
            )
    
    def _handle_wifi_data(self, packet_data):
        mac = packet_data.get("mac", "")
        rssi = packet_data.get("rssi", 0)
        
        # Estimate distance from RSSI (rough approximation)
        # Formula: distance = 10 ^ ((RSSI + 59) / (-20))
        # This is a rough estimate for WiFi signals
        try:
            estimated_distance = pow(10, (rssi + 59) / -20.0)
            distance_str = f"{estimated_distance:.2f}m"
        except:
            estimated_distance = 0
            distance_str = "N/A"
        
        # Track unique devices
        if mac not in self.wifi_devices:
            self.wifi_devices[mac] = {"count": 0, "distance": estimated_distance}
        self.wifi_devices[mac]["count"] += 1
        self.wifi_devices[mac]["distance"] = min(self.wifi_devices[mac]["distance"], estimated_distance)
        
        # Update unified device tracker
        if mac not in self.all_devices:
            self.all_devices[mac] = {"sources": set(), "name": "Unknown", "distance": estimated_distance}
        self.all_devices[mac]["sources"].add("WiFi")
        self.all_devices[mac]["distance"] = min(self.all_devices[mac].get("distance", 999), estimated_distance)
        
        self.wifi_packet_count += 1
        
        # Count devices seen by both BLE and WiFi
        both_count = sum(1 for d in self.all_devices.values() if len(d["sources"]) > 1)
        
        self.wifi_count_var.set(
            f"Packets: {self.wifi_packet_count} | Unique: {len(self.wifi_devices)} | "
            f"Both BLE+WiFi: {both_count}"
        )
        
        # Add source indicator
        source_icon = ""
        if mac in self.all_devices and "BLE" in self.all_devices[mac]["sources"]:
            source_icon = "📶+📻"  # Seen by both
        else:
            source_icon = "📻"  # WiFi only
        
        # Add to tree (keep last 100 entries)
        children = self.wifi_tree.get_children()
        if len(children) > 100:
            self.wifi_tree.delete(children[0])
        
        self.wifi_tree.insert("", tk.END, values=(
            packet_data.get("time", ""),
            f"{source_icon} {mac}" if source_icon else mac,
            f"{rssi} dBm",
            packet_data.get("channel", 0),
            packet_data.get("length", 0),
            packet_data.get("type", 0),
            distance_str
        ))
        
        # Auto-scroll to latest
        self.wifi_tree.yview_moveto(1)
    
    def _on_close(self):
        self.ble_monitor.stop()
        self.wifi_monitor.stop()
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()


def main():
    app = ESP32MonitorGUI()
    app.run()


if __name__ == "__main__":
    main()
