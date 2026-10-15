#!/bin/bash
# ==============================================================================
# Setup ADB Port Forwarding for Zero-Latency USB Mac <-> DJI Drone Connection
# ==============================================================================

echo "Checking ADB connection to Android device..."
DEVICE_COUNT=$(adb devices | grep -v "List of devices" | grep "device$" | wc -l | tr -d ' ')

if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "⚠️  No Android device detected over ADB."
    echo "Please ensure:"
    echo "  1. Your Android phone / DJI RC is plugged into this Mac via USB."
    echo "  2. USB Debugging is ENABLED in Developer Options on Android."
    echo "  3. You accepted the 'Allow USB debugging' prompt on the device screen."
    exit 1
fi

echo "Forwarding Control Port (TCP 9090)..."
adb forward tcp:9090 tcp:9090

echo "Forwarding RTSP Video Port (TCP 8554)..."
adb forward tcp:8554 tcp:8554

echo ""
echo "✅ Ports forwarded successfully!"
echo "   - Control Socket : localhost:9090"
echo "   - RTSP Stream    : rtsp://admin:123456@localhost:8554/streaming/live/1"
echo ""
echo "You can now run:"
echo "   python3 controller.py --host 127.0.0.1"
