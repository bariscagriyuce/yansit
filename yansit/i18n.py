"""Arayüz dili (Türkçe / English).

Metinler kodda Türkçe yazılır ve anahtar olarak kullanılır; İngilizce
karşılıkları EN sözlüğündedir. Değişkenler {ad} biçiminde yer tutuculardır.
"""

import os

from . import config

LANGUAGES = {"tr": "Türkçe", "en": "English"}

EN = {
    # Arayüz
    "YANSIT – Ekranı TV'ye Yansıt": "YANSIT – Mirror Your Screen to a TV",
    "Bulunan TV'ler": "Found TVs",
    "Google TV → Google Cast  ·  Samsung / LG / Roku → Miracast  ·  DLNA yalnızca yedek yöntem":
        "Google TV → Google Cast  ·  Samsung / LG / Roku → Miracast  ·  DLNA is only a fallback",
    "Çözünürlük:": "Resolution:",
    "Kalite:": "Quality:",
    "Dil:": "Language:",
    "Yüksek": "High",
    "Normal": "Normal",
    "Düşük (zayıf Wi-Fi)": "Low (weak Wi-Fi)",
    "Sesi de gönder": "Send audio too",
    "Yeniden Tara": "Rescan",
    "Yansıtmayı Başlat": "Start Mirroring",
    "Yansıtmayı Durdur": "Stop Mirroring",
    "TV'ler aranıyor…": "Searching for TVs…",
    "{count} cihaz bulundu.": "{count} device(s) found.",
    "TV bulunamadı. TV'nin açık ve aynı ağda olduğundan, Miracast için TV'de "
    "'Ekran Yansıtma' modunun açık olduğundan emin olun.":
        "No TV found. Make sure the TV is on and on the same network; for Miracast, "
        "turn on the TV's 'Screen Mirroring' mode.",
    "Yeniden taranıyor…": "Rescanning…",
    "Yansıtma durduruldu.": "Mirroring stopped.",
    "Paylaşılacak ekranı seçin…": "Choose the screen to share…",
    "{kind} bulma başlatılamadı: {error}": "Could not start {kind} discovery: {error}",
    "Eksik GStreamer öğeleri ({kind}): {elements} – kurulum için install.sh'yi çalıştırın.":
        "Missing GStreamer elements ({kind}): {elements} – run install.sh to install them.",
    # Ekran yakalama
    "Ekran paylaşımı iptal edildi.": "Screen sharing was cancelled.",
    "Portal ekran paylaşımını reddetti.": "The portal denied screen sharing.",
    "Portal hatası: {error}": "Portal error: {error}",
    "Paylaşılacak ekran seçilmedi.": "No screen was selected for sharing.",
    "PipeWire bağlantısı açılamadı: {error}": "Could not open the PipeWire connection: {error}",
    # Yayın
    "H.264 kodlayıcı bulunamadı (gst-plugin-va veya gst-plugins-ugly kurun).":
        "No H.264 encoder found (install gst-plugin-va or gst-plugins-ugly).",
    "Yayın başlatılamadı (GStreamer).": "Could not start the stream (GStreamer).",
    "Yayın hatası: {error}": "Stream error: {error}",
    "YANSIT – Ekran": "YANSIT – Screen",
    # Google Cast
    "Görüntü kodlanıyor…": "Encoding the picture…",
    "Görüntü kodlanamadı (HLS parçası oluşmadı).": "Could not encode the picture (no HLS segment was produced).",
    "{name} cihazına bağlanılıyor…": "Connecting to {name}…",
    "{name} üzerinde yansıtılıyor": "Mirroring to {name}",
    "Google Cast hatası: {error}": "Google Cast error: {error}",
    # DLNA
    "{name} üzerinde oynatılıyor (DLNA)": "Playing on {name} (DLNA)",
    "DLNA hatası: {error}": "DLNA error: {error}",
    # Miracast
    "Miracast servisi kaydedilemedi: {error}": "Could not register the Miracast service: {error}",
    "iwd okunamadı: {error}": "Could not read iwd: {error}",
    "iwd çalışmıyor; Miracast kullanılamaz.": "iwd is not running; Miracast is unavailable.",
    "Miracast taraması başlatılamadı: {error}": "Could not start the Miracast scan: {error}",
    "{name}: TV ekranındaki bağlantı isteğini onaylayın…":
        "{name}: accept the connection request on the TV screen…",
    "Wi-Fi Direct bağlantısı kurulamadı: {error}": "Wi-Fi Direct connection failed: {error}",
    "TV bağlantıyı reddetti ya da zaman aşımı oldu.":
        "the TV refused the connection or it timed out.",
    "Wi-Fi Direct bağlandı, TV'nin yayını istemesi bekleniyor…":
        "Wi-Fi Direct connected, waiting for the TV to request the stream…",
    "TV bağlandı ama yayını başlatmadı. Güvenlik duvarında TCP {port} portunun açık "
    "olduğundan emin olun.":
        "The TV connected but did not start the stream. Make sure TCP port {port} "
        "is open in the firewall.",
    "TV bağlandı, görüntü ayarları konuşuluyor…": "TV connected, negotiating picture settings…",
    "TV bağlantıyı kapattı.": "The TV closed the connection.",
    "Miracast protokol hatası: {error}": "Miracast protocol error: {error}",
    "TV {step} adımını reddetti (RTSP {status}).": "The TV rejected step {step} (RTSP {status}).",
    "TV yansıtmayı sonlandırdı.": "The TV ended mirroring.",
    "sesli": "with audio",
    "sessiz": "no audio",
    "Miracast ile yansıtılıyor ({w}x{h} {fps} fps, {sound})":
        "Mirroring via Miracast ({w}x{h} {fps} fps, {sound})",
}


def _detect():
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if value:
            return "tr" if value.lower().startswith("tr") else "en"
    return "en"


language = os.environ.get("YANSIT_LANG") or config.get("language") or _detect()


def set_language(code):
    global language
    language = code
    config.set("language", code)


def _(text, **values):
    if language == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text
