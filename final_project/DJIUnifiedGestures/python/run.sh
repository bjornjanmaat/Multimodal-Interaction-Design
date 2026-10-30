#!/bin/bash
# ==============================================================================
# Run DJI Unified Gesture Controller using myenv Python
# ==============================================================================

VENV_PYTHON="/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/myenv/bin/python"
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

if [ ! -f "$VENV_PYTHON" ]; then
    echo "⚠️  Virtual environment python not found at: $VENV_PYTHON"
    echo "Falling back to system python3..."
    VENV_PYTHON="python3"
fi

echo "Using Python: $VENV_PYTHON"
exec "$VENV_PYTHON" "$DIR/gesture_controller.py" "$@"
