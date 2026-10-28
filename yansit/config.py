"""Küçük kalıcı ayar deposu (~/.config/yansit/config.json)."""

import json
import os

PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                    "yansit", "config.json")

_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(PATH) as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def get(key, default=None):
    return _load().get(key, default)


def set(key, value):
    data = _load()
    data[key] = value
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    with open(PATH, "w") as f:
        json.dump(data, f, indent=2)
