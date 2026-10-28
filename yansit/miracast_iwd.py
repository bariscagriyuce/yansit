"""Miracast cihaz bulma ve Wi-Fi Direct bağlantısı (iwd arka ucu).

iwd'nin P2P D-Bus arayüzüne bilgisayarı "Wi-Fi Display kaynağı" olarak
kaydedip ekran alıcısı (TV) olan eşleri listeliyoruz.

Sınırlama: iwd grup sahibi (GO) olduğunda, ağ yapılandırması NetworkManager'a
bırakıldıysa TV'ye IP dağıtmaz ve bağlantı zaman aşımına uğrar. Samsung gibi
grup sahipliğini kaynağa bırakan TV'lerde bu yüzden wpa_supplicant arka ucu
(miracast_nm.py) gerekir.
"""

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from .devices import Device
from .i18n import _
from .wfd import RTSP_PORT, WfdSource

IWD = "net.connman.iwd"
P2P_DEVICE = "net.connman.iwd.p2p.Device"
P2P_PEER = "net.connman.iwd.p2p.Peer"
P2P_DISPLAY = "net.connman.iwd.p2p.Display"
WSC = "net.connman.iwd.SimpleConfiguration"
SERVICE_MANAGER = "net.connman.iwd.p2p.ServiceManager"


class IwdDiscovery:
    def __init__(self, on_change, on_log):
        self.on_change = on_change
        self.on_log = on_log
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.objects = {}
        self.discovering = set()
        self.problem = None
        self.subs = []
        self.watch = Gio.bus_watch_name_on_connection(
            self.bus, IWD, Gio.BusNameWatcherFlags.NONE, self._appeared, self._vanished)

    def call(self, path, iface, method, args=None, reply=None, timeout=-1, on_done=None):
        def done(bus, res):
            try:
                result = bus.call_finish(res)
                if on_done:
                    on_done(result, None)
            except GLib.Error as e:
                if on_done:
                    on_done(None, e)
        self.bus.call(IWD, path, iface, method, args, reply, Gio.DBusCallFlags.NONE,
                      timeout, None, done)

    def _appeared(self, *_args):
        self.problem = None
        self.subs = [
            self.bus.signal_subscribe(IWD, "org.freedesktop.DBus.ObjectManager", None, "/",
                                      None, Gio.DBusSignalFlags.NONE, self._on_om),
            self.bus.signal_subscribe(IWD, "org.freedesktop.DBus.Properties",
                                      "PropertiesChanged", None, None,
                                      Gio.DBusSignalFlags.NONE, self._on_props),
        ]

        def registered(_res, err):
            if err and "AlreadyExists" not in err.message:
                self.problem = _("Miracast servisi kaydedilemedi: {error}", error=err.message)
                self.on_log(self.problem)

        self.call("/net/connman/iwd", SERVICE_MANAGER, "RegisterDisplayService",
                   GLib.Variant("(a{sv})", ({"Source": GLib.Variant("b", True),
                                             "Port": GLib.Variant("q", RTSP_PORT)},)),
                   on_done=registered)

        def got_objects(res, err):
            if err:
                self.problem = _("iwd okunamadı: {error}", error=err.message)
                return
            self.objects = res.unpack()[0]
            self._start_discovery()
            self.on_change()

        self.call("/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                   on_done=got_objects)

    def _vanished(self, *_args):
        for s in self.subs:
            self.bus.signal_unsubscribe(s)
        self.subs = []
        self.objects = {}
        self.discovering = set()
        self.problem = _("iwd çalışmıyor; Miracast kullanılamaz.")
        self.on_change()

    def _start_discovery(self):
        for path, ifaces in self.objects.items():
            if P2P_DEVICE in ifaces and path not in self.discovering:
                if not ifaces[P2P_DEVICE].get("Enabled"):
                    self.call(path, "org.freedesktop.DBus.Properties", "Set",
                               GLib.Variant("(ssv)", (P2P_DEVICE, "Enabled",
                                                      GLib.Variant("b", True))))

                def done(_res, err, path=path):
                    if err:
                        self.on_log(_("Miracast taraması başlatılamadı: {error}", error=err.message))
                        self.discovering.discard(path)
                self.discovering.add(path)
                self.call(path, P2P_DEVICE, "RequestDiscovery", on_done=done)

    def _on_om(self, _c, _s, _path, _iface, signal, params):
        if signal == "InterfacesAdded":
            path, ifaces = params.unpack()
            self.objects.setdefault(path, {}).update(ifaces)
            if P2P_DEVICE in ifaces:
                self._start_discovery()
        elif signal == "InterfacesRemoved":
            path, names = params.unpack()
            for n in names:
                self.objects.get(path, {}).pop(n, None)
            if not self.objects.get(path):
                self.objects.pop(path, None)
                self.discovering.discard(path)
        self.on_change()

    def _on_props(self, _c, _s, path, _iface, _signal, params):
        iface, changed, invalidated = params.unpack()
        if path in self.objects and iface in self.objects[path]:
            props = self.objects[path][iface]
            props.update(changed)
            for k in invalidated:
                props.pop(k, None)
            if iface in (P2P_PEER, P2P_DISPLAY):
                self.on_change()

    def rescan(self):
        # Taramayı yeniden başlatmak, eşlerin daha hızlı görünmesini sağlar
        for path in list(self.discovering):
            self.call(path, P2P_DEVICE, "ReleaseDiscovery")
        self.discovering = set()
        self._start_discovery()

    def devices(self):
        result = []
        for path, ifaces in self.objects.items():
            peer, display = ifaces.get(P2P_PEER), ifaces.get(P2P_DISPLAY)
            if peer and display and display.get("Sink"):
                result.append(Device("miracast", path, peer.get("Name") or path.rsplit("/", 1)[-1],
                                     peer.get("DeviceSubcategory", ""), data=path))
        return result

    def new_session(self, device, capture, settings, on_status, on_error, on_ended):
        return IwdSession(device, capture, settings, self, on_status, on_error, on_ended)

    def peer_props(self, path):
        return self.objects.get(path, {}).get(P2P_PEER, {})

    def close(self):
        for path in self.discovering:
            try:
                self.bus.call_sync(IWD, path, P2P_DEVICE, "ReleaseDiscovery", None, None,
                                   Gio.DBusCallFlags.NONE, 2000, None)
            except GLib.Error:
                pass
        try:
            self.bus.call_sync(IWD, "/net/connman/iwd", SERVICE_MANAGER,
                               "UnregisterDisplayService", None, None,
                               Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            pass
        Gio.bus_unwatch_name(self.watch)


class IwdSession:
    def __init__(self, device, capture, settings, discovery, on_status, on_error, on_ended):
        self.device = device
        self.discovery = discovery
        self.on_status = on_status
        self.on_error = on_error
        self.stopped = False
        self.wait_timer = None
        # RTSP sunucusu, TV bağlanmaya çalışmadan önce dinlemede olmalı
        self.rtsp = WfdSource(capture, settings, on_status, on_error, on_ended)

    def start(self):
        if self.discovery.problem:
            raise RuntimeError(self.discovery.problem)
        self.on_status(_("{name}: TV ekranındaki bağlantı isteğini onaylayın…", name=self.device.name))

        def connected(_res, err):
            if self.stopped:
                return
            if err:
                msg = err.message.split(":")[-1].strip() or err.message
                self.on_error(_("Wi-Fi Direct bağlantısı kurulamadı: {error}", error=msg))
                return
            if not self.rtsp.connected:
                self.on_status(_("Wi-Fi Direct bağlandı, TV'nin yayını istemesi bekleniyor…"))
                self.wait_timer = GLib.timeout_add_seconds(25, self._rtsp_timeout)

        self.discovery.call(self.device.data, WSC, "PushButton", timeout=120000,
                             on_done=connected)

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
        self.rtsp.close()
        path = self.device.data
        if self.discovery.peer_props(path).get("Connected"):
            self.discovery.call(path, P2P_PEER, "Disconnect")
        else:
            # Bağlantı hâlâ kuruluyorsa iptal et
            self.discovery.call(path, WSC, "Cancel")
