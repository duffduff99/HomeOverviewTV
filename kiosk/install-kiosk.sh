#!/usr/bin/env bash
# Turn a Raspberry Pi (Raspberry Pi OS Lite, 64-bit, Bookworm or newer) into a
# full-screen House TV display on the HDMI port.
#
#   curl -fsSL https://raw.githubusercontent.com/duffduff99/HomeOverviewTV/main/kiosk/install-kiosk.sh | sudo bash -s -- [options]
#
# Options:
#   --url URL        page to show (default http://localhost:8080)
#   --user NAME      user that runs the display (default: the user who ran sudo, else "pi")
#   --force-1080p    force 1920x1080@60 on HDMI (use if the modulator reports the wrong mode)
#
# What it does: installs Chromium and the tiny "cage" kiosk compositor, sets
# HDMI as the default audio output, and adds a systemd service that starts
# Chromium full screen at boot and restarts it if it ever exits.
# Undo with: sudo systemctl disable --now house-tv-kiosk && sudo systemctl set-default multi-user.target
set -euo pipefail

URL="http://localhost:8080"
KIOSK_USER="${SUDO_USER:-pi}"
FORCE_1080P=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --user) KIOSK_USER="$2"; shift 2 ;;
    --force-1080p) FORCE_1080P=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Please run with sudo." >&2; exit 1; }
id "$KIOSK_USER" >/dev/null 2>&1 || { echo "User $KIOSK_USER does not exist (use --user)." >&2; exit 1; }

echo "==> Installing Chromium and cage"
apt-get update
CHROMIUM_PKG=chromium
apt-cache show chromium >/dev/null 2>&1 || CHROMIUM_PKG=chromium-browser
apt-get install -y --no-install-recommends cage "$CHROMIUM_PKG" fonts-noto-color-emoji alsa-utils curl
CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser)"

usermod -aG video,render,audio,input "$KIOSK_USER"

echo "==> Writing launcher"
cat > /usr/local/bin/house-tv-kiosk <<EOF
#!/usr/bin/env bash
# Wait for the channel server, then open it full screen.
URL="$URL"
for i in \$(seq 1 120); do
  curl -fsS -o /dev/null "\$URL/health" && break
  sleep 2
done
exec "$CHROMIUM_BIN" \\
  --kiosk "\$URL" \\
  --ozone-platform=wayland \\
  --noerrdialogs --disable-infobars --no-first-run --hide-scrollbars \\
  --autoplay-policy=no-user-gesture-required \\
  --disable-features=Translate,MediaRouter \\
  --check-for-update-interval=31536000 \\
  --password-store=basic \\
  --disk-cache-dir=/tmp/house-tv-cache \\
  --enable-gpu-rasterization --ignore-gpu-blocklist
EOF
chmod +x /usr/local/bin/house-tv-kiosk

cat > /etc/pam.d/house-tv-kiosk <<'EOF'
auth     required pam_unix.so nullok
account  required pam_unix.so
session  required pam_unix.so
session  required pam_systemd.so
EOF

echo "==> Installing systemd service"
cat > /etc/systemd/system/house-tv-kiosk.service <<EOF
[Unit]
Description=House TV kiosk display
After=systemd-user-sessions.service network-online.target dbus.socket systemd-logind.service
Wants=network-online.target dbus.socket systemd-logind.service
Conflicts=getty@tty1.service
After=getty@tty1.service

[Service]
Type=simple
User=$KIOSK_USER
PAMName=house-tv-kiosk
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
TTYVTDisallocate=yes
StandardInput=tty-fail
StandardOutput=journal
StandardError=journal
UtmpIdentifier=tty1
UtmpMode=user
Environment=XDG_SESSION_TYPE=wayland
ExecStart=/usr/bin/cage -d -- /usr/local/bin/house-tv-kiosk
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

echo "==> Selecting HDMI audio"
HDMI_CARD="$(aplay -l 2>/dev/null | awk -F'[ :]' '/^card [0-9]+:.*(vc4hdmi|HDMI)/ {print $2; exit}')"
if [[ -n "$HDMI_CARD" ]]; then
  HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
  printf 'defaults.pcm.card %s\ndefaults.ctl.card %s\n' "$HDMI_CARD" "$HDMI_CARD" > "$HOME_DIR/.asoundrc"
  chown "$KIOSK_USER": "$HOME_DIR/.asoundrc"
  echo "    HDMI audio is card $HDMI_CARD"
else
  echo "    Could not find an HDMI audio device; leaving the default." >&2
fi

CMDLINE=/boot/firmware/cmdline.txt
[[ -f $CMDLINE ]] || CMDLINE=/boot/cmdline.txt
if [[ -f $CMDLINE ]]; then
  grep -q consoleblank=0 "$CMDLINE" || sed -i 's/$/ consoleblank=0/' "$CMDLINE"
  if [[ $FORCE_1080P -eq 1 ]] && ! grep -q "video=HDMI-A-1" "$CMDLINE"; then
    sed -i 's/$/ video=HDMI-A-1:1920x1080@60D/' "$CMDLINE"
    echo "    Forced HDMI to 1920x1080@60"
  fi
fi

systemctl daemon-reload
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl enable house-tv-kiosk.service
systemctl set-default graphical.target

echo
echo "Done. Reboot to start the display:  sudo reboot"
echo "Logs:  journalctl -u house-tv-kiosk -f"
