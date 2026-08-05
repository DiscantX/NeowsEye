"""
Stream Adapter 

Bridges communication between CommunicationMod's stdin/stdout protocol
and the main program by routing messages through network sockets.

Note that this script should be run as a subprocess of CommunicationMod.
It is not run at all by the main program. The only interaction it has with
main is through web sockets.

To run this as a subprocess of CommuncationMod, you must point the mod's
`config.properties file to this file.

Instructions can be found at: https://github.com/ForgottenArbiter/CommunicationMod

A word of caution: Ensure you point it to the correct interpreter. This is especially
important if using venv. Example usage:
`command=C\:/Users/Username/Documents/python/NeowsEye/.venv/Scripts/python.exe C\:/Users/Username/Documents/python/NeowsEye/stream_adapter.py`
"""

import socket
import sys
import threading

class Adapter:
    def __init__(self, host='127.0.0.1', port=12345):
        self.host = host
        self.port = port
        self.connection = None
        self.address = None
        self.send_ready_signal()
        self.create_server()        # Warning: blocks until main.py connects
        
    def create_server(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)
        # Sits here until you open your terminal and run main.py
        self.connection, self.address = self.server.accept()
        
    def send_ready_signal(self):
        print("ready", flush=True)    
        
    def relay_from_main_to_java(self):
        """THREAD 1: Continually reads from main.py socket and prints to Java"""
        while True:
            try:
                data = self.connection.recv(1024)
                if not data:
                    break
                message = data.decode('utf-8')
                print(f"FROM_MAIN: {message}", flush=True)   
            except ConnectionResetError:
                break
                
    def relay_from_java_to_main(self):
        """THREAD 2: Continually reads from Java stdin and sends to main.py socket"""
        # This acts as your loop over _read_stdin
        for line in sys.stdin:
            message = line.strip()
            
            # Complete logic: encode string to bytes and send over socket
            try:
                payload = f"{message}\n".encode('utf-8')
                self.connection.sendall(payload)
            except Exception as e:
                print(f"Socket send failed: {e}", file=sys.stderr)

    def communicate(self):
        # Spin up Thread 1 to handle main.py -> Java
        main_to_java_thread = threading.Thread(target=self.relay_from_main_to_java, daemon=True)
        main_to_java_thread.start()
        
        # Run Thread 2 on the MAIN thread to handle Java -> main.py
        # This keeps the script alive and prevents it from exiting immediately
        self.relay_from_java_to_main()
        
        # Clean up if the stdin loop ever finishes
        self.connection.close()
        self.server.close()

def main():
    adapter = Adapter()
    adapter.communicate()

if __name__ == "__main__":
    main()
