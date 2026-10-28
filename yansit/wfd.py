"""Wi-Fi Display (Miracast) kaynak tarafı RTSP oturumu.

Wi-Fi Direct bağlantısı kurulduktan sonra TV (alıcı) bilgisayarın 7236
portuna TCP ile bağlanır. Ardından M1-M7 mesajlarıyla yetenekler
karşılaştırılır ve görüntü MPEG-TS/RTP olarak UDP üzerinden gönderilir.
"""

import os
import random
import socket

from gi.repository import GLib

from .i18n import _
from .pipeline import Streamer

RTSP_PORT = 7236
DEBUG = bool(os.environ.get("YANSIT_DEBUG"))
SESSION_TIMEOUT = 30
METHODS = "org.wfa.wfd1.0, SETUP, TEARDOWN, PLAY, PAUSE, GET_PARAMETER, SET_PARAMETER"

# (CEA bit, genişlik, yükseklik, fps, gereken H.264 seviye biti)
# Seviye bitleri: 0x01=3.1 0x02=3.2 0x04=4 0x08=4.1 0x10=4.2
CEA_1080P30 = (7, 1920, 1080, 30, 0x04)
CEA_720P30 = (5, 1280, 720, 30, 0x01)
CEA_720P60 = (6, 1280, 720, 60, 0x02)
CEA_480P60 = (0, 640, 480, 60, 0x01)  # tüm alıcılarda zorunlu


class WfdError(Exception):
    pass


def parse_params(body):
    params = {}
    for line in body.decode(errors="ignore").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            params[k.strip().lower()] = v.strip()
        elif line.strip():
            params[line.strip().lower()] = None
    return params


def choose_video(value, prefer_height):
    """Alıcının wfd_video_formats değerinden uygun bir mod seçer."""
    try:
        parts = value.split()
        codec = " ".join(parts[2:]).split(",")[0].split()
        profiles, level, cea = int(codec[0], 16), int(codec[1], 16), int(codec[2], 16)
    except (ValueError, IndexError, AttributeError):
        profiles, level, cea = 0x01, 0x01, 0x01

    order = [CEA_1080P30, CEA_720P30, CEA_720P60] if prefer_height >= 1080 \
        else [CEA_720P30, CEA_720P60, CEA_1080P30]
    mode = CEA_480P60
    for m in order:
        if cea & (1 << m[0]) and level >= m[4]:
            mode = m
            break

    profile_bit = 0x01 if profiles & 0x01 or not profiles & 0x02 else 0x02
    return mode, profile_bit


class WfdSource:
    def __init__(self, capture, settings, on_status, on_error, on_ended):
        self.capture = capture
        self.settings = settings
        self.on_status = on_status
        self.on_error = on_error
        self.on_ended = on_ended

        self.conn = None
        self.rx = b""
        self.cseq = 0
        self.pending = {}
        self.m1_done = self.m2_done = False
        self.sink = {}
        self.mode = None
        self.profile_bit = 0x01
        self.audio = False
        self.remote_ip = self.local_ip = None
        self.remote_rtp_port = None
        self.local_rtp_port = random.randint(20000, 30000)
        self.session_id = str(random.randint(10000000, 99999999))
        self.streamer = None
        self.watches = []
        self.closed = False

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("0.0.0.0", RTSP_PORT))
        self.server.listen(1)
        self.watches.append(GLib.io_add_watch(
            self.server.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN, self._on_accept))

    @property
    def connected(self):
        return self.conn is not None

    # --- bağlantı ---------------------------------------------------------

    def _on_accept(self, *_args):
        self.conn, addr = self.server.accept()
        self.remote_ip = addr[0]
        self.local_ip = self.conn.getsockname()[0]
        self.server.close()
        self.server = None
        self.on_status(_("TV bağlandı, görüntü ayarları konuşuluyor…"))
        self.watches.append(GLib.io_add_watch(
            self.conn.fileno(), GLib.PRIORITY_DEFAULT,
            GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_readable))
        self._request("OPTIONS", "*", "M1", require=True)
        return False

    def _on_readable(self, _fd, cond):
        try:
            data = b"" if cond & (GLib.IO_HUP | GLib.IO_ERR) else self.conn.recv(65536)
            if not data:
                self._end(_("TV bağlantıyı kapattı."))
                return False
            self.rx += data
            while self._parse_one():
                pass
            return True
        except Exception as e:
            self._fail(_("Miracast protokol hatası: {error}", error=e))
            return False

    def _parse_one(self):
        if b"\r\n\r\n" not in self.rx:
            return False
        head, rest = self.rx.split(b"\r\n\r\n", 1)
        lines = head.decode(errors="ignore").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        length = int(headers.get("content-length", 0))
        if len(rest) < length:
            return False
        body, self.rx = rest[:length], rest[length:]
        if DEBUG:
            print("RTSP <<", head.decode(errors="ignore").replace("\r\n", " | "), "|", body)
        first = lines[0].split(None, 2)
        if first[0].startswith("RTSP/"):
            self._on_response(int(first[1]), headers, body)
        else:
            self._on_request(first[0], first[1], headers, body)
        return True

    # --- gönderme --------------------------------------------------------

    def _send(self, text):
        if DEBUG:
            print("RTSP >>", text.replace("\r\n", " | "))
        self.conn.sendall(text.encode())

    def _request(self, method, url, tag, params=None, require=False):
        self.cseq += 1
        self.pending[self.cseq] = tag
        msg = f"{method} {url} RTSP/1.0\r\nCSeq: {self.cseq}\r\n"
        if require:
            msg += "Require: org.wfa.wfd1.0\r\n"
        body = ""
        if isinstance(params, dict):
            body = "".join(f"{k}: {v}\r\n" for k, v in params.items())
        elif params:
            body = "".join(f"{k}\r\n" for k in params)
        if body:
            msg += f"Content-Type: text/parameters\r\nContent-Length: {len(body)}\r\n"
        self._send(msg + "\r\n" + body)

    def _respond(self, headers, extra=None, status="200 OK"):
        msg = f"RTSP/1.0 {status}\r\nCSeq: {headers.get('cseq', '0')}\r\n"
        for k, v in (extra or {}).items():
            msg += f"{k}: {v}\r\n"
        self._send(msg + "\r\n")

    # --- durum makinesi --------------------------------------------------

    def _on_response(self, status, headers, body):
        tag = self.pending.pop(int(headers.get("cseq", -1)), None)
        if tag == "M16":
            return
        if status != 200 and tag in ("M1", "M3", "M4", "M5"):
            raise WfdError(_("TV {step} adımını reddetti (RTSP {status}).", step=tag, status=status))
        if tag == "M1":
            self.m1_done = True
            self._maybe_m3()
        elif tag == "M3":
            self.sink = parse_params(body)
            self._send_m4()
        elif tag == "M4":
            self._request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "M5",
                          params={"wfd_trigger_method": "SETUP"})

    def _maybe_m3(self):
        if self.m1_done and self.m2_done and "M3" not in self.pending.values() and not self.sink:
            self._request("GET_PARAMETER", "rtsp://localhost/wfd1.0", "M3", params=[
                "wfd_video_formats", "wfd_audio_codecs", "wfd_client_rtp_ports"])

    def _send_m4(self):
        ports = (self.sink.get("wfd_client_rtp_ports") or "").split()
        try:
            self.remote_rtp_port = int(ports[1])
        except (IndexError, ValueError):
            self.remote_rtp_port = 19000
        self.mode, self.profile_bit = choose_video(
            self.sink.get("wfd_video_formats"), self.settings.height)
        cea_bit, *_mode, level = self.mode
        params = {
            "wfd_video_formats": f"00 00 {self.profile_bit:02x} {level:02x} "
                                 f"{1 << cea_bit:08x} 00000000 00000000 00 0000 0000 00 none none",
        }
        audio_caps = self.sink.get("wfd_audio_codecs") or ""
        self.audio = self.settings.audio and "AAC" in audio_caps
        if self.audio:
            params["wfd_audio_codecs"] = "AAC 00000001 00"
        params["wfd_presentation_URL"] = f"rtsp://{self.local_ip}/wfd1.0/streamid=0 none"
        params["wfd_client_rtp_ports"] = f"RTP/AVP/UDP;unicast {self.remote_rtp_port} 0 mode=play"
        self._request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "M4", params=params)

    def _on_request(self, method, url, headers, body):
        session = {"Session": f"{self.session_id};timeout={SESSION_TIMEOUT}"}
        if method == "OPTIONS":
            self._respond(headers, {"Public": METHODS})
            self.m2_done = True
            self._maybe_m3()
        elif method == "SETUP":
            transport = headers.get("transport", "")
            for part in transport.split(";"):
                if part.startswith("client_port="):
                    self.remote_rtp_port = int(part.split("=", 1)[1].split("-")[0])
            self._respond(headers, dict(session, Transport=(
                f"RTP/AVP/UDP;unicast;client_port={self.remote_rtp_port};"
                f"server_port={self.local_rtp_port}")))
        elif method == "PLAY":
            self._respond(headers, session)
            self._play()
        elif method == "PAUSE":
            self._respond(headers, session)
            if self.streamer:
                self.streamer.set_paused(True)
        elif method == "TEARDOWN":
            self._respond(headers, session)
            self._end(_("TV yansıtmayı sonlandırdı."))
        elif method == "SET_PARAMETER":
            self._respond(headers)
            params = parse_params(body)
            if "wfd_idr_request" in params and self.streamer:
                self.streamer.force_keyframe()
        else:  # GET_PARAMETER (canlılık kontrolü) ve diğerleri
            self._respond(headers)

    def _play(self):
        if self.streamer:
            self.streamer.set_paused(False)
            return
        _bit, w, h, fps, _level = self.mode
        s = self.settings
        s.width, s.height, s.fps = w, h, fps
        s.bitrate = min(s.bitrate, 8000 if h >= 1080 else 5000)
        self.streamer = Streamer(self.capture, s, self.on_error)
        profile = "constrained-baseline" if self.profile_bit == 0x01 else "high"
        self.streamer.start_rtp(self.remote_ip, self.remote_rtp_port, self.local_rtp_port,
                                profile=profile, audio=self.audio)
        self.watches.append(GLib.timeout_add_seconds(SESSION_TIMEOUT - 10, self._keepalive))
        sound = _("sesli") if self.audio else _("sessiz")
        self.on_status(_("Miracast ile yansıtılıyor ({w}x{h} {fps} fps, {sound})",
                         w=w, h=h, fps=fps, sound=sound))

    def _keepalive(self):
        if self.conn:
            self._request("GET_PARAMETER", "rtsp://localhost/wfd1.0", "M16")
        return True

    # --- sonlandırma -----------------------------------------------------

    def _fail(self, msg):
        if not self.closed:
            self.close()
            self.on_error(msg)

    def _end(self, msg):
        if not self.closed:
            self.close()
            self.on_ended(msg)

    def close(self):
        if self.closed:
            return
        self.closed = True
        ctx = GLib.MainContext.default()
        for w in self.watches:
            if ctx.find_source_by_id(w):  # kendiliğinden bitmiş olabilir
                GLib.source_remove(w)
        self.watches = []
        if self.streamer:
            self.streamer.stop()
        if self.conn:
            try:
                self._request("SET_PARAMETER", "rtsp://localhost/wfd1.0", "TEARDOWN",
                              params={"wfd_trigger_method": "TEARDOWN"})
            except OSError:
                pass
            self.conn.close()
            self.conn = None
        if self.server:
            self.server.close()
            self.server = None
