#!/bin/bash
# Granola Bridge Launcher
# Double-click this file to start the server on http://localhost:8080

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

echo "Starting Granola Bridge..."
echo "Dashboard: http://localhost:8080"
echo "Press Ctrl+C to stop."
echo ""

source "$PROJECT_DIR/venv/bin/activate"
exec granola-bridge run
