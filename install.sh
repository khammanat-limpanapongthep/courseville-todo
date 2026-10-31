#!/bin/bash
# Install (or reinstall) the hourly background job. Safe to run again.
set -euo pipefail

LABEL="com.guy.courseville-todo"
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$DIR/config.json" ]; then
  echo "Missing config.json. Copy config.example.json to config.json and add your iCal URL." >&2
  exit 1
fi

mkdir -p "$DIR/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$DIR/sync.py</string>
  </array>
  <key>StartInterval</key>
  <integer>3600</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$DIR/logs/sync.log</string>
  <key>StandardErrorPath</key>
  <string>$DIR/logs/sync.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. Runs every hour; log: $DIR/logs/sync.log"
