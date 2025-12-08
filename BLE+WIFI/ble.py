import socket
import json
from datetime import datetime

# ==== CONFIG ====
UDP_IP = "0.0.0.0"      # Listen on all available interfaces
UDP_PORT = 12345        # Must match ESP32 udpPort value

print("========================================")
print("   📡 ESP32 BLE LIVE RECEIVER (UDP)     ")
print("========================================")
print(f"🔌 Listening on: {UDP_IP}:{UDP_PORT}")
print("📍 Waiting for BLE data...\n")

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print("✅ UDP socket ready!")
print("📡 Waiting for ESP32 BLE data...")
print("   (Make sure ESP32 ble.ino is uploaded with IP: 172.19.5.15)")
print("-" * 60 + "\n")


def print_device(data):
    """Pretty print device detection messages."""

    if "event" not in data:
        print("⚠️ Unknown packet:", data)
        return

    event = data["event"]

    if event == "FREQUENT_DEVICES_SUMMARY":
        print("\n\n================ SUMMARY =================")
        print(f"📊 Total Scans: {data.get('totalScans')}")
        print(f"📍 Frequent Devices Count: {data.get('frequentDevicesCount')}")
        print("------------------------------------------")

        for i, dev in enumerate(data.get("devices", []), start=1):
            print(f"{i}. {dev['name']} ({dev['address']})")
            print(f"   RSSI: {dev['rssi']}  | Distance: {dev['distance']:.2f}m")
            print(f"   Seen Count: {dev['seenCount']}")
            print("")

        print("==========================================\n")

    else:
        dev = data["device"]
        print(f"📲 Device Detected: {dev['name']} ({dev['address']})")
        print(f"   RSSI: {dev['rssi']}  | Distance: {dev['distance']:.2f}m")
        print(f"   Seen {dev['seenCount']} times")
        print("-----------------------------------------")


packet_count = 0
json_buffer = ""  # Buffer for reassembling fragmented JSON

while True:
    raw_data, addr = sock.recvfrom(4096)  # receive UDP packet
    packet_count += 1
    
    print(f"\n{'='*60}")
    print(f"📦 Packet #{packet_count} Received | Size: {len(raw_data)} bytes | From: {addr[0]}:{addr[1]}")
    print(f"{'='*60}")
    
    try:
        # Decode the packet
        decoded = None
        try:
            decoded = raw_data.decode("utf-8")
            print(f"✅ UTF-8 decode successful")
        except UnicodeDecodeError as ude:
            print(f"⚠️ UTF-8 failed, trying latin-1...")
            decoded = raw_data.decode("latin-1")
            print(f"✅ Latin-1 decode successful")
        
        # Add to buffer
        json_buffer += decoded
        print(f"📝 Buffer size: {len(json_buffer)} chars")
        
        # Check if JSON is complete by counting braces
        open_braces = json_buffer.count('{')
        close_braces = json_buffer.count('}')
        
        print(f"🔢 Braces: {{ = {open_braces}, }} = {close_braces}")
        
        if open_braces > 0 and open_braces == close_braces:
            # JSON looks complete, try to parse it
            print(f"✅ JSON appears complete, attempting parse...")
            
            try:
                json_data = json.loads(json_buffer)
                print(f"✅ JSON parsed successfully!")
                print(f"📊 JSON keys: {list(json_data.keys())}")
                
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"\n⏱ {timestamp} | Processing complete JSON...")
                print_device(json_data)
                
                # Clear buffer after successful parse
                json_buffer = ""
                
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON parse failed despite balanced braces")
                print(f"   Error: {e}")
                print(f"   Error position: {e.pos if hasattr(e, 'pos') else 'N/A'}")
                print(f"   Clearing buffer and starting fresh...")
                json_buffer = ""
        else:
            print(f"⏳ JSON incomplete, waiting for more packets...")
            print(f"   Preview (last 100 chars): ...{json_buffer[-100:]}")

    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR!")
        print(f"   Type: {type(e).__name__}")
        print(f"   Error: {e}")
        print(f"   Clearing buffer...")
        json_buffer = ""
        import traceback
        traceback.print_exc()
