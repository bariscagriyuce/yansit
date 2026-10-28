"""TV'lerin yayını çektiği küçük HTTP sunucusu.

  /hls/<dosya>   HLS çalma listesi ve parçaları (Chromecast)
  /stream.ts     Canlı MPEG-TS akışı (DLNA)
"""

import os
import queue
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765

DLNA_FEATURES = ("DLNA.ORG_OP=00;DLNA.ORG_CI=0;"
                 "DLNA.ORG_FLAGS=01700000000000000000000000000000")


class Broadcaster:
    """Canlı TS baytlarını bağlı tüm istemcilere dağıtır."""

    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()

    def push(self, data):
        with self.lock:
            for q in self.clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass  # yavaş istemci: kare atla

    def subscribe(self):
        q = queue.Queue(maxsize=2000)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)


class StreamServer:
    def __init__(self, hls_dir):
        self.hls_dir = hls_dir
        self.broadcaster = Broadcaster()
        self.live = False
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                if os.environ.get("YANSIT_DEBUG"):
                    print("HTTP", self.client_address[0], fmt % args)

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "*")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_HEAD(self):
                self.do_GET(head=True)

            def do_GET(self, head=False):
                path = self.path.split("?", 1)[0]
                if path == "/stream.ts":
                    self._stream(head)
                elif path.startswith("/hls/"):
                    self._file(os.path.basename(path), head)
                else:
                    self.send_error(404)

            def _file(self, name, head):
                full = os.path.join(server.hls_dir, name)
                try:
                    with open(full, "rb") as f:
                        data = f.read()
                except OSError:
                    self.send_error(404)
                    return
                ctype = ("application/vnd.apple.mpegurl" if name.endswith(".m3u8")
                         else "video/mp2t")
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def _stream(self, head):
                if not server.live:
                    self.send_error(503)
                    return
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "video/mpeg")
                self.send_header("transferMode.dlna.org", "Streaming")
                self.send_header("contentFeatures.dlna.org", DLNA_FEATURES)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                if head:
                    return
                q = server.broadcaster.subscribe()
                try:
                    while server.live:
                        try:
                            self.wfile.write(q.get(timeout=2))
                        except queue.Empty:
                            continue
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    server.broadcaster.unsubscribe(q)

        self.httpd = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.live = False
        self.httpd.shutdown()
        self.httpd.server_close()


def local_ip_for(remote_ip):
    """Uzak cihaza giden yolda kullanılan yerel IP adresi."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((remote_ip, 9))
        return s.getsockname()[0]
    finally:
        s.close()
