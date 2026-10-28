"""Miracast arka ucunu seçer.

NetworkManager wpa_supplicant ile çalışıyorsa onun P2P aygıtı kullanılır
(önerilen). Yoksa iwd'nin kendi P2P arayüzüne düşülür.
"""

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio

from .miracast_iwd import IwdDiscovery
from .miracast_nm import NmDiscovery, p2p_device_path


def create_discovery(on_change, on_log):
    path = p2p_device_path(Gio.bus_get_sync(Gio.BusType.SYSTEM, None))
    if path:
        return NmDiscovery(path, on_change, on_log)
    return IwdDiscovery(on_change, on_log)
