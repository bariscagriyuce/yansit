#!/usr/bin/env bash
# NetworkManager'ın Wi-Fi arka ucunu değiştirir.
#   bash tools/wifi-backend.sh wpa_supplicant   # Miracast için önerilen
#   bash tools/wifi-backend.sh iwd              # eski hâline döndür
#
# wpa_supplicant'a geçerken iwd'de kayıtlı Wi-Fi şifreleri NetworkManager
# profillerine taşınır. Geçişten sonra internete bağlanılamazsa betik
# otomatik olarak önceki arka uca geri döner.
set -euo pipefail

target="${1:-wpa_supplicant}"
case "$target" in
    wpa_supplicant|iwd) ;;
    *) echo "Kullanım / Usage: $0 [wpa_supplicant|iwd]"; exit 1 ;;
esac

if [ "$EUID" -ne 0 ]; then
    exec sudo bash "$0" "$@"
fi

conf=/etc/NetworkManager/conf.d/wifi_backend.conf
previous=$(sed -n 's/^wifi.backend=//p' "$conf" 2>/dev/null || true)
previous=${previous:-wpa_supplicant}

if [ "$previous" = "$target" ]; then
    echo "Wi-Fi arka ucu zaten $target. / Wi-Fi backend is already $target."
    exit 0
fi

migrate_iwd_passwords() {
    # /var/lib/iwd/<SSID>.psk → NetworkManager profili (yalnızca şifresi boş olanlara)
    shopt -s nullglob
    for f in /var/lib/iwd/*.psk; do
        name=$(basename "$f" .psk)
        if [[ "$name" == =* ]]; then
            ssid=$(printf '%s' "${name#=}" | xxd -r -p)
        else
            ssid="$name"
        fi
        secret=$(sed -n 's/^Passphrase=//p' "$f" | head -1)
        [ -n "$secret" ] || secret=$(sed -n 's/^PreSharedKey=//p' "$f" | head -1)
        [ -n "$secret" ] || continue
        while IFS=: read -r uuid type; do
            [ "$type" = "802-11-wireless" ] || continue
            [ "$(nmcli -g 802-11-wireless.ssid connection show "$uuid")" = "$ssid" ] || continue
            if [ -z "$(nmcli -s -g 802-11-wireless-security.psk connection show "$uuid")" ]; then
                nmcli connection modify "$uuid" 802-11-wireless-security.psk "$secret"
                echo "  şifre taşındı / password migrated: $ssid"
            fi
        done < <(nmcli -t -f UUID,TYPE connection show)
    done
}

apply_backend() {
    local backend=$1
    printf '[device]\nwifi.backend=%s\n' "$backend" > "$conf"
    if [ "$backend" = wpa_supplicant ]; then
        systemctl disable --now iwd 2>/dev/null || true
        systemctl enable wpa_supplicant 2>/dev/null || true
    else
        systemctl disable --now wpa_supplicant 2>/dev/null || true
        systemctl enable --now iwd
    fi
    systemctl restart NetworkManager
}

wait_online() {
    for _ in $(seq 45); do
        if nmcli -t -f STATE general 2>/dev/null | grep -q '^connected'; then
            return 0
        fi
        sleep 1
    done
    return 1
}

if [ "$target" = wpa_supplicant ]; then
    echo "==> iwd'deki Wi-Fi şifreleri NetworkManager'a taşınıyor"
    migrate_iwd_passwords
    if command -v ufw >/dev/null; then
        echo "==> ufw: Miracast için DHCP/DNS izinleri"
        ufw allow proto udp from any port 68 to any port 67 comment "YANSIT Miracast DHCP"
        ufw allow from 10.42.0.0/16 to any port 53 comment "YANSIT Miracast DNS"
    fi
fi

echo "==> Wi-Fi arka ucu: $previous → $target (Wi-Fi birkaç saniye kesilecek)"
cp -a "$conf" "$conf.yansit-yedek" 2>/dev/null || true
apply_backend "$target"

echo "==> Bağlantı bekleniyor…"
if wait_online; then
    nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device | grep -E 'wifi' || true
    echo "Tamam / Done: Wi-Fi artık $target kullanıyor."
    echo "Geri almak için / To revert: bash $(dirname "$0")/wifi-backend.sh $previous"
else
    echo "!! 45 sn içinde bağlantı kurulamadı, $previous arka ucuna geri dönülüyor."
    apply_backend "$previous"
    wait_online && echo "Önceki hâle dönüldü / Reverted to $previous." || \
        echo "!! Bağlantı yok; KDE ağ simgesinden Wi-Fi'yi elle seçin."
    exit 1
fi
