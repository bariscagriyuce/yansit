"""YANSIT ana penceresi (PySide6).

Qt bu sistemde GLib olay döngüsünü kullandığı için GStreamer, Gio D-Bus
ve GLib zamanlayıcıları doğrudan aynı döngüde çalışır.
"""

import signal
import sys
import time

from gi.repository import GLib
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .capture import ScreenCapture
from .cast import CastDiscovery, CastSession
from .devices import KIND_ORDER
from .dlna import DlnaDiscovery, DlnaSession
from .httpserver import StreamServer
from . import i18n
from .i18n import _
from .miracast import MiracastDiscovery, MiracastSession
from .pipeline import Settings, missing_elements

RESOLUTIONS = [("1080p (1920×1080)", 1920, 1080), ("720p (1280×720)", 1280, 720)]
QUALITIES = [("Yüksek", 10000), ("Normal", 6000), ("Düşük (zayıf Wi-Fi)", 3000)]

KIND_ICONS = {"cast": "video-display", "miracast": "network-wireless", "dlna": "video-television"}


def on_main(fn):
    """Başka iş parçacıklarından gelen geri çağrıları ana döngüye taşır."""
    def wrapper(*args):
        GLib.idle_add(lambda: fn(*args) and False)
    return wrapper


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon.fromTheme("video-display"))
        self.resize(560, 520)

        self.session = None
        self.capture = ScreenCapture()
        self.server = StreamServer(hls_dir="/nonexistent")

        layout = QVBoxLayout(self)
        self.title = QLabel()
        layout.addWidget(self.title)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self.toggle())
        self.list.currentItemChanged.connect(lambda *_args: self.update_buttons())
        layout.addWidget(self.list, 1)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray; font-size: 90%;")
        layout.addWidget(self.hint)

        opts = QHBoxLayout()
        self.res = QComboBox()
        for label, *_size in RESOLUTIONS:
            self.res.addItem(label)
        self.quality = QComboBox()
        for _label in QUALITIES:
            self.quality.addItem("")
        self.quality.setCurrentIndex(1)
        self.audio = QCheckBox()
        self.audio.setChecked(True)
        self.res_label, self.quality_label = QLabel(), QLabel()
        opts.addWidget(self.res_label)
        opts.addWidget(self.res)
        opts.addWidget(self.quality_label)
        opts.addWidget(self.quality)
        opts.addWidget(self.audio)
        opts.addStretch()
        layout.addLayout(opts)

        buttons = QHBoxLayout()
        self.lang_label = QLabel()
        self.lang = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(i18n.language)))
        self.lang.currentIndexChanged.connect(self.change_language)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "")
        self.refresh_btn.clicked.connect(self.rescan)
        self.start_btn = QPushButton(QIcon.fromTheme("media-playback-start"), "")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.toggle)
        buttons.addWidget(self.lang_label)
        buttons.addWidget(self.lang)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch()
        buttons.addWidget(self.start_btn)
        layout.addLayout(buttons)

        self.status = QLabel(_("TV'ler aranıyor…"))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        layout.addWidget(self.log_view)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(300)
        self.refresh_timer.timeout.connect(self.refresh_devices)
        changed = on_main(self.refresh_timer.start)

        self.discoveries = {}
        for kind, factory in (
                ("cast", lambda: CastDiscovery(changed)),
                ("miracast", lambda: MiracastDiscovery(changed, self.log)),
                ("dlna", lambda: DlnaDiscovery(changed))):
            try:
                self.discoveries[kind] = factory()
            except Exception as e:
                self.log(_("{kind} bulma başlatılamadı: {error}", kind=kind, error=e))

        for kind in ("hls", "rtp", "ts"):
            missing = missing_elements(kind)
            if missing:
                self.log(_("Eksik GStreamer öğeleri ({kind}): {elements} – kurulum için "
                           "install.sh'yi çalıştırın.", kind=kind, elements=", ".join(missing)))
        self.retranslate()

    def retranslate(self):
        self.setWindowTitle(_("YANSIT – Ekranı TV'ye Yansıt"))
        self.title.setText("<b>" + _("Bulunan TV'ler") + "</b>")
        self.hint.setText(_("Google TV → Google Cast  ·  Samsung / LG / Roku → Miracast  ·  "
                            "DLNA yalnızca yedek yöntem"))
        self.res_label.setText(_("Çözünürlük:"))
        self.quality_label.setText(_("Kalite:"))
        for i, (label, _bitrate) in enumerate(QUALITIES):
            self.quality.setItemText(i, _(label))
        self.audio.setText(_("Sesi de gönder"))
        self.lang_label.setText(_("Dil:"))
        self.refresh_btn.setText(_("Yeniden Tara"))
        self.update_buttons()

    def change_language(self):
        i18n.set_language(self.lang.currentData())
        self.retranslate()
        if not self.session:
            self.refresh_devices()

    # --- yardımcılar -----------------------------------------------------

    def log(self, msg):
        self.log_view.appendPlainText(f"{time.strftime('%H:%M:%S')}  {msg}")

    def set_status(self, msg, error=False):
        self.status.setText(msg)
        self.status.setStyleSheet("color: #d33; font-weight: bold;" if error else "")
        self.log(msg)

    def refresh_devices(self):
        current = self.list.currentItem()
        selected = current.data(Qt.UserRole).key if current else None
        devices = []
        for d in self.discoveries.values():
            devices += d.devices()
        devices.sort(key=lambda d: (KIND_ORDER[d.kind], d.name.lower()))

        self.list.clear()
        for dev in devices:
            item = QListWidgetItem(QIcon.fromTheme(KIND_ICONS[dev.kind]), dev.label)
            item.setData(Qt.UserRole, dev)
            self.list.addItem(item)
            if dev.key == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        if not self.session:
            self.status.setStyleSheet("")
            self.status.setText(_("{count} cihaz bulundu.", count=len(devices)) if devices else
                                _("TV bulunamadı. TV'nin açık ve aynı ağda olduğundan, "
                                  "Miracast için TV'de 'Ekran Yansıtma' modunun açık "
                                  "olduğundan emin olun."))
        self.update_buttons()

    def rescan(self):
        for d in self.discoveries.values():
            if hasattr(d, "rescan"):
                d.rescan()
        self.set_status(_("Yeniden taranıyor…"))
        QTimer.singleShot(5000, self.refresh_devices)

    def update_buttons(self):
        if self.session:
            self.start_btn.setText(_("Yansıtmayı Durdur"))
            self.start_btn.setIcon(QIcon.fromTheme("media-playback-stop"))
            self.start_btn.setEnabled(True)
        else:
            self.start_btn.setText(_("Yansıtmayı Başlat"))
            self.start_btn.setIcon(QIcon.fromTheme("media-playback-start"))
            self.start_btn.setEnabled(self.list.currentItem() is not None)
        for w in (self.res, self.quality, self.audio, self.list):
            w.setEnabled(self.session is None)

    # --- yansıtma ---------------------------------------------------------

    def toggle(self):
        if self.session:
            self.stop(_("Yansıtma durduruldu."))
        elif self.list.currentItem():
            self.start(self.list.currentItem().data(Qt.UserRole))

    def start(self, dev):
        _, w, h = RESOLUTIONS[self.res.currentIndex()]
        settings = Settings(width=w, height=h, bitrate=QUALITIES[self.quality.currentIndex()][1],
                            audio=self.audio.isChecked())
        self.session = "starting"
        self.update_buttons()
        self.set_status(_("Paylaşılacak ekranı seçin…"))

        def ready():
            if self.session != "starting":
                self.capture.stop()  # bu arada iptal edildi
                return
            status = on_main(self.set_status)
            error = on_main(self.fail)
            ended = on_main(lambda msg: self.stop(msg))
            try:
                if dev.kind == "cast":
                    self.session = CastSession(dev, self.capture, settings, self.server,
                                               self.discoveries["cast"].zconf, status, error)
                elif dev.kind == "miracast":
                    self.session = MiracastSession(dev, self.capture, settings,
                                                   self.discoveries["miracast"],
                                                   status, error, ended)
                else:
                    self.session = DlnaSession(dev, self.capture, settings, self.server,
                                               status, error)
                self.session.start()
            except Exception as e:
                self.fail(str(e))
            self.update_buttons()

        self.capture.start(ready, self.fail)

    def stop(self, msg=None, error=False):
        session, self.session = self.session, None
        if session and session != "starting":
            session.stop()
        self.capture.stop()
        if msg:
            self.set_status(msg, error)
        self.update_buttons()

    def fail(self, msg):
        if self.session:
            self.stop(msg, error=True)
        else:
            self.set_status(msg, error=True)

    def closeEvent(self, event):
        self.stop()
        for d in self.discoveries.values():
            try:
                d.close()
            except Exception:
                pass
        self.server.close()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("yansit")
    app.setDesktopFileName("yansit")
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    # Ctrl+C'nin işlenebilmesi için Python'a düzenli olarak söz ver
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(500)
    win = MainWindow()
    win.show()
    app.aboutToQuit.connect(win.close)
    sys.exit(app.exec())
