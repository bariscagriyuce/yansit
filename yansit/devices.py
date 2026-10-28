"""Tüm yöntemlerin ortak cihaz tanımı."""

from dataclasses import dataclass, field

KIND_LABELS = {
    "cast": "Google Cast",
    "miracast": "Miracast",
    "dlna": "DLNA",
}

# Listede gösterim sırası: en güvenilir yöntem önce
KIND_ORDER = {"cast": 0, "miracast": 1, "dlna": 2}


@dataclass
class Device:
    kind: str          # "cast" | "miracast" | "dlna"
    id: str            # yöntem içinde benzersiz kimlik
    name: str
    detail: str = ""   # model / üretici
    data: object = field(default=None, repr=False, compare=False)

    @property
    def key(self):
        return f"{self.kind}:{self.id}"

    @property
    def label(self):
        extra = f"  ({self.detail})" if self.detail else ""
        return f"{self.name}{extra}  ·  {KIND_LABELS[self.kind]}"
