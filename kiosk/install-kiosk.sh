#!/usr/bin/env bash
# Turn a Raspberry Pi (Raspberry Pi OS Lite, 64-bit) or a small PC running
# Ubuntu Server 24.04+ or Debian 12/13 (no desktop) into a full-screen House TV display.
#
#   curl -fsSL https://raw.githubusercontent.com/duffduff99/HomeOverviewTV/main/kiosk/install-kiosk.sh | sudo bash -s -- [options]
#
# Options:
#   --url URL        page to show (default http://localhost:8080)
#   --user NAME      user that runs the display (default: "kiosk", created if missing:
#                    no password, no sudo, no docker access)
#   --audio WHERE    hdmi (default), analog (3.5 mm / headphone jack) or default (leave as is)
#   --resolution WxH use this mode instead of the screen's preferred one, e.g.
#                    1920x1080 or 1280x720 (set when the display starts, on every
#                    connected output unless --output is given)
#   --force-1080p    same as --resolution 1920x1080
#   --output NAME    only apply --resolution to this output, e.g. HDMI-A-1, DP-1, VGA-1
#                    (the names are logged at each start: journalctl -u house-tv-kiosk)
#   --show-cursor    keep mice/touchpads working (by default they're ignored so no
#                    cursor appears on the TV)
#
# Examples:
#   sudo ./install-kiosk.sh                                   # HDMI picture + HDMI sound
#   sudo ./install-kiosk.sh --audio analog                    # VGA or HDMI picture, sound on the 3.5 mm jack
#   sudo ./install-kiosk.sh --audio analog --resolution 1920x1080
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
KIOSK_USER="kiosk"
AUDIO=hdmi
OUTPUT=""
RESOLUTION=""
SHOW_CURSOR=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --user) KIOSK_USER="$2"; shift 2 ;;
    --audio) AUDIO="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    --resolution) RESOLUTION="$2"; shift 2 ;;
    --force-1080p) RESOLUTION=1920x1080; shift ;;
    --show-cursor) SHOW_CURSOR=1; shift ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ $AUDIO =~ ^(hdmi|analog|default)$ ]] || { echo "--audio must be hdmi, analog or default" >&2; exit 1; }
[[ -z $RESOLUTION || $RESOLUTION =~ ^[0-9]+x[0-9]+$ ]] || { echo "--resolution looks like 1280x720" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "Please run with sudo." >&2; exit 1; }
if ! id "$KIOSK_USER" >/dev/null 2>&1; then
  # A dedicated account for the browser: home folder, but no password (can't log
  # in), no login shell, and not in the sudo or docker groups.
  echo "==> Creating display user '$KIOSK_USER'"
  useradd --create-home --shell /usr/sbin/nologin --comment "House TV display" "$KIOSK_USER"
fi
if id -nG "$KIOSK_USER" | grep -qwE 'sudo|docker|wheel|adm'; then
  echo "Warning: $KIOSK_USER is in an admin group (sudo/docker/wheel/adm). The display" >&2
  echo "         is safer under an unprivileged account (the default 'kiosk')." >&2
fi

OS_ID="$(. /etc/os-release && echo "${ID:-}")"
apt-get update
apt-get install -y --no-install-recommends cage wlr-randr fonts-noto-color-emoji alsa-utils curl ca-certificates gnupg
if [[ $OS_ID == ubuntu && $(dpkg --print-architecture) == amd64 ]]; then
  # Ubuntu's "chromium" package is only a wrapper for the snap, whose sandbox
  # doesn't suit a desktop-less kiosk. Use Google Chrome's regular .deb instead;
  # it keeps itself updated through apt.
  echo "==> Installing Google Chrome and cage (Ubuntu)"
  install -d -m 0755 /etc/apt/keyrings
  curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor --yes -o /etc/apt/keyrings/google-chrome.gpg
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list
  apt-get update
  apt-get install -y google-chrome-stable
  CHROMIUM_BIN="$(command -v google-chrome-stable)"
elif [[ $OS_ID == ubuntu ]]; then
  echo "Ubuntu on $(dpkg --print-architecture) isn't supported (Chrome is x86-only and Ubuntu's Chromium is a snap)." >&2
  echo "Use Raspberry Pi OS or Debian on this machine." >&2
  exit 1
else
  echo "==> Installing Chromium and cage"
  CHROMIUM_PKG=chromium
  apt-cache show chromium >/dev/null 2>&1 || CHROMIUM_PKG=chromium-browser
  apt-get install -y --no-install-recommends "$CHROMIUM_PKG"
  CHROMIUM_BIN="$(command -v chromium || command -v chromium-browser)"
fi

usermod -aG video,render,audio,input "$KIOSK_USER"

echo "==> Writing launcher"
cat > /usr/local/bin/house-tv-kiosk <<EOF
#!/usr/bin/env bash
# Wait for the channel server, then open it full screen.
URL="$URL"
RESOLUTION="$RESOLUTION"
OUTPUT="$OUTPUT"

# Log the outputs and their modes (see them with: journalctl -u house-tv-kiosk)
echo "Display outputs:" >&2
wlr-randr >&2 || echo "(wlr-randr could not list outputs)" >&2

# Screens report a "preferred" mode (some modulators prefer 720p). Override it if asked.
if [ -n "\$RESOLUTION" ]; then
  for out in \${OUTPUT:-\$(wlr-randr 2>/dev/null | awk '/^[^ \t]/ {name=\$1} /Enabled: yes/ {print name}')}; do
    if wlr-randr --output "\$out" --mode "\$RESOLUTION" >&2 \\
       || wlr-randr --output "\$out" --custom-mode "\$RESOLUTION" >&2; then
      echo "Set \$out to \$RESOLUTION" >&2
    else
      echo "Could not set \$out to \$RESOLUTION" >&2
    fi
  done
fi

for i in \$(seq 1 120); do
  curl -fsS -o /dev/null "\$URL/health" && break
  sleep 2
done
exec "$CHROMIUM_BIN" \\
  --kiosk "\$URL" \\
  --ozone-platform=wayland \\
  --noerrdialogs --disable-infobars --no-first-run --no-default-browser-check --hide-scrollbars \\
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
if [[ -n $RESOLUTION && -n $OUTPUT ]]; then   # also for the boot console
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
[[ -n $RESOLUTION ]] && echo "    Display will be set to $RESOLUTION on ${OUTPUT:-every connected output}"

echo "==> Mouse cursor"
RULE=/etc/udev/rules.d/90-house-tv-no-pointer.rules
if [[ $SHOW_CURSOR -eq 1 ]]; then
  echo "# House TV kiosk: pointing devices enabled (--show-cursor)" > "$RULE"
  echo "    Mice and touchpads left enabled (--show-cursor)"
else
  # With no pointing device the kiosk draws no cursor. Wireless keyboard
  # receivers often include a "mouse", so ignore every pointing device.
  cat > "$RULE" <<'EOF'
# House TV kiosk: ignore pointing devices so no cursor appears on the TV.
# Re-run install-kiosk.sh with --show-cursor to use a mouse again.
ACTION=="add|change", SUBSYSTEM=="input", ENV{ID_INPUT_MOUSE}=="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"
ACTION=="add|change", SUBSYSTEM=="input", ENV{ID_INPUT_TOUCHPAD}=="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"
ACTION=="add|change", SUBSYSTEM=="input", ENV{ID_INPUT_TABLET}=="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"
ACTION=="add|change", SUBSYSTEM=="input", ENV{ID_INPUT_POINTINGSTICK}=="1", ENV{LIBINPUT_IGNORE_DEVICE}="1"
EOF
  echo "    Pointing devices ignored, so no cursor is shown (--show-cursor to keep them)"
fi
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true

systemctl daemon-reload
systemctl disable getty@tty1.service >/dev/null 2>&1 || true
systemctl enable house-tv-kiosk.service
systemctl set-default graphical.target

echo
echo "Done. Reboot to start the display:  sudo reboot"
echo "Logs:  journalctl -u house-tv-kiosk -f"
