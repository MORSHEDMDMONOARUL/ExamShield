import socket
import struct

# ==== SETTINGS ====
UDP_IP = "0.0.0.0"        # Listen on all network interfaces
UDP_PORT = 8888

# Packet structure from ESP32
# 6 bytes MAC, int8 RSSI, uint32 timestamp, uint16 len, uint8 channel, uint8 type
packet_format = "<6B b I H B B"
packet_size = struct.calcsize(packet_format)

print("======================================")
print(" UDP PACKET RECEIVER STARTED ")
print(" Listening on port:", UDP_PORT)
print("======================================\n")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

def format_mac(mac_bytes):
    return ":".join(f"{b:02X}" for b in mac_bytes)

while True:
    data, addr = sock.recvfrom(1024)

    # Try to decode as binary struct first
    if len(data) == packet_size:
        unpacked = struct.unpack(packet_format, data)

        mac = format_mac(unpacked[:6])
        rssi = unpacked[6]
        timestamp = unpacked[7]
        length = unpacked[8]
        channel = unpacked[9]
        pkt_type = unpacked[10]

        print(f"[BINARY] MAC: {mac}, RSSI: {rssi}, CH: {channel}, LEN: {length}, TYPE: {pkt_type}")

    else:
        # Fallback readable text line
        try:
            text = data.decode().strip()
            print(f"[TEXT] {text}")
        except:
            print(f"[RAW] {data}")
