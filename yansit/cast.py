"""Google Cast (Chromecast, Google TV, Android TV) desteği.

Ekran HLS olarak kodlanır, yerel HTTP sunucusundan yayınlanır ve TV'nin
varsayılan medya oynatıcısına adresi gönderilir. Gecikme yaklaşık 3-5 sn.
"""

import os
import shutil
import tempfile
import threading
import time

import pychromecast
import zeroconf
from pychromecast.discovery import CastBrowser, SimpleCastListener

from .devices import Device
from .i18n import _
from .httpserver import PORT, local_ip_for
from .pipeline import Streamer


class CastDiscovery:
    def __init__(self, on_change):
        self.zconf = zeroconf.Zeroconf()
        listener = SimpleCastListener(
            add_callback=lambda *_args: on_change(),
            remove_callback=lambda *_args: on_change(),
            update_callback=lambda *_args: on_change())
        self.browser = CastBrowser(listener, self.zconf)
        self.browser.start_discovery()

    def devices(self):
        result = []
        for uuid, info in list(self.browser.devices.items()):
            if info.cast_type in ("audio", "group"):
                continue  # yalnızca ekranı olan cihazlar
            result.append(Device("cast", str(uuid), info.friendly_name,
                                 info.model_name or "", data=info))
        return result

    def close(self):
        self.browser.stop_discovery()
        self.zconf.close()


class CastSession:
    def __init__(self, device, capture, settings, server, zconf, on_status, on_error):
        self.device = device
        self.server = server
        self.zconf = zconf
        self.on_status = on_status
        self.on_error = on_error
        self.cast = None
        self.stopped = False
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self.dir = tempfile.mkdtemp(prefix="yansit-hls-", dir=runtime)
        self.streamer = Streamer(capture, settings, on_error)

    def start(self):
        self.server.hls_dir = self.dir
        self.streamer.start_hls(self.dir)
        self.on_status(_("Görüntü kodlanıyor…"))
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self):
        try:
            info = self.device.data
            playlist = os.path.join(self.dir, "live.m3u8")
            # TV oynatmaya başlamadan önce çalma listesinde birkaç parça olmalı
            deadline = time.time() + 20
            while not self.stopped and time.time() < deadline:
                try:
                    with open(playlist) as f:
                        if f.read().count("#EXTINF") >= 2:
                            break
                except OSError:
                    pass
                time.sleep(0.3)
            else:
                if not self.stopped:
                    self.on_error(_("Görüntü kodlanamadı (HLS parçası oluşmadı)."))
                return

            self.on_status(_("{name} cihazına bağlanılıyor…", name=info.friendly_name))
            self.cast = pychromecast.get_chromecast_from_cast_info(
                info, self.zconf, tries=2, timeout=10)
            self.cast.wait(timeout=15)
            if self.stopped:
                return
            url = f"http://{local_ip_for(str(info.host))}:{PORT}/hls/live.m3u8"
            mc = self.cast.media_controller
            mc.play_media(url, "application/x-mpegURL", title=_("YANSIT – Ekran"),
                          stream_type="LIVE")
            mc.block_until_active(timeout=20)
            self.on_status(_("{name} üzerinde yansıtılıyor", name=info.friendly_name))
        except Exception as e:  # pychromecast çok çeşitli hata türleri atar
            if not self.stopped:
                self.on_error(_("Google Cast hatası: {error}", error=e))

    def stop(self):
        self.stopped = True
        cast = self.cast
        if cast:
            def quit_cast():
                try:
                    cast.quit_app()
                    cast.disconnect(timeout=5)
                except Exception:
                    pass
            threading.Thread(target=quit_cast, daemon=True).start()
        self.streamer.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
