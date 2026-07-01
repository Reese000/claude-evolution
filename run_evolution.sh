#!/bin/bash
# Main orchestration script for Claude Evolution System
# This runs the full evolution cycle: analysis -> evolution -> verification

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if evolution is enabled
if ! grep -q "enabled: true" config/settings.yaml; then
    echo "Evolution is disabled in config/settings.yaml"
    exit 0
fi

# Run the Python orchestrator
python3 orchestrate.py

echo ""
echo "Evolution cycle complete. Check data/ directory for logs and reports."
