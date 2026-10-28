# YANSIT

**[Türkçe](#türkçe) · [English](#english)**

---

## Türkçe

CachyOS / Arch Linux (KDE Plasma, Wayland) ekranını ve sesini kablosuz olarak TV'ye yansıtır.
Arayüz Türkçe ve İngilizce'dir; dil penceredeki **Dil** menüsünden anında değiştirilebilir.

| TV | Yöntem | Gecikme |
|---|---|---|
| Google TV / Android TV / Chromecast | **Google Cast** (ev ağı üzerinden) | ~3–5 sn |
| Samsung, LG, Roku | **Miracast** (Wi-Fi Direct, modem gerekmez) | < 1 sn |
| Yansıtması olmayan akıllı TV'ler | **DLNA** (yedek yöntem) | ~2–5 sn |

### Kurulum

```bash
git clone https://github.com/bariscagriyuce/yansit.git
cd yansit
bash install.sh
```

Betik şunları yapar:
- Eksik GStreamer eklentilerini kurar (özellikle `gst-plugins-good`; Miracast ve Google Cast için gerekli).
- **ufw güvenlik duvarında** yalnızca yerel ağlar için gerekli portları açar (TV'nin bilgisayara
  geri bağlanabilmesi için şart):
  - TCP 7236 – Miracast denetim bağlantısı
  - TCP 8765 – Google Cast / DLNA yayın sunucusu
  - UDP 50900 – DLNA cihaz bulma yanıtları
  - UDP 5353 – mDNS (Google Cast cihaz bulma)
- Uygulama menüsüne **YANSIT** kısayolunu ekler.

> Proje NTFS/exFAT bir diskteyse `./install.sh` "çalıştırılabilir değil" hatası verir;
> bu yüzden `bash install.sh` kullanın.

### Kullanım

1. TV'yi açın.
   - **Samsung:** Kaynak → *Screen Mirroring / Ekran Yansıtma*
   - **LG:** *Screen Share* uygulaması
   - **Roku:** Ayarlar → Sistem → *Screen mirroring* açık olmalı
   - **Google TV:** Ek bir şey gerekmez, sadece aynı Wi-Fi ağında olsun.
2. YANSIT'i açın, listeden TV'yi seçin, **Yansıtmayı Başlat**'a basın.
3. KDE hangi ekranın paylaşılacağını sorar (yalnızca ilk seferde).
4. Miracast'te TV ekranında çıkan bağlantı isteğini kumandayla onaylayın.

Terminalden: `yansit` ya da proje klasöründe `python3 -m yansit`.
Ortam değişkenleri: `YANSIT_LANG=en|tr` (dili zorla), `YANSIT_DEBUG=1` (HTTP günlüğü).

### Miracast ve iwd (Samsung TV'ler için önemli)

CachyOS'ta Wi-Fi varsayılan olarak **iwd** ile çalışır. Samsung gibi bazı TV'ler Wi-Fi Direct
grubunun yönetimini bilgisayara bırakır; iwd bu durumda TV'ye IP adresi vermediği için bağlantı
~20 saniye sonra düşer. Çözüm, NetworkManager'ı **wpa_supplicant** ile çalıştırmaktır:

```bash
bash tools/wifi-backend.sh wpa_supplicant   # geri almak için: bash tools/wifi-backend.sh iwd
```

Betik iwd'de kayıtlı Wi-Fi şifrelerini NetworkManager'a taşır ve 45 saniye içinde internet
gelmezse otomatik olarak geri döner. YANSIT hangi altyapının çalıştığını kendisi algılar.
Google Cast ve DLNA her iki altyapıda da çalışır.

Test edilen TV: **Samsung S90D** – Google Cast, DLNA ve (wpa_supplicant ile) Miracast çalışıyor.
Miracast'te ilk saniyelerde TV küçük pencereden tam ekrana geçerken kısa bir duraklama olur; bu normaldir.
Samsung, Wi-Fi Direct grubuna bazen zamanında katılamaz; YANSIT bu durumda bağlantıyı 4 kereye kadar
kendisi yeniden dener, bu yüzden bağlanmak bazen 1-2 dakika sürebilir.

### Bilinen sınırlamalar

- HDCP korumalı içerik Miracast'te gösterilmez.
- Miracast'te TV ses olarak yalnızca LPCM destekliyorsa görüntü sessiz gönderilir.
- Wi-Fi Direct bağlantısı sırasında normal Wi-Fi hızı bir miktar düşebilir.
- Ses, yansıtma sırasında bilgisayarın hoparlöründe de çalmaya devam eder.

---

## English

Wirelessly mirrors the screen and audio of a CachyOS / Arch Linux (KDE Plasma, Wayland) desktop to a TV.
The interface is available in Turkish and English; switch instantly from the **Language** menu.

| TV | Method | Latency |
|---|---|---|
| Google TV / Android TV / Chromecast | **Google Cast** (over your home network) | ~3–5 s |
| Samsung, LG, Roku | **Miracast** (Wi-Fi Direct, no router needed) | < 1 s |
| Smart TVs without mirroring | **DLNA** (fallback) | ~2–5 s |

### Installation

```bash
git clone https://github.com/bariscagriyuce/yansit.git
cd yansit
bash install.sh
```

The script:
- Installs the missing GStreamer plugins (notably `gst-plugins-good`, required for Miracast and Google Cast).
- Opens the required ports in the **ufw firewall**, for local networks only (the TV must be able
  to connect back to the computer):
  - TCP 7236 – Miracast control connection
  - TCP 8765 – Google Cast / DLNA streaming server
  - UDP 50900 – DLNA discovery replies
  - UDP 5353 – mDNS (Google Cast discovery)
- Adds a **YANSIT** entry to the application menu.

> If the project is on an NTFS/exFAT drive, `./install.sh` fails with "not an executable file";
> use `bash install.sh` instead.

### Usage

1. Turn on the TV.
   - **Samsung:** Source → *Screen Mirroring*
   - **LG:** the *Screen Share* app
   - **Roku:** Settings → System → *Screen mirroring* must be enabled
   - **Google TV:** nothing extra, just be on the same Wi-Fi network.
2. Open YANSIT, pick the TV from the list and press **Start Mirroring**.
3. KDE asks which screen to share (first time only).
4. With Miracast, accept the connection request on the TV with the remote.

From a terminal: `yansit`, or `python3 -m yansit` in the project folder.
Environment variables: `YANSIT_LANG=en|tr` (force a language), `YANSIT_DEBUG=1` (HTTP log).

### Miracast and iwd (important for Samsung TVs)

On CachyOS, Wi-Fi runs on **iwd** by default. Some TVs, such as Samsung, leave Wi-Fi Direct group
ownership to the computer; iwd then does not hand the TV an IP address and the connection drops after
~20 seconds. The fix is to run NetworkManager on **wpa_supplicant**:

```bash
bash tools/wifi-backend.sh wpa_supplicant   # to revert: bash tools/wifi-backend.sh iwd
```

The script migrates Wi-Fi passwords stored in iwd to NetworkManager and rolls back automatically if
there is no connectivity within 45 seconds. YANSIT detects which backend is running. Google Cast and
DLNA work with both.

Tested TV: **Samsung S90D** – Google Cast, DLNA and (with wpa_supplicant) Miracast work.
With Miracast, the TV briefly pauses during the first seconds while it switches from a small window to
full screen; this is normal. Samsung sometimes fails to join the Wi-Fi Direct group in time; YANSIT then
retries the connection up to 4 times by itself, so connecting can occasionally take 1-2 minutes.

### Known limitations

- HDCP-protected content is not shown over Miracast.
- Over Miracast, if the TV only supports LPCM audio, video is sent without sound.
- Regular Wi-Fi throughput may drop somewhat while Wi-Fi Direct is connected.
- Audio keeps playing on the computer's speakers while mirroring.

---

## Technical details / Teknik ayrıntılar

- **Screen capture:** `xdg-desktop-portal` ScreenCast → PipeWire → GStreamer. The selection is remembered
  with a restore token.
- **Encoding:** Intel VA hardware encoder (`vah264lpenc`), falling back to `x264enc`. Audio: monitor of the
  default output → AAC.
- **Miracast:** the Wi-Fi Direct link is set up through NetworkManager's Wi-Fi P2P API (wpa_supplicant), or
  through iwd's P2P D-Bus API as a fallback. YANSIT then runs the WFD RTSP negotiation (M1–M7) and sends
  MPEG-TS over RTP, paced so that frames do not leave the radio in bursts.
- **Google Cast:** HLS segments served over HTTP and played by the TV's default media receiver.
- **DLNA:** live MPEG-TS over HTTP, started with UPnP AVTransport.

| File | Purpose |
|---|---|
| `yansit/app.py` | User interface (PySide6) |
| `yansit/i18n.py` | Translations (Turkish / English) |
| `yansit/capture.py` | Wayland screen capture (portal) |
| `yansit/pipeline.py` | GStreamer encoding pipelines |
| `yansit/cast.py` | Google Cast |
| `yansit/miracast_nm.py`, `yansit/miracast_iwd.py` | Miracast Wi-Fi Direct (NetworkManager / iwd) |
| `yansit/wfd.py` | Miracast WFD RTSP session |
| `tools/wifi-backend.sh` | Switch NetworkManager between wpa_supplicant and iwd |
| `yansit/dlna.py`, `yansit/httpserver.py` | DLNA and the streaming server |

### Requirements / Gereksinimler

Python 3, PySide6, PyGObject, GStreamer 1.22+ (base, good, bad, libav, va, pipewire),
pychromecast, zeroconf, xdg-desktop-portal (KDE) and iwd for Miracast.

## License / Lisans

[MIT](LICENSE) – serbestçe kullanabilir, değiştirebilir ve dağıtabilirsiniz /
free to use, modify and distribute.
