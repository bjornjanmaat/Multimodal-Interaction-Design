# DJI Unified: 6DOF Flight Control & Live HD Video Stream

A unified system combining:
1. **Precision 6DOF Flight Controls** (`DJIControlServer` & `DJIControlClient`):
   - Discrete step movement (default 20cm, configurable via `+`/`-`).
   - 6 degrees of freedom: Forward/Back, Left/Right, Up/Down, Yaw rotation.
   - Smooth velocity control mode.
   - Auto-Takeoff, Auto-Landing, and Landing Protection Confirmation.
   - Real-time telemetry (Altitude, Compass Heading, Battery %).
2. **Real-time Live HD Video Streaming** (`Mobile-SDK-Android-V5` & `mac-controller`):
   - Low-latency RTSP live video streaming directly from the drone camera via MSDK v5 `LiveStreamManager`.
   - Dedicated Aviation HUD overlay (Altitude, Heading, Connection, Step distance, Crosshair).

---

## Directory Structure

```
DJIUnified/
├── android/               # Complete MSDK v5 Android Studio Project
│   ├── app/
│   │   ├── build.gradle   # MSDK v5.18.0 & Ktor Embedded Server
│   │   └── src/main/java/com/rrc/djiControlServer/
│   │       ├── MainActivity.kt  # Combined Flight REST API + RTSP Streamer
│   │       └── MApplication.kt
│   └── build.gradle
├── python/                # Mac Python Client & HUD Controller
│   ├── DJIControlClient.py  # Python API Client (Flight + Stream)
│   ├── controller.py        # All-in-one Live Video HUD + Flight Controller
│   ├── interactive_cli.py   # Pure Terminal CLI Flight Controller
│   ├── setup_usb_forwarding.sh
│   └── requirements.txt
└── install_and_run.sh     # One-step build, install, & launch script
```

---

## Quickstart

### 1. Install & Launch the Android App
Plug your Android phone into your Mac via USB and run:
```bash
cd DJIUnified
./install_and_run.sh
```
*(This compiles the app with MSDK v5, installs it on your phone, forwards ports 8080 & 8554, and starts the server).*

---

### 2. Run the Controller on Mac

#### Over Wi-Fi:
Find the phone's Wi-Fi IP address shown at the top of the Android screen (e.g. `192.168.2.8`) and run:
```bash
cd DJIUnified/python
python3 controller.py --host 192.168.2.8
```

#### Over USB (Zero-Latency Mode):
```bash
cd DJIUnified/python
./setup_usb_forwarding.sh
python3 controller.py --host 127.0.0.1
```

---

## Controls

| Key | Action |
|---|---|
| **`W` / `S`** | Move Forward / Backward (by step distance, default 20cm) |
| **`A` / `D`** | Move Left / Right (by step distance) |
| **`U` / `J`** (or `Up` / `Down`) | Move Up / Down (by step distance) |
| **`Q` / `E`** (or `Left` / `Right`) | Rotate Counter-Clockwise / Clockwise (30°) |
| **`T`** or **`Space`** | Initiate Auto-Takeoff |
| **`L`** | Initiate Auto-Landing |
| **`C`** | Confirm Landing |
| **`P`** | Capture Photo |
| **`+` / `-`** | Increase / Decrease step distance (+/- 5cm) |
| **`V`** | Toggle HUD Overlay On / Off |
| **`Esc` or `X`** | Quit Controller |
