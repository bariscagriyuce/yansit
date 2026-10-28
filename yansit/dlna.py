"""DLNA / UPnP MediaRenderer desteği (Samsung, LG ve çoğu akıllı TV).

Ekran canlı MPEG-TS olarak HTTP'den yayınlanır, TV'ye AVTransport ile
"bu adresi oynat" denir. Yansıtma özelliği olmayan TV'ler için yedek yöntem.
"""

import socket
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

from .devices import Device
from .i18n import _
from .httpserver import DLNA_FEATURES, PORT, local_ip_for
from .pipeline import Streamer

SSDP_ADDR = ("239.255.255.250", 1900)
# Yanıtlar bu sabit porta gelir; güvenlik duvarında yalnızca bu port açılır
SSDP_REPLY_PORT = 50900
RENDERER = "urn:schemas-upnp-org:device:MediaRenderer:1"
AVTRANSPORT = "urn:schemas-upnp-org:service:AVTransport:1"
NS = {"d": "urn:schemas-upnp-org:device-1-0"}


def _fetch_renderer(location):
    with urllib.request.urlopen(location, timeout=4) as r:
        root = ET.fromstring(r.read())
    base = root.findtext("d:URLBase", namespaces=NS) or location
    for dev in root.iter("{urn:schemas-upnp-org:device-1-0}device"):
        for svc in dev.iterfind("d:serviceList/d:service", NS):
            if svc.findtext("d:serviceType", namespaces=NS, default="").startswith(
                    "urn:schemas-upnp-org:service:AVTransport:"):
                control = urljoin(base, svc.findtext("d:controlURL", namespaces=NS))
                return Device(
                    "dlna",
                    dev.findtext("d:UDN", namespaces=NS) or location,
                    dev.findtext("d:friendlyName", namespaces=NS) or "DLNA TV",
                    dev.findtext("d:manufacturer", namespaces=NS) or "",
                    data=control)
    return None


class DlnaDiscovery:
    def __init__(self, on_change):
        self.on_change = on_change
        self.found = {}
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def devices(self):
        return list(self.found.values())

    def rescan(self):
        threading.Thread(target=self._search, daemon=True).start()

    def _loop(self):
        while self.running:
            self._search()
            time.sleep(30)

    def _search(self):
        msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
               f'MAN: "ssdp:discover"\r\nMX: 2\r\nST: {RENDERER}\r\n\r\n').encode()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.settimeout(1)
        locations = set()
        try:
            s.bind(("0.0.0.0", SSDP_REPLY_PORT))
            for _attempt in range(2):
                s.sendto(msg, SSDP_ADDR)
            end = time.time() + 4
            while time.time() < end:
                try:
                    data, _addr = s.recvfrom(4096)
                except socket.timeout:
                    continue
                for line in data.decode(errors="ignore").split("\r\n"):
                    if line.lower().startswith("location:"):
                        locations.add(line.split(":", 1)[1].strip())
        except OSError:
            return
        finally:
            s.close()

        changed = False
        for loc in locations:
            try:
                dev = _fetch_renderer(loc)
            except Exception:
                continue
            if dev and dev.key not in self.found:
                self.found[dev.key] = dev
                changed = True
        if changed:
            self.on_change()

    def close(self):
        self.running = False


def _soap(control_url, action, args):
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
    envelope = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{AVTRANSPORT}">{body}</u:{action}>'
        "</s:Body></s:Envelope>").encode()
    req = urllib.request.Request(control_url, data=envelope, headers={
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPAction": f'"{AVTRANSPORT}#{action}"',
    })
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read()


def _didl(url):
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        f'<item id="0" parentID="-1" restricted="1"><dc:title>{escape(_('YANSIT – Ekran'))}</dc:title>'
        "<upnp:class>object.item.videoItem</upnp:class>"
        f'<res protocolInfo="http-get:*:video/mpeg:{DLNA_FEATURES}">{escape(url)}</res>'
        "</item></DIDL-Lite>")


class DlnaSession:
    def __init__(self, device, capture, settings, server, on_status, on_error):
        self.device = device
        self.server = server
        self.on_status = on_status
        self.on_error = on_error
        self.stopped = False
        self.streamer = Streamer(capture, settings, on_error)

    def start(self):
        self.server.live = True
        self.streamer.start_ts(self.server.broadcaster.push)
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        control = self.device.data
        try:
            host = urlparse(control).hostname
            url = f"http://{local_ip_for(host)}:{PORT}/stream.ts"
            self.on_status(_("{name} cihazına bağlanılıyor…", name=self.device.name))
            try:
                _soap(control, "Stop", {"InstanceID": 0})
            except Exception:
                pass  # zaten duruyor olabilir
            _soap(control, "SetAVTransportURI",
                  {"InstanceID": 0, "CurrentURI": url, "CurrentURIMetaData": _didl(url)})
            _soap(control, "Play", {"InstanceID": 0, "Speed": 1})
            if not self.stopped:
                self.on_status(_("{name} üzerinde oynatılıyor (DLNA)", name=self.device.name))
        except Exception as e:
            if not self.stopped:
                self.on_error(_("DLNA hatası: {error}", error=e))

    def stop(self):
        self.stopped = True
        self.server.live = False
        control = self.device.data

        def stop_tv():
            try:
                _soap(control, "Stop", {"InstanceID": 0})
            except Exception:
                pass
        threading.Thread(target=stop_tv, daemon=True).start()
        self.streamer.stop()
