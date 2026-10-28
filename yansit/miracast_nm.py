"""Miracast cihaz bulma ve Wi-Fi Direct bağlantısı (NetworkManager + wpa_supplicant).

NetworkManager'ın Wi-Fi P2P aygıtı üzerinden ekran alıcısı olan eşleri bulur
ve bağlantıyı NetworkManager'a kurdurur. Bilgisayar grup sahibi olursa
NetworkManager TV'ye otomatik olarak IP dağıtır ("shared" kipi), bu yüzden
Samsung gibi grup sahipliğini kaynağa bırakan TV'lerde de çalışır.
"""

import getpass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from .devices import Device
from .i18n import _
from .wfd import RTSP_PORT, WfdSource

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_DEVICE = "org.freedesktop.NetworkManager.Device"
NM_P2P_DEVICE = "org.freedesktop.NetworkManager.Device.WifiP2P"
NM_PEER = "org.freedesktop.NetworkManager.WifiP2PPeer"
NM_ACTIVE = "org.freedesktop.NetworkManager.Connection.Active"
PROPS = "org.freedesktop.DBus.Properties"

DEVICE_TYPE_WIFI_P2P = 30
ACTIVE_ACTIVATED = 2
ACTIVE_DEACTIVATED = 4

FIND_SECONDS = 120

# Bizi 7236 portunda RTSP sunan bir WFD kaynağı olarak tanıtan bilgi
# alt öğesi (WFD Device Information, oturum kurulabilir, 200 Mbit/s)
SOURCE_WFD_IES = bytes.fromhex("000006" "0090" "1c44" "00c8")


def p2p_device_path(bus):
    """wpa_supplicant tabanlı NetworkManager P2P aygıtının yolu (yoksa None)."""
    try:
        devices = bus.call_sync(NM, NM_PATH, NM, "GetDevices", None, None,
                                Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    except GLib.Error:
        return None
    for path in devices:
        try:
            props = bus.call_sync(NM, path, PROPS, "GetAll", GLib.Variant("(s)", (NM_DEVICE,)),
                                  None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        except GLib.Error:
            continue
        # iwd arka ucundaki P2P aygıtının adı bir D-Bus yoludur (/net/connman/iwd/0)
        if (props.get("DeviceType") == DEVICE_TYPE_WIFI_P2P
                and not props.get("Interface", "").startswith("/")):
            return path
    return None


def wfd_device_type(ies):
    """WFD IE'lerinden aygıt türü: 0 kaynak, 1 alıcı, 2 ikincil alıcı, 3 çift rol."""
    i = 0
    while i + 3 <= len(ies):
        sub_id, length = ies[i], int.from_bytes(ies[i + 1:i + 3], "big")
        if sub_id == 0 and length >= 2:
            return int.from_bytes(ies[i + 3:i + 5], "big") & 0x03
        i += 3 + length
    return None


class NmDiscovery:
    def __init__(self, device_path, on_change, on_log):
        self.on_change = on_change
        self.on_log = on_log
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.device = device_path
        self.peers = {}
        self.problem = None
        self.subs = [
            self.bus.signal_subscribe(NM, NM_P2P_DEVICE, None, self.device, None,
                                      Gio.DBusSignalFlags.NONE, self._on_device_signal),
            self.bus.signal_subscribe(NM, PROPS, "PropertiesChanged", None, NM_PEER,
                                      Gio.DBusSignalFlags.NONE, self._on_peer_props),
        ]
        try:
            paths = self._get(self.device, NM_P2P_DEVICE, "Peers")
        except GLib.Error:
            paths = []
        for p in paths:
            self._add_peer(p)
        self._find()
        self.find_timer = GLib.timeout_add_seconds(FIND_SECONDS - 10, self._find)

    def call(self, path, iface, method, args=None, on_done=None, timeout=-1):
        def done(bus, res):
            try:
                result = bus.call_finish(res)
                if on_done:
                    on_done(result, None)
            except GLib.Error as e:
                if on_done:
                    on_done(None, e)
        self.bus.call(NM, path, iface, method, args, None, Gio.DBusCallFlags.NONE,
                      timeout, None, done)

    def _get(self, path, iface, prop):
        return self.bus.call_sync(NM, path, PROPS, "Get", GLib.Variant("(ss)", (iface, prop)),
                                  None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]

    def _find(self):
        def done(_res, err):
            if err:
                self.problem = _("Miracast taraması başlatılamadı: {error}", error=err.message)
                self.on_log(self.problem)
            else:
                self.problem = None
        self.call(self.device, NM_P2P_DEVICE, "StartFind",
                  GLib.Variant("(a{sv})", ({"timeout": GLib.Variant("i", FIND_SECONDS)},)),
                  on_done=done)
        return True

    def _add_peer(self, path):
        try:
            props = self.bus.call_sync(NM, path, PROPS, "GetAll", GLib.Variant("(s)", (NM_PEER,)),
                                       None, Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        except GLib.Error:
            return
        self.peers[path] = props
        self.on_change()

    def _on_device_signal(self, _c, _s, _path, _iface, signal, params):
        (peer,) = params.unpack()
        if signal == "PeerAdded":
            self._add_peer(peer)
        elif signal == "PeerRemoved" and self.peers.pop(peer, None) is not None:
            self.on_change()

    def _on_peer_props(self, _c, _s, path, _iface, _signal, params):
        _name, changed, _invalidated = params.unpack()
        if path in self.peers:
            self.peers[path].update(changed)
            if "WfdIEs" in changed or "Name" in changed:
                self.on_change()

    def rescan(self):
        self.call(self.device, NM_P2P_DEVICE, "StopFind", on_done=lambda *_a: self._find())

    def devices(self):
        result = []
        for path, p in self.peers.items():
            if wfd_device_type(bytes(p.get("WfdIEs") or b"")) in (1, 3):
                detail = " ".join(x for x in (p.get("Manufacturer"), p.get("Model")) if x)
                result.append(Device("miracast", path, p.get("Name") or p.get("HwAddress"),
                                     detail, data=path))
        return result

    def new_session(self, device, capture, settings, on_status, on_error, on_ended):
        return NmSession(device, capture, settings, self, on_status, on_error, on_ended)

    def close(self):
        GLib.source_remove(self.find_timer)
        for s in self.subs:
            self.bus.signal_unsubscribe(s)
        try:
            self.bus.call_sync(NM, self.device, NM_P2P_DEVICE, "StopFind", None, None,
                               Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            pass


class NmSession:
    def __init__(self, device, capture, settings, discovery, on_status, on_error, on_ended):
        self.device = device
        self.discovery = discovery
        self.on_status = on_status
        self.on_error = on_error
        self.on_ended = on_ended
        self.stopped = False
        self.active = None
        self.sub = None
        self.wait_timer = None
        # RTSP sunucusu, TV bağlanmaya çalışmadan önce dinlemede olmalı
        self.rtsp = WfdSource(capture, settings, on_status, on_error, on_ended)

    def start(self):
        peer = self.discovery.peers.get(self.device.data, {})
        connection = {
            "connection": {
                "id": GLib.Variant("s", "YANSIT Miracast"),
                "type": GLib.Variant("s", "wifi-p2p"),
                "autoconnect": GLib.Variant("b", False),
                "permissions": GLib.Variant("as", [f"user:{getpass.getuser()}"]),
            },
            "wifi-p2p": {
                "peer": GLib.Variant("s", peer.get("HwAddress", "")),
                "wfd-ies": GLib.Variant("ay", SOURCE_WFD_IES),
            },
            # P2P ağı hiçbir zaman varsayılan yol olmasın; internet ev ağından gitmeye devam eder
            "ipv4": {"method": GLib.Variant("s", "auto"),
                     "never-default": GLib.Variant("b", True)},
            "ipv6": {"method": GLib.Variant("s", "auto"),
                     "never-default": GLib.Variant("b", True),
                     "may-fail": GLib.Variant("b", True)},
        }
        options = {"persist": GLib.Variant("s", "volatile"),
                   "bind-activation": GLib.Variant("s", "dbus-client")}
        self.on_status(_("{name}: TV ekranındaki bağlantı isteğini onaylayın…",
                         name=self.device.name))
        self.discovery.call(
            NM_PATH, NM, "AddAndActivateConnection2",
            GLib.Variant("(a{sa{sv}}ooa{sv})",
                         (connection, self.discovery.device, self.device.data, options)),
            on_done=self._on_added)

    def _on_added(self, res, err):
        if self.stopped:
            if res:
                self.discovery.call(NM_PATH, NM, "DeactivateConnection",
                                    GLib.Variant("(o)", (res.unpack()[1],)))
            return
        if err:
            self.on_error(_("Wi-Fi Direct bağlantısı kurulamadı: {error}",
                            error=err.message.split(":")[-1].strip()))
            return
        self.active = res.unpack()[1]
        self.sub = self.discovery.bus.signal_subscribe(
            NM, NM_ACTIVE, "StateChanged", self.active, None,
            Gio.DBusSignalFlags.NONE, self._on_state)

    def _on_state(self, _c, _s, _path, _iface, _signal, params):
        state, _reason = params.unpack()
        if self.stopped:
            return
        if state == ACTIVE_ACTIVATED and not self.rtsp.connected:
            self.on_status(_("Wi-Fi Direct bağlandı, TV'nin yayını istemesi bekleniyor…"))
            self.wait_timer = GLib.timeout_add_seconds(25, self._rtsp_timeout)
        elif state == ACTIVE_DEACTIVATED:
            self.active = None
            if self.rtsp.connected:
                self.on_ended(_("TV bağlantıyı kapattı."))
            else:
                self.on_error(_("Wi-Fi Direct bağlantısı kurulamadı: {error}",
                                error=_("TV bağlantıyı reddetti ya da zaman aşımı oldu.")))

    def _rtsp_timeout(self):
        self.wait_timer = None
        if not self.rtsp.connected and not self.stopped:
            self.on_error(_("TV bağlandı ama yayını başlatmadı. Güvenlik duvarında TCP {port} "
                            "portunun açık olduğundan emin olun.", port=RTSP_PORT))
        return False

    def stop(self):
        self.stopped = True
        if self.wait_timer:
            GLib.source_remove(self.wait_timer)
            self.wait_timer = None
        if self.sub:
            self.discovery.bus.signal_unsubscribe(self.sub)
            self.sub = None
        self.rtsp.close()
        if self.active:
            self.discovery.call(NM_PATH, NM, "DeactivateConnection",
                                GLib.Variant("(o)", (self.active,)))
            self.active = None
