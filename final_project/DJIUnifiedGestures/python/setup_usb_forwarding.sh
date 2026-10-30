#!/bin/bash
# ==============================================================================
# Setup ADB Port Forwarding for DJIUnified (USB Zero-Latency Mode)
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

echo "Forwarding HTTP Flight Control Port (TCP 8080)..."
adb forward tcp:8080 tcp:8080

echo "Forwarding RTSP Live Video Stream Port (TCP 8554)..."
adb forward tcp:8554 tcp:8554

echo ""
echo "✅ Ports forwarded successfully!"
echo "   - REST Flight API  : http://127.0.0.1:8080"
echo "   - RTSP Live Video  : rtsp://admin:123456@127.0.0.1:8554/streaming/live/1"
echo ""
echo "You can now run:"
echo "   python3 controller.py --host 127.0.0.1"
echo ""
