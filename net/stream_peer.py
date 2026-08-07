"""
Stream Peer

Shared base for the two ends of the NeowsEye socket bridge:
  - StreamAdapter (stream_adapter.py): the server side, run as a
    CommunicationMod subprocess, bridging stdin/stdout to the socket.
  - StreamClient (stream_client.py): the client side, used by main.py
    to talk to the adapter.

Both sides speak the same wire format: newline-delimited UTF-8 text.
This class owns the socket, the newline framing/buffering, and sending.
Subclasses own connection setup (server-accept vs. client-connect) and
what they do with each line once it arrives.
"""

import socket

HOST = '127.0.0.1'
PORT = 12345
BUFFER_SIZE = 4096


class StreamPeer:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.socket = None  # set by subclass once connected
        self._buffer = ""

    def send(self, message):
        """Sends a single newline-delimited message over the socket."""
        self.socket.sendall(f"{message}\n".encode('utf-8'))

    def _read_lines(self, sock=None):
        """Generator yielding complete newline-delimited lines as they arrive
        on the given socket (or self.socket if not specified). Stops
        (StopIteration) when the peer disconnects or the socket errors."""
        sock = sock if sock is not None else self.socket
        buffer = ""
        while True:
            try:
                data = sock.recv(BUFFER_SIZE)
            except (ConnectionResetError, OSError):
                return
            if not data:
                return
            buffer += data.decode('utf-8')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                if line:
                    yield line

    def close(self):
        if self.socket:
            self.socket.close()