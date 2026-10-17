# DJI Unified Gesture Controller: MediaPipe Thumbs Up/Down

A real-time hand gesture recognition flight system for DJI drones.
Scans the live RTSP drone camera stream using **Google MediaPipe** to recognize gestures:
- **`Closing Hand` (✋ $\rightarrow$ ✊ Open to Closed)**: Commands the drone to move **Forward** by step distance (default: 10cm).
- **`Opening Hand` (✊ $\rightarrow$ ✋ Closed to Open)**: Commands the drone to move **Backward** by step distance (default: 10cm).
- **`Thumb_Up` (👍)**: Commands the drone to climb **Up** by step distance (default: 10cm).
- **`Thumb_Down` (👎)**: Commands the drone to descend **Down** by step distance (default: 10cm).
- **`No Hand / Neutral`**: Drone hovers safely in place.
- **`Spacebar`**: Emergency Stop (E-Stop) toggle to immediately pause/resume gesture control.

---

## Directory Structure

```
DJIUnifiedGestures/
├── android/                 # Android MSDK v5 REST server (8080) + RTSP Streamer (8554)
│   ├── app/
│   └── build.gradle
├── python/                  # MediaPipe Gesture Recognition & Flight Controller
│   ├── gesture_controller.py # Real-time RTSP Stream Scanner + Gesture Flight HUD
│   ├── DJIControlClient.py   # HTTP REST Client & Simulator Mock for DJI Flight Control
│   ├── gesture_recognizer.task # Pre-trained MediaPipe Gesture Model
│   ├── run_simulator.sh      # Launch simulator with laptop camera (no drone needed)
│   ├── run.sh                # Launcher using 'myenv' virtual environment
│   ├── setup_usb_forwarding.sh
│   └── requirements.txt
├── install_and_run.sh       # Android installation & port forwarding script
└── README.md
```

---

## Quickstart

### Option A: Simulator Mode (No Drone Needed - Laptop Camera)
Test gestures and simulated drone flight using your Mac's built-in camera:
```bash
cd DJIUnifiedGestures/python
./run_simulator.sh
```

---

### Option B: Connect to Physical Drone

#### 1. Launch the Android App
Ensure your Android phone running `DJIUnifiedGestures` is connected to your drone and your local Wi-Fi (or USB).
To install/launch via USB:
```bash
cd DJIUnifiedGestures
./install_and_run.sh
```

---

#### 2. Run the Gesture Controller (using `myenv`)

#### Over Wi-Fi:
Use your phone's Wi-Fi IP (shown at the top of the app, e.g. `192.168.2.8`):
```bash
cd DJIUnifiedGestures/python
./run.sh --host 192.168.2.8
```

#### Over USB:
```bash
cd DJIUnifiedGestures/python
./setup_usb_forwarding.sh
./run.sh --host 127.0.0.1
```

*(Note: `./run.sh` automatically uses the virtual environment at `/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/myenv/bin/python`)*

---

## Controls & Gestures

| Gesture / Key | Action |
|---|---|
| **👍 Thumb Up** | **Climb (Move Up)** by step distance (default 10cm) |
| **👎 Thumb Down** | **Descend (Move Down)** by step distance (default 10cm) |
| **Neutral / No Hand** | **Hover** in place |
| **`Spacebar`** | **Emergency Stop (E-Stop)**: Instantly pauses/resumes gesture tracking |
| **`G`** | **Toggle Gesture Control** On / Off (manual keys only) |
| **`W` / `S`** | Manual Pitch Forward / Backward |
| **`A` / `D`** | Manual Roll Left / Right |
| **`U` / `J`** | Manual Altitude Up / Down |
| **`Q` / `E`** | Manual Yaw Rotate CCW / CW |
| **`T`** | Auto-Takeoff |
| **`L`** | Auto-Landing |
| **`C`** | Confirm Landing |
| **`P`** | Capture Photo |
| **`+` / `-`** | Increase / Decrease step distance (+/- 5cm) |
| **`Esc` or `X`** | Exit Application |
