#!/usr/bin/env bash
# Show a calibration test pattern on the kiosk display instead of the channel,
# keeping the kiosk's resolution setting.
#
#   sudo ./kiosk/test-pattern.sh white              # also: black, gray, ramp, bars
#   sudo ./kiosk/test-pattern.sh off                # back to the channel
#   sudo ./kiosk/test-pattern.sh white --for 120    # white for 2 minutes, then the
#                                                   # channel, without restarting
#
# --for is for modulators that auto-calibrate when they detect a VGA signal
# (e.g. ZeeVee ZvPro): start the white pattern, re-plug the VGA cable so it
# calibrates on white, and the channel comes back by itself without changing
# the video mode, so the modulator doesn't recalibrate on the channel.
#
# Needs the kiosk installed with a recent install-kiosk.sh, and the House TV
# server running.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Please run with sudo." >&2; exit 1; }
LAUNCHER=/usr/local/bin/house-tv-kiosk
DROPIN_DIR=/etc/systemd/system/house-tv-kiosk.service.d
DROPIN="$DROPIN_DIR/test-pattern.conf"

[[ -f $LAUNCHER ]] || { echo "The kiosk isn't installed (run install-kiosk.sh first)." >&2; exit 1; }
grep -q HOUSE_TV_URL "$LAUNCHER" || {
  echo "Your kiosk was installed with an older install-kiosk.sh. Re-run it (with the same options) first." >&2
  exit 1
}

PATTERN="${1:-}"
FOR=""
if [[ ${2:-} == --for ]]; then
  FOR="${3:-}"
  [[ $FOR =~ ^[0-9]+$ && $FOR -gt 0 ]] || { echo "--for needs a number of seconds" >&2; exit 1; }
fi

case "$PATTERN" in
  white|black|gray|ramp|bars)
    # The channel's address, as given to install-kiosk.sh (--url)
    BASE="$(sed -n 's/^BASE="\(.*\)"$/\1/p' "$LAUNCHER")"
    BASE="${BASE:-http://localhost:8080}"
    QUERY=""
    [[ -n $FOR ]] && QUERY="?after=$FOR"
    mkdir -p "$DROPIN_DIR"
    printf '[Service]\nEnvironment="HOUSE_TV_URL=%s/static/pattern.html%s#%s"\n' "$BASE" "$QUERY" "$PATTERN" > "$DROPIN"
    systemctl daemon-reload
    systemctl restart house-tv-kiosk
    if [[ -n $FOR ]]; then
      # Only this run shows the pattern; the next restart or reboot shows the channel.
      rm -f "$DROPIN"
      systemctl daemon-reload
      echo "Showing $PATTERN for $FOR seconds, then the channel (no restart in between)."
    else
      echo "Showing the $PATTERN pattern. Run '$0 off' to go back to the channel."
    fi
    ;;
  off)
    if [[ -f $DROPIN ]]; then rm -f "$DROPIN"; fi
    systemctl daemon-reload
    systemctl restart house-tv-kiosk
    echo "Back to the channel."
    ;;
  *)
    echo "Usage: sudo $0 white|black|gray|ramp|bars [--for SECONDS]" >&2
    echo "       sudo $0 off" >&2
    exit 1
    ;;
esac
