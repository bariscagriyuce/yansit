#!/usr/bin/env bash
# YANSIT kurulumu: eksik paketler, güvenlik duvarı kuralları ve menü kısayolu.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Gerekli paketler kuruluyor (sudo şifresi istenebilir)"
sudo pacman -S --needed --noconfirm \
    gst-plugins-good gst-plugins-bad gst-plugin-pipewire gst-plugin-va gst-libav \
    python-gobject pyside6 python-pychromecast python-zeroconf \
    xdg-desktop-portal-kde

if command -v ufw >/dev/null; then
    echo "==> ufw: yalnızca yerel ağlar için YANSIT portları açılıyor"
    for net in 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12; do
        sudo ufw allow from "$net" to any port 7236 proto tcp comment "YANSIT Miracast RTSP"
        sudo ufw allow from "$net" to any port 8765 proto tcp comment "YANSIT yayin sunucusu"
        sudo ufw allow from "$net" to any port 50900 proto udp comment "YANSIT DLNA kesif"
        sudo ufw allow from "$net" to any port 5353 proto udp comment "YANSIT mDNS (Google Cast)"
    done
fi

echo "==> Menü kısayolu oluşturuluyor"
mkdir -p "$HOME/.local/share/applications" "$HOME/.local/bin"
cat > "$HOME/.local/bin/yansit" <<EOF
#!/bin/sh
cd "$DIR" && exec python3 -m yansit "\$@"
EOF
chmod +x "$HOME/.local/bin/yansit"
sed "s|@EXEC@|$HOME/.local/bin/yansit|" "$DIR/yansit.desktop.in" \
    > "$HOME/.local/share/applications/yansit.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo
echo "Kurulum tamam. Uygulama menüsünden 'YANSIT' ile ya da 'yansit' komutuyla başlatın."
