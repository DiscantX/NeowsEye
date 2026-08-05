"""
Stream Client

Bridges the main program to stream_adapter.py — and through it, CommunicationMod —
over a plain TCP socket, using the framing/buffering shared in StreamPeer.

Unlike StreamAdapter, this class doesn't block the caller on an incoming
loop. Incoming lines are parsed off a background thread and handed to the
main program through a queue, since main.py has its own game logic to run
between messages rather than a passive Java-stdout stream to forward.
"""

import json
import socket
import threading
import queue
import time

from stream_peer import StreamPeer, HOST, PORT


class StreamClient(StreamPeer):
    def __init__(self, host=HOST, port=PORT):
        super().__init__(host, port)
        self._incoming_queue = queue.Queue()

    def start(self):
        """Connects to stream_adapter.py and starts the incoming relay thread."""
        self._establish_connection()
        incoming_thread = threading.Thread(target=self._relay_incoming, daemon=True)
        incoming_thread.start()

    def _establish_connection(self, retry_interval=1.0):
        """Opens a client socket to stream_adapter.py's server, retrying until
        it comes up (or max_attempts is exhausted)."""
        attempt = 0
        while True:
            attempt += 1
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                self.socket.connect((self.host, self.port))
                return
            except ConnectionRefusedError:
                self.socket.close()
                print(f"Adapter not ready yet (attempt {attempt}), retrying in {retry_interval}s...")
                time.sleep(retry_interval)

        raise ConnectionError(
            f"Could not connect to stream_adapter.py at {self.host}:{self.port} "
            f"after {max_attempts} attempts. Is CommunicationMod running?"
        )

    def _relay_incoming(self):
        """THREAD: reads lines from stream_adapter.py and queues them, parsed."""
        for line in self._read_lines():
            self._incoming_queue.put(self._parse(line))
        self._incoming_queue.put(None)  # sentinel: adapter disconnected

    @staticmethod
    def _parse(line):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return {"raw": line}

    def get_message(self, timeout=None):
        """Blocks for the next parsed message (dict), or returns None if the adapter disconnected."""
        try:
            return self._incoming_queue.get(timeout=timeout)
        except queue.Empty:
            return None