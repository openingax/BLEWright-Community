"""Byte/message relay only: no BLE state or fixture data. One TCP session per launch."""
import json
from pathlib import Path
import queue
import socket
import threading


PROTOCOL = json.loads((Path(__file__).resolve().parents[2] / "protocol/constants.json").read_text())


class RpcRelay:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=3)
        self.stream = self.socket.makefile('rb')
        try:
            self.hello = self._read()
            if self.hello.get('type') != 'hello' or self.hello.get('version') != PROTOCOL['version']:
                raise RuntimeError('Unsupported BLEWright protocol')
            if not isinstance(self.hello.get('sessionId'), str):
                raise RuntimeError('Missing RPC session ID')
        except Exception:
            self.stream.close()
            self.socket.close()
            raise
        self.socket.settimeout(None)
        self.queue = queue.Queue(maxsize=1024)
        self.closed = threading.Event()
        self.script = None
        self.threads = []

    def _read(self):
        line = self.stream.readline(PROTOCOL['maxFrameBytes'] + 2)
        if not line or len(line) > PROTOCOL['maxFrameBytes'] + 1 or not line.endswith(b'\n'):
            raise ConnectionError('RPC service disconnected or sent an invalid frame')
        frame = json.loads(line)
        if not isinstance(frame, dict):
            raise ConnectionError('Invalid RPC frame')
        return frame

    def start(self, script):
        self.script = script
        for target in (self._reader, self._writer):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()

    def send(self, request):
        if self.closed.is_set():
            return
        try:
            self.queue.put_nowait(request)
        except queue.Full:
            self._lost('RPC relay queue is full')

    def _reader(self):
        try:
            while not self.closed.is_set():
                frame = self._read()
                if frame.get('sessionId') != self.hello['sessionId'] or frame.get('version') != PROTOCOL['version']:
                    raise ConnectionError('RPC session mismatch')
                self.script.post({'type': 'rpc-frame', 'payload': frame})
        except Exception as error:
            self._lost(str(error))

    def _writer(self):
        try:
            while not self.closed.is_set():
                request = self.queue.get()
                if request is None:
                    return
                self.socket.sendall((json.dumps(request, separators=(',', ':')) + '\n').encode())
        except Exception as error:
            self._lost(str(error))

    def _lost(self, reason):
        if self.closed.is_set():
            return
        if self.script:
            try:
                self.script.post({'type': 'rpc-frame', 'payload': {'type': 'transportLost', 'reason': reason}})
            except Exception:
                pass
        self.close()

    def close(self):
        if self.closed.is_set():
            return
        self.closed.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()
        # Reader owns the file object; do not close its buffered reader while it blocks.
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1)
        self.stream.close()
