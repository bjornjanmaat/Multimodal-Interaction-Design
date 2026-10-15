#!/bin/bash
# ==============================================================================
# Install & Launch DJIControlServer (SDK v5) on Connected Android Device
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
APK_PATH="$DIR/app/build/outputs/apk/debug/app-debug.apk"
PACKAGE_NAME="com.dji.sampleV5.aircraft"
ACTIVITY_NAME="com.rrc.djiControlServer.MainActivity"

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
    (cd "$DIR" && ./gradlew assembleDebug)
fi

echo "Installing APK ($APK_PATH)..."
adb install -r "$APK_PATH"

echo "Forwarding HTTP REST Port (TCP 8080)..."
adb forward tcp:8080 tcp:8080

echo "Launching DJIControlServer on device..."
adb shell am start -n "$PACKAGE_NAME/$ACTIVITY_NAME"

echo ""
echo "✅ DJIControlServer (SDK v5) is installed, running, and forwarded on port 8080!"
echo ""
echo "You can now test the connection with:"
echo "   curl http://127.0.0.1:8080/"
echo ""
echo "Or run the interactive CLI controller:"
echo "   python3 ../DJIControlClient/interactive_control.py"
echo ""
