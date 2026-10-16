#!/bin/bash
# ==============================================================================
# Run DJI Gesture Simulator with Laptop Camera (No Drone Needed)
# ==============================================================================

VENV_PYTHON="/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/myenv/bin/python"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "⚠️  Virtual environment python not found at: $VENV_PYTHON"
    echo "Falling back to system python3..."
    VENV_PYTHON="python3"
fi

echo "================================================================="
echo "  Starting DJI Gesture Simulator using Laptop Webcam"
echo "  Python: $VENV_PYTHON"
echo "================================================================="

exec "$VENV_PYTHON" "$DIR/gesture_controller.py" --sim "$@"
