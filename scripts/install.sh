#!/bin/bash
# Install Granola Bridge as a launchd service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="$HOME/.granola-bridge"
PLIST_NAME="com.granola-bridge.daemon.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

echo "Installing Granola Bridge..."

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$LAUNCH_AGENTS"

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found."
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ $(echo "$PYTHON_VERSION < 3.11" | bc -l) -eq 1 ]]; then
    echo "Error: Python 3.11+ is required, found $PYTHON_VERSION"
    exit 1
fi

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

# Install package
echo "Installing dependencies..."
pip install --upgrade pip
pip install -e "$PROJECT_DIR"

# Copy config if not exists
if [[ ! -f "$INSTALL_DIR/config.yaml" ]]; then
    cp "$PROJECT_DIR/config.yaml.example" "$INSTALL_DIR/config.yaml"
    echo "Created config at $INSTALL_DIR/config.yaml"
    echo "Please edit this file with your settings."
fi

# Copy and configure plist
echo "Installing launchd service..."
PLIST_CONTENT=$(cat "$PROJECT_DIR/launchd/$PLIST_NAME")
PLIST_CONTENT="${PLIST_CONTENT//__INSTALL_DIR__/$INSTALL_DIR}"
PLIST_CONTENT="${PLIST_CONTENT//__HOME__/$HOME}"

echo "$PLIST_CONTENT" > "$LAUNCH_AGENTS/$PLIST_NAME"

echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "1. Edit your config: $INSTALL_DIR/config.yaml"
echo "2. Create .env file with Trello credentials: $PROJECT_DIR/.env"
echo "3. Start the service: launchctl load $LAUNCH_AGENTS/$PLIST_NAME"
echo ""
echo "Useful commands:"
echo "  Start:   launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo "  Stop:    launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
echo "  Logs:    tail -f $INSTALL_DIR/logs/daemon.log"
echo "  Status:  launchctl list | grep granola"
echo ""
echo "Dashboard will be available at: http://localhost:8080"
