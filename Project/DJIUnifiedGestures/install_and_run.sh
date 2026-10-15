#!/bin/bash
# ==============================================================================
# Install & Launch DJIUnified (Flight Control + Live Streaming) on Android
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
ANDROID_DIR="$DIR/android"
APK_PATH="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
PACKAGE_NAME="com.dji.sampleV5.aircraft"
ACTIVITY_NAME="com.rrc.djiControlServer.MainActivity"

echo "============================================================"
echo "   DJI UNIFIED: FLIGHT CONTROLLER + RTSP VIDEO STREAMING"
echo "============================================================"

echo "Checking ADB connection to Android device..."
DEVICE_COUNT=$(adb devices | grep -v "List of devices" | grep "device$" | wc -l | tr -d ' ')

if [ "$DEVICE_COUNT" -eq 0 ]; then
    echo "⚠️  No Android device detected over ADB."
    echo "Please ensure:"
    echo "  1. Your Android phone / DJI RC is plugged into this Mac via USB."
    echo "  2. USB Debugging is ENABLED in Developer Options."
    echo "  3. Accept the 'Allow USB debugging' prompt on the device screen."
    exit 1
fi

echo "Connected device detected."

if [ ! -f "$APK_PATH" ]; then
    echo "Building APK..."
    (cd "$ANDROID_DIR" && ./gradlew assembleDebug)
fi

echo "Installing APK ($APK_PATH)..."
adb install -r "$APK_PATH"

echo "Forwarding Ports..."
echo "  - Port 8080 (REST Flight Controls)"
adb forward tcp:8080 tcp:8080
echo "  - Port 8554 (RTSP Live Video Stream)"
adb forward tcp:8554 tcp:8554

echo "Launching DJIUnified on device..."
adb shell am start -n "$PACKAGE_NAME/$ACTIVITY_NAME"

echo ""
echo "✅ DJIUnified is installed, running, and forwarded!"
echo ""
echo "Run the controller over USB:"
echo "   python3 python/controller.py --host 127.0.0.1"
echo ""
echo "Or over Wi-Fi (using your phone's Wi-Fi IP):"
echo "   python3 python/controller.py --host <PHONE_IP>"
echo ""
