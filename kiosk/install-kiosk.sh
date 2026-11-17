#!/usr/bin/env bash
# Turn a Raspberry Pi (Raspberry Pi OS Lite, 64-bit) or a small PC running
# Debian 12/13 without a desktop into a full-screen House TV display.
#
#   curl -fsSL https://raw.githubusercontent.com/duffduff99/HomeOverviewTV/main/kiosk/install-kiosk.sh | sudo bash -s -- [options]
#
# Options:
#   --url URL        page to show (default http://localhost:8080)
#   --user NAME      user that runs the display (default: the user who ran sudo, else "pi")
#   --audio WHERE    hdmi (default), analog (3.5 mm / headphone jack) or default (leave as is)
#   --output NAME    video connector to force a mode on: HDMI-A-1 (default), VGA-1, DP-1...
#                    (list them with: ls /sys/class/drm/  -> card0-VGA-1 means VGA-1)
#   --resolution WxH force this mode on --output, e.g. 1280x720 or 1024x768
#   --force-1080p    same as --resolution 1920x1080
#
# Examples:
#   sudo ./install-kiosk.sh                                   # HDMI picture + HDMI sound
#   sudo ./install-kiosk.sh --audio analog                    # VGA or HDMI picture, sound on the 3.5 mm jack
#   sudo ./install-kiosk.sh --audio analog --output VGA-1 --resolution 1280x720
#
# The picture goes to whichever screen is connected. With more than one
# connected, unplug the one you don't use. The page scales to any resolution.
# Running the script again with different options replaces the earlier choice.
#
# What it does: installs Chromium and the tiny "cage" kiosk compositor, sets
# the default audio output, and adds a systemd service that starts Chromium
# full screen at boot and restarts it if it ever exits.
# Undo with: sudo systemctl disable --now house-tv-kiosk && sudo systemctl set-default multi-user.target
set -euo pipefail

URL="http://localhost:8080"
KIOSK_USER="${SUDO_USER:-pi}"
AUDIO=hdmi
OUTPUT=HDMI-A-1
RESOLUTION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --user) KIOSK_USER="$2"; shift 2 ;;
    --audio) AUDIO="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --resolution) RESOLUTION="$2"; shift 2 ;;
    --force-1080p) RESOLUTION=1920x1080; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ $AUDIO =~ ^(hdmi|analog|default)$ ]] || { echo "--audio must be hdmi, analog or default" >&2; exit 1; }
[[ -z $RESOLUTION || $RESOLUTION =~ ^[0-9]+x[0-9]+$ ]] || { echo "--resolution looks like 1280x720" >&2; exit 1; }
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

echo "==> Selecting audio output: $AUDIO"
# Pi: HDMI is its own card (vc4hdmi), the jack is "Headphones".
# Intel/AMD PCs: one card with several devices, e.g. "device 0: ... Analog"
# for the jack and "device 3: HDMI 0" for HDMI.
HOME_DIR="$(getent passwd "$KIOSK_USER" | cut -d: -f6)"
case "$AUDIO" in
  hdmi)   PATTERN='vc4hdmi|HDMI' ;;
  analog) PATTERN='Analog|Headphones' ;;
  *)      PATTERN='' ;;
esac
AUDIO_LINE=""
[[ -n $PATTERN ]] && AUDIO_LINE="$(aplay -l 2>/dev/null | grep -E "^card [0-9]+:.*($PATTERN)" | head -n1 || true)"
if [[ -n "$AUDIO_LINE" ]]; then
  CARD="$(sed -E 's/^card ([0-9]+):.*/\1/' <<<"$AUDIO_LINE")"
  DEV="$(sed -E 's/.*device ([0-9]+):.*/\1/' <<<"$AUDIO_LINE")"
  printf 'defaults.pcm.card %s\ndefaults.pcm.device %s\ndefaults.ctl.card %s\n' "$CARD" "$DEV" "$CARD" > "$HOME_DIR/.asoundrc"
  chown "$KIOSK_USER": "$HOME_DIR/.asoundrc"
  echo "    Using card $CARD, device $DEV: ${AUDIO_LINE#*device $DEV: }"
  echo "    (wrong one? edit $HOME_DIR/.asoundrc using the numbers from 'aplay -l')"
else
  rm -f "$HOME_DIR/.asoundrc"
  [[ $AUDIO == default ]] || echo "    No $AUDIO audio device found; using the system default." >&2
fi
# Make sure the output isn't muted (analog jacks often start muted on PCs).
if [[ -n "${CARD:-}" ]]; then
  for ctl in Master Headphone Speaker PCM; do
    amixer -q -c "$CARD" sset "$ctl" 90% unmute 2>/dev/null || true
  done
  alsactl store 2>/dev/null || true
fi

KARGS="consoleblank=0"
if [[ -n $RESOLUTION ]]; then
  FLAG=D; [[ $OUTPUT == VGA* ]] && FLAG=e   # D = digital (HDMI/DP), e = enable (VGA)
  KARGS="$KARGS video=$OUTPUT:${RESOLUTION}@60$FLAG"
fi
set_kargs() {  # $1 = file, $2 = sed prefix that matches the start of the kernel arguments
  local file="$1" start="$2"
  sed -i -E "s/video=[^ \"]* ?//g" "$file"           # replace any earlier forced mode
  for arg in $KARGS; do
    grep -q "${arg%%=*}=" "$file" || sed -i -E "s/$start/&$arg /" "$file"
  done
}
CMDLINE=/boot/firmware/cmdline.txt
[[ -f $CMDLINE ]] || CMDLINE=/boot/cmdline.txt
if [[ -f $CMDLINE ]]; then                       # Raspberry Pi
  set_kargs "$CMDLINE" '^'
elif [[ -f /etc/default/grub ]]; then            # regular PC
  set_kargs /etc/default/grub '^GRUB_CMDLINE_LINUX_DEFAULT="'
  update-grub >/dev/null 2>&1 || true
fi
[[ -n $RESOLUTION ]] && echo "    Forcing $OUTPUT to ${RESOLUTION}@60"

systemctl daemon-reload
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl enable house-tv-kiosk.service
systemctl set-default graphical.target

echo
echo "Done. Reboot to start the display:  sudo reboot"
echo "Logs:  journalctl -u house-tv-kiosk -f"
