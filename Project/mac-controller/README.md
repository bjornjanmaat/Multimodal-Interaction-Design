# DJI Drone Mac Controller & Live Stream HUD

A complete bridge system that allows you to:
1. **Live stream HD video** from your DJI drone to your Mac with an aviation HUD (Heads-Up Display).
2. **Control the drone** from your Mac using Keyboard or USB/Bluetooth Gamepads (PlayStation, Xbox, Joystick).
3. **Monitor real-time telemetry** (Battery %, Altitude, Heading, Motors state, Flight state).

---

## Architecture Overview

```
 [Mac: controller.py]
      │  ▲
      │  │ (RTSP Video on 8554 & TCP Control/Telemetry on 9090)
      ▼  │
 [Android Phone / DJI Controller running MSDK V5 Bridge]
      │
      │ (DJI OcuSync Radio Link)
      ▼
 [DJI Drone (Mini 3 / Mavic 3 / etc.)]
```

Communication can happen over **Direct USB (via ADB port forwarding - Recommended)** or **Local Wi-Fi**.

---

## Quickstart Guide

### 1. Android App Setup
1. Open the project in **Android Studio**:
   `/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/Project/Mobile-SDK-Android-V5/SampleCode-V5/android-sdk-v5-as`
2. Connect your Android device or DJI RC controller via USB and install/run the **Sample App**.
3. In the app:
   - Tap **Testing Tools** $\rightarrow$ **Aircraft**.
   - Tap **Mac Controller Bridge** (second item, right next to Virtual Stick).
   - Tap **Start Mac Bridge**.
   - Notice the green status: Control Address `192.168.x.x:9090` and RTSP Stream `rtsp://admin:123456@...:8554/streaming/live/1`.

---

### 2. Mac Setup

#### Install Dependencies
Open Terminal on your Mac and navigate to this folder:
```bash
cd "/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/Project/mac-controller"
pip install -r requirements.txt
```

#### Choose Connection Mode:

#### Option A: Over USB (Recommended — Zero-Latency & No Wi-Fi Lag)
Plug your Android device into your Mac via USB and run:
```bash
./setup_usb_forwarding.sh
python3 controller.py --host 127.0.0.1
```

#### Option B: Over Wi-Fi
Make sure your Mac and Android phone are on the same Wi-Fi. Check the IP shown on your Android screen (e.g. `192.168.1.50`) and run:
```bash
python3 controller.py --host 192.168.1.50
```

---

## Controls

### Keyboard Controls
| Key | Action |
|---|---|
| **`W` / `S`** | Pitch Forward / Pitch Backward |
| **`A` / `D`** | Roll Left / Roll Right |
| **`Up` / `Down`** (or `I` / `K`) | Throttle Ascend / Descend |
| **`Left` / `Right`** (or `J` / `L`) | Yaw Rotate Counter-Clockwise / Clockwise |
| **`Space`** | Initiate Auto-Takeoff |
| **`L`** | Initiate Auto-Landing |
| **`E`** | Request Virtual Stick Authority |
| **`X` or `Esc`** | Emergency Hover (Instantly neutralizes all sticks) |
| **`Q`** | Quit Controller Application |

### Gamepad / Joystick Controls
If you plug in or pair an Xbox, PlayStation, or generic USB/Bluetooth controller, it is automatically detected and mapped:
- **Left Stick**: Throttle (Up/Down) & Yaw (Left/Right)
- **Right Stick**: Pitch (Forward/Back) & Roll (Left/Right)

---

## Safety Features
- **Deadman's Watchdog**: The Android app continuously checks for control packets from the Mac. If connection is lost or drops for $> 500\text{ ms}$, the Android app automatically neutralizes the sticks so the drone stops and safely hovers in place.
- **Physical RC Priority**: At any point, moving the physical sticks on the DJI remote controller will override virtual stick inputs.
