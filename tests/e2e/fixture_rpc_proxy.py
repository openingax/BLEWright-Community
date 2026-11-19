#!/usr/bin/env python3
"""Test-only proxy for existing UI tests: restrict writes to a USB-verified fixture.

The production general service remains unrestricted. Normal clients never use
this helper. It lets UI suites that select by name run safely against that service.
"""
import argparse
import json
from pathlib import Path
import socket
import socketserver
import threading


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--identity', type=Path, required=True)
    p.add_argument('--upstream-port', type=int, required=True)
    p.add_argument('--port', type=int, required=True)
    args = p.parse_args()
    target = json.loads(args.identity.read_text())
    nonce = target['nonce']
    nonce = list(bytes.fromhex(nonce)) if isinstance(nonce, str) else nonce
    address = target['address'].upper()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            with socket.create_connection(('127.0.0.1', args.upstream_port), timeout=3) as upstream:
                upstream.settimeout(None)
                stream = upstream.makefile('rb')
                lock = threading.Lock()
                proven = threading.Event()
                def send(frame):
                    with lock:
                        self.connection.sendall((json.dumps(frame) + '\n').encode())
                def receive():
                    try:
                        for line in stream:
                            frame = json.loads(line)
                            if frame.get('event') == 'advertisement':
                                d = frame['device']
                                if d['address'].upper() != address or d.get('manufacturerData') != [255, 255, *nonce]:
                                    continue
                                proven.set()
                            send(frame)
                    except (OSError, ValueError):
                        pass
                    finally:
                        try: self.connection.shutdown(socket.SHUT_RDWR)
                        except OSError: pass
                thread = threading.Thread(target=receive, daemon=True)
                thread.start()
                try:
                    for line in self.rfile:
                        q = json.loads(line)
                        if q.get('method') == 'connect' and (not proven.is_set() or q.get('params', {}).get('address', '').upper() != address):
                            send(dict(type='result', version=q['version'], sessionId=q['sessionId'], id=q['id'], error={'code':'TEST_TARGET_NOT_ALLOWED'}))
                            continue
                        upstream.sendall(line)
                finally:
                    upstream.shutdown(socket.SHUT_RDWR)
                    thread.join(timeout=2)
                    stream.close()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    with Server(('127.0.0.1', args.port), Handler) as server:
        print('Fixture-only test proxy ready', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    main()
