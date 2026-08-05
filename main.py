import socket
import time

print("Main process started. Connecting to stream_adapter.py...")

# Create client socket and connect
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(('127.0.0.1', 12345))

print("Connected successfully!")

# Phase 1: Send 5 data packets through the socket sequentially
for i in range(5):
    msg = f"Task update {i}"
    client.sendall(msg.encode('utf-8'))
    
    # This prints to YOUR terminal screen perfectly
    print(f"Sent to adapter: {msg}") 
    time.sleep(2)

print("\nPhase 1 complete. Now entering permanent listening loop...")

# Phase 2: Enter sequential "listen -> print" loop
while True:
    try:
        data = client.recv(1024)
        if not data:
            print("Adapter disconnected.")
            break
            
        # Decode and print incoming messages from Java via the adapter
        message = data.decode('utf-8')
        print(f"Received from Java: {message.strip()}")
        
    except ConnectionResetError:
        print("Connection lost.")
        break

client.close()
