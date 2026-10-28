"""GStreamer boru hatları: ekranı + sistem sesini H.264/AAC olarak kodlar.

Üç çıkış türü var:
  * rtp  - MPEG-TS/RTP UDP üzerinden (Miracast)
  * ts   - MPEG-TS baytları bir geri çağrıya (DLNA HTTP yayını)
  * hls  - HLS parçaları bir klasöre (Chromecast / Google TV)
"""

import os
from dataclasses import dataclass

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo

from .i18n import _

Gst.init(None)

# Miracast alıcılarının beklediği MPEG-TS PID'leri (WFD spesifikasyonu)
VIDEO_PID = 0x1011
AUDIO_PID = 0x1100

# Test için portal yerine sahte görüntü/ses kaynağı kullan
TEST_SOURCE = bool(os.environ.get("YANSIT_TEST_SOURCE"))


@dataclass
class Settings:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    bitrate: int = 8000  # kbit/s
    audio: bool = True


def has(element):
    return Gst.ElementFactory.find(element) is not None


def missing_elements(kind):
    need = ["videoconvertscale", "videorate", "h264parse", "mpegtsmux", "queue"]
    if kind == "rtp":
        need += ["rtpmp2tpay", "udpsink"]
    elif kind == "hls":
        need += ["hlssink2", "splitmuxsink"]
    else:
        need += ["appsink"]
    return [e for e in need if not has(e)]


def _encoder(s, profile):
    gop = s.fps  # her saniye bir anahtar kare: düşük gecikme ve HLS için şart
    caps = f"video/x-h264,profile={profile}"
    for name in ("vah264lpenc", "vah264enc"):
        if has(name):
            return (f"{name} name=venc rate-control=cbr bitrate={s.bitrate} "
                    f"key-int-max={gop} b-frames=0 ! {caps}")
    if has("x264enc"):
        return (f"x264enc name=venc tune=zerolatency speed-preset=ultrafast "
                f"bitrate={s.bitrate} key-int-max={gop} bframes=0 ! {caps}")
    if has("openh264enc"):
        return (f"openh264enc name=venc bitrate={s.bitrate * 1000} "
                f"gop-size={gop} ! {caps}")
    raise RuntimeError(_("H.264 kodlayıcı bulunamadı (gst-plugin-va veya gst-plugins-ugly kurun)."))


def _video_branch(s, capture, profile):
    if TEST_SOURCE or capture is None:
        src = "videotestsrc is-live=true pattern=ball"
    else:
        src = (f"pipewiresrc fd={capture.pipewire_fd()} path={capture.node_id} "
               f"do-timestamp=true keepalive-time=1000 always-copy=true")
    return (f"{src} ! queue max-size-buffers=3 leaky=downstream "
            f"! videoconvertscale n-threads=0 add-borders=true ! videorate "
            f"! video/x-raw,format=NV12,width={s.width},height={s.height},"
            f"framerate={s.fps}/1,pixel-aspect-ratio=1/1 "
            f"! {_encoder(s, profile)} ! h264parse config-interval=-1")


def _audio_branch():
    if TEST_SOURCE:
        src = "audiotestsrc is-live=true wave=ticks volume=0.3"
    else:
        # Varsayılan hoparlörün "monitör"ünü, yani bilgisayarda çalan sesi yakalar
        src = 'pipewiresrc stream-properties="props,stream.capture.sink=true" do-timestamp=true'
    enc = "fdkaacenc bitrate=128000" if has("fdkaacenc") else "avenc_aac bitrate=128000"
    parse = " ! aacparse" if has("aacparse") else ""
    return (f"{src} ! queue max-size-time=200000000 leaky=downstream "
            f"! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 "
            f"! {enc}{parse}")


class Streamer:
    def __init__(self, capture, settings, on_error):
        self.capture = capture
        self.settings = settings
        self.on_error = on_error
        self.pipeline = None

    def _launch(self, desc):
        self.pipeline = Gst.parse_launch(desc)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self.stop()
            raise RuntimeError(_("Yayın başlatılamadı (GStreamer)."))

    def _on_message(self, _bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print("GStreamer hatası:", err.message, dbg)
            self.on_error(_("Yayın hatası: {error}", error=err.message))

    def _ts_desc(self, profile, audio, sink):
        s = self.settings
        desc = (f"{_video_branch(s, self.capture, profile)} ! queue ! mux.sink_{VIDEO_PID} "
                f"mpegtsmux name=mux alignment=7 ! {sink}")
        if audio:
            desc += f" {_audio_branch()} ! queue ! mux.sink_{AUDIO_PID}"
        return desc

    def start_rtp(self, host, port, bind_port, profile="constrained-baseline", audio=True):
        self._launch(self._ts_desc(
            profile, audio,
            f"rtpmp2tpay pt=33 mtu=1472 ! udpsink host={host} port={port} "
            f"bind-port={bind_port} sync=false async=false"))

    def start_ts(self, on_data, profile="main"):
        self._launch(self._ts_desc(
            profile, self.settings.audio,
            "appsink name=out emit-signals=true sync=false max-buffers=200 drop=true"))

        def on_sample(sink):
            sample = sink.emit("pull-sample")
            buf = sample.get_buffer()
            ok, info = buf.map(Gst.MapFlags.READ)
            if ok:
                on_data(bytes(info.data))
                buf.unmap(info)
            return Gst.FlowReturn.OK

        self.pipeline.get_by_name("out").connect("new-sample", on_sample)

    def start_hls(self, directory):
        s = self.settings
        desc = (f"{_video_branch(s, self.capture, 'main')} ! queue ! hls.video "
                f"hlssink2 name=hls location={directory}/seg%05d.ts "
                f"playlist-location={directory}/live.m3u8 target-duration=1 "
                f"playlist-length=4 max-files=12")
        if s.audio:
            desc += f" {_audio_branch()} ! queue ! hls.audio"
        self._launch(desc)

    def force_keyframe(self):
        enc = self.pipeline and self.pipeline.get_by_name("venc")
        if enc:
            ev = GstVideo.video_event_new_upstream_force_key_unit(Gst.CLOCK_TIME_NONE, True, 0)
            enc.get_static_pad("src").send_event(ev)

    def set_paused(self, paused):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED if paused else Gst.State.PLAYING)

    def stop(self):
        if self.pipeline:
            self.pipeline.get_bus().remove_signal_watch()
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
