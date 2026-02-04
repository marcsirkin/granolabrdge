#!/bin/bash
# Uninstall Granola Bridge launchd service

set -e

PLIST_NAME="com.granola-bridge.daemon.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
INSTALL_DIR="$HOME/.granola-bridge"

echo "Uninstalling Granola Bridge..."

# Stop the service if running
if launchctl list | grep -q "granola-bridge"; then
    echo "Stopping service..."
    launchctl unload "$LAUNCH_AGENTS/$PLIST_NAME" 2>/dev/null || true
fi

# Remove plist
if [[ -f "$LAUNCH_AGENTS/$PLIST_NAME" ]]; then
    rm "$LAUNCH_AGENTS/$PLIST_NAME"
    echo "Removed launchd plist"
fi

# Ask about data
echo ""
read -p "Remove configuration and database? (y/N) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [[ -d "$INSTALL_DIR" ]]; then
        rm -rf "$INSTALL_DIR"
        echo "Removed $INSTALL_DIR"
    fi
else
    echo "Keeping data at $INSTALL_DIR"
fi

echo ""
echo "Uninstall complete!"
