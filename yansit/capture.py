"""Wayland ekran yakalama: xdg-desktop-portal ScreenCast arayüzü.

Portal, kullanıcıya hangi ekranın paylaşılacağını sorar ve bir PipeWire
düğümü verir. Seçim "restore_token" ile hatırlanır; böylece pencere yalnızca
ilk seferde açılır.
"""

import os
import random

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import config
from .i18n import _

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST = "org.freedesktop.portal.ScreenCast"

SOURCE_MONITOR = 1
SOURCE_WINDOW = 2
CURSOR_EMBEDDED = 2
PERSIST_UNTIL_REVOKED = 2


class ScreenCapture:
    """Portal oturumunu yönetir. start() bittiğinde on_ready() ya da on_error() çağrılır."""

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.session = None
        self.node_id = None
        self.fd = None
        self.size = None

    @property
    def active(self):
        return self.fd is not None

    def _request(self, method, args, on_response, on_error):
        """Portal isteği yapar; sonuç Request.Response sinyaliyle gelir."""
        token = f"yansit_{random.randint(0, 1 << 30)}"
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        handle = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        sub = [0]

        def on_signal(conn, _sender, _path, _iface, _signal, params):
            conn.signal_unsubscribe(sub[0])
            code, results = params.unpack()
            if code == 0:
                on_response(results)
            elif code == 1:
                on_error(_("Ekran paylaşımı iptal edildi."))
            else:
                on_error(_("Portal ekran paylaşımını reddetti."))

        sub[0] = self.bus.signal_subscribe(
            PORTAL, "org.freedesktop.portal.Request", "Response", handle, None,
            Gio.DBusSignalFlags.NO_MATCH_RULE, on_signal)

        options = dict(args[-1])
        options["handle_token"] = GLib.Variant("s", token)
        args = list(args[:-1]) + [options]

        def on_done(bus, res):
            try:
                bus.call_finish(res)
            except GLib.Error as e:
                self.bus.signal_unsubscribe(sub[0])
                on_error(_("Portal hatası: {error}", error=e.message))

        self.bus.call(PORTAL, PORTAL_PATH, SCREENCAST, method,
                      GLib.Variant(_signature(method), tuple(args)), None,
                      Gio.DBusCallFlags.NONE, -1, None, on_done)

    def start(self, on_ready, on_error):
        if self.active:
            on_ready()
            return

        def created(results):
            self.session = results["session_handle"]
            opts = {
                "types": GLib.Variant("u", SOURCE_MONITOR | SOURCE_WINDOW),
                "multiple": GLib.Variant("b", False),
                "cursor_mode": GLib.Variant("u", CURSOR_EMBEDDED),
                "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
            }
            token = config.get("restore_token")
            if token:
                opts["restore_token"] = GLib.Variant("s", token)
            self._request("SelectSources", [self.session, opts], selected, on_error)

        def selected(_results):
            self._request("Start", [self.session, "", {}], started, on_error)

        def started(results):
            streams = results.get("streams") or []
            if not streams:
                on_error(_("Paylaşılacak ekran seçilmedi."))
                return
            if results.get("restore_token"):
                config.set("restore_token", results["restore_token"])
            self.node_id, props = streams[0]
            self.size = props.get("size")
            try:
                ret, fds = self.bus.call_with_unix_fd_list_sync(
                    PORTAL, PORTAL_PATH, SCREENCAST, "OpenPipeWireRemote",
                    GLib.Variant("(oa{sv})", (self.session, {})),
                    GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None)
                self.fd = fds.get(ret.unpack()[0])
            except GLib.Error as e:
                on_error(_("PipeWire bağlantısı açılamadı: {error}", error=e.message))
                return
            on_ready()

        def create_error(msg):
            # Eski bir restore_token reddedilmiş olabilir; bir sonraki denemede sıfırdan sor
            config.set("restore_token", None)
            on_error(msg)

        self._request("CreateSession",
                      [{"session_handle_token": GLib.Variant("s", "yansit_session")}],
                      created, create_error)

    def pipewire_fd(self):
        """GStreamer'a verilecek kopya fd (her boru hattı kendi kopyasını kapatır)."""
        return os.dup(self.fd)

    def stop(self):
        if self.session:
            try:
                self.bus.call_sync(PORTAL, self.session, "org.freedesktop.portal.Session",
                                   "Close", None, None, Gio.DBusCallFlags.NONE, -1, None)
            except GLib.Error:
                pass
        if self.fd is not None:
            os.close(self.fd)
        self.session = self.node_id = self.fd = None


def _signature(method):
    return {
        "CreateSession": "(a{sv})",
        "SelectSources": "(oa{sv})",
        "Start": "(osa{sv})",
    }[method]
