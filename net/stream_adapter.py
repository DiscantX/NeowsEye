"""
Stream Adapter

Bridges communication between CommunicationMod's stdin/stdout protocol
and the main program by routing messages through a TCP socket.

Note that this script should be run as a subprocess of CommunicationMod.
It is not run at all by the main program. The only interaction it has with
main is through the socket, via stream_client.py.

Survives main.py restarting: the adapter keeps accepting new connections
for its whole lifetime, so you can stop/restart main.py without restarting
the game or CommunicationMod. Only one client is served at a time; a new
connection replaces the previous one.

To run this as a subprocess of CommunicationMod, you must point the mod's
`config.properties` file to this file. On Windows, the file can be found at:
%LOCALAPPDATA%\\ModTheSpire\\CommunicationMod

Instructions can be found at: https://github.com/ForgottenArbiter/CommunicationMod

A word of caution: Ensure you point it to the correct interpreter. This is especially
important if using venv. Example usage:
`command=C\:/Users/Username/Documents/python/NeowsEye/.venv/Scripts/python.exe C\:/Users/Username/Documents/python/NeowsEye/stream_adapter.py`
"""

import socket
import sys
import threading

from stream_peer import StreamPeer, HOST, PORT


class StreamAdapter(StreamPeer):
    def __init__(self, host=HOST, port=PORT):
        super().__init__(host, port)
        self.server = None
        self.connection_address = None
        self._socket_lock = threading.Lock()

    def start(self):
        """Announces readiness to CommunicationMod and opens the listening socket."""
        self._send_ready_signal()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.host, self.port))
        self.server.listen(1)

    def _send_ready_signal(self):
        print("ready", flush=True)

    def _accept_loop(self):
        """THREAD: repeatedly accepts new client connections for the life of the
        process, so main.py can be stopped and restarted without restarting
        this adapter or the game. Each accepted connection gets its own
        incoming-relay thread; a new connection replaces the previous one."""
        while True:
            connection, address = self.server.accept()
            print(f"Client connected: {address}", file=sys.stderr, flush=True)

            with self._socket_lock:
                self.socket = connection
                self.connection_address = address
                self._buffer = ""  # discard any partial line from a prior connection

            relay_thread = threading.Thread(
                target=self._relay_incoming, args=(connection,), daemon=True
            )
            relay_thread.start()

    def _relay_incoming(self, connection):
        """THREAD: reads lines from one client connection (via the socket) and
        prints them to Java. Exits when that connection closes."""
        for line in self._read_lines(connection):
            print(line, flush=True)

        with self._socket_lock:
            if self.socket is connection:
                print("Client disconnected.", file=sys.stderr, flush=True)
                self.socket = None

    def _relay_outgoing(self):
        """MAIN THREAD: reads lines from Java's stdout (piped to our stdin) and
        sends them to whichever client is currently connected, if any."""
        for line in sys.stdin:
            message = line.strip()
            if not message:
                continue
            with self._socket_lock:
                current_socket = self.socket
            if current_socket is None:
                # No client connected right now; nothing to send to. The
                # client will get a fresh snapshot via 'state' once it
                # reconnects, so dropping this is safe rather than blocking.
                continue
            try:
                current_socket.sendall(f"{message}\n".encode('utf-8'))
            except OSError as e:
                print(f"Socket send failed: {e}", file=sys.stderr)

    def communicate(self):
        """Starts the accept loop, then runs the outgoing relay on the main
        thread. This keeps the process alive for as long as Java's stdout
        stays open, across any number of client connect/disconnect cycles."""
        accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        accept_thread.start()

        self._relay_outgoing()

        self.close()
        self.server.close()


def main():
    adapter = StreamAdapter()
    adapter.start()
    adapter.communicate()


if __name__ == "__main__":
    main()