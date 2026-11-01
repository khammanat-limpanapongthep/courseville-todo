#!/bin/bash
# Install (or reinstall) the hourly background job. Safe to run again; rerun
# after changing sync.py so the installed copy is refreshed.
#
# macOS blocks launchd jobs from reading ~/Documents, so the script is copied
# to ~/Library/Application Support/courseville-todo and runs from there.
set -euo pipefail

LABEL="com.guy.courseville-todo"
REPO="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/Library/Application Support/courseville-todo"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$DATA/logs" "$HOME/Library/LaunchAgents"

# One-time move of a config.json created inside the repo.
if [ -f "$REPO/config.json" ] && [ ! -f "$DATA/config.json" ]; then
  mv "$REPO/config.json" "$DATA/config.json"
fi
if [ ! -f "$DATA/config.json" ]; then
  echo "Missing $DATA/config.json. Copy config.example.json there and add your iCal URL." >&2
  exit 1
fi

cp "$REPO/sync.py" "$DATA/sync.py"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DATA/sync.py</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$DATA/logs/sync.log</string>
  <key>StandardErrorPath</key>
  <string>$DATA/logs/sync.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. Runs every hour; log: $DATA/logs/sync.log"
