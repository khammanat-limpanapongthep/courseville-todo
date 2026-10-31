#!/bin/bash
# Stop and remove the background job. Reminders already added are kept.
set -euo pipefail

LABEL="com.guy.courseville-todo"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
echo "Uninstalled."
