#!/bin/bash
echo "Starting ENTIENT Worker..."
echo "Press Ctrl+C to stop."
echo ""
source .venv/bin/activate
python worker.py "$@"
