#!/usr/bin/env bash
# Update House TV to the latest version and confirm it's actually running.
#
#   cd ~/house-tv && ./update.sh
#
# Works whether docker-compose.yml uses the published image (image:) or builds
# from source (build: .), keeps your local edits to docker-compose.yml, and
# reminds you if the kiosk scripts changed.
set -euo pipefail

cd "$(dirname "$0")"

# Use sudo for docker unless this user can already talk to it.
DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then DOCKER=(sudo docker); fi
DC=("${DOCKER[@]}" compose)

step() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------- 1. code
step "Getting the latest code"
OLD_REV="$(git rev-parse HEAD)"
STASHED=0
if ! git diff --quiet; then
  # Local edits to tracked files (usually docker-compose.yml): set aside, re-apply after.
  git stash push --quiet --message "update.sh $(date +%F-%T)"
  STASHED=1
fi
if ! git pull --ff-only; then
  [[ $STASHED -eq 1 ]] && git stash pop --quiet || true
  echo "git pull failed; nothing was changed." >&2
  exit 1
fi
if [[ $STASHED -eq 1 ]] && ! git stash pop --quiet; then
  echo "Your local edits clash with the update. They're saved in 'git stash list';" >&2
  echo "re-apply them by hand (e.g. the image:/build: lines in docker-compose.yml)." >&2
  exit 1
fi
NEW_REV="$(git rev-parse HEAD)"
if [[ $OLD_REV == "$NEW_REV" ]]; then
  echo "Already up to date ($(git log -1 --format='%h %s'))."
else
  git log --oneline "$OLD_REV..$NEW_REV" | sed 's/^/    /'
fi

# --------------------------------------------------------------- 2. server
if grep -qE '^[[:space:]]*build:' docker-compose.yml; then
  step "Building the server from source (docker-compose.yml uses build:)"
  "${DC[@]}" build --build-arg "GIT_SHA=$NEW_REV"
else
  step "Downloading the published image (docker-compose.yml uses image:)"
  "${DC[@]}" pull
fi
step "Restarting the server"
"${DC[@]}" up -d --force-recreate

# ---------------------------------------------------------------- 3. check
step "Checking the running version"
PORT="$(sed -nE 's/^[[:space:]]*-[[:space:]]*"?([0-9]+):8080"?.*/\1/p' docker-compose.yml | head -n1)"
PORT="${PORT:-8080}"
HEALTH=""
for _ in $(seq 1 30); do
  HEALTH="$(curl -fsS "http://localhost:$PORT/health" 2>/dev/null || true)"
  [[ -n $HEALTH ]] && break
  sleep 2
done
if [[ -z $HEALTH ]]; then
  echo "The server didn't answer on port $PORT. Check: ${DC[*]} logs --tail 40 house-tv" >&2
  exit 1
fi
RUNNING="$(sed -nE 's/.*"revision": *"([^"]*)".*/\1/p' <<<"$HEALTH")"
if [[ $RUNNING == "$NEW_REV" ]]; then
  echo "Running $(git log -1 --format='%h (%s)' "$NEW_REV"). All good."
elif [[ -z $RUNNING || $RUNNING == unknown ]]; then
  echo "The server is up, but its image doesn't record which version it is"
  echo "(images published before this check was added). The next update will show it."
else
  echo "The server is running ${RUNNING:0:7}, but the code is at ${NEW_REV:0:7}." >&2
  if ! grep -qE '^[[:space:]]*build:' docker-compose.yml; then
    echo "The published image is probably still being built on GitHub (takes a few" >&2
    echo "minutes after a merge). Wait a bit and run ./update.sh again." >&2
  fi
  exit 1
fi
echo "Displays reload the new version by themselves."

# ----------------------------------------------------------------- 4. kiosk
if [[ $OLD_REV != "$NEW_REV" ]] && ! git diff --quiet "$OLD_REV" "$NEW_REV" -- kiosk/install-kiosk.sh; then
  echo
  echo "Note: the kiosk installer changed in this update. Re-run it with the options"
  echo "you normally use to pick up the changes, e.g.:"
  echo "    sudo ./kiosk/install-kiosk.sh --broadcast --audio analog --resolution 1920x1080"
fi
