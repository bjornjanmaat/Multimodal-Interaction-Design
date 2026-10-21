# DJI Unified Gesture Controller: MediaPipe Thumbs Up/Down

A real-time hand gesture recognition flight system for DJI drones.
Scans the live RTSP drone camera stream using **Google MediaPipe** to recognize gestures:
- **`Closing Hand` (✋ $\rightarrow$ ✊ Open to Closed)**: Commands the drone to move **Forward** by step distance (default: **40cm** = 0.40m, speed mapped from gesture duration).
- **`Opening Hand` (✊ $\rightarrow$ ✋ Closed to Open)**: Commands the drone to move **Backward** by step distance (default: **40cm** = 0.40m, speed mapped from gesture duration).
- **`Thumb_Up` (👍)**: Commands the drone to climb **Up** by step distance (default: **10cm** = 0.10m).
- **`Thumb_Down` (👎)**: Commands the drone to descend **Down** by step distance (default: **10cm** = 0.10m).
- **`Safety Boundary Box` (🛡️)**: Press `[H]` to anchor a safety box around the drone's position. Enforces limits of **±1.0m** (100cm) Forward/Backward and **±30cm** Up/Down altitude (plus ±50cm Lateral). Movements exceeding these limits are automatically blocked! Press `[K]` to clear.
- **`Gaze-Averted Thumb Haptic Buzz` (⚡)**: When the user's gaze is averted from the camera (looking Left, Right, Up, or Down) and performs a thumb gesture (**Thumb Up**, **Thumb Down**, **Thumb Left**, or **Thumb Right**), it triggers the wireless vibration motor via UDP (`10.114.198.176:5005`) with visual haptic feedback on the HUD.
- **`Gaze Tracking` (👀)**: Tracks head pose (yaw/pitch) and iris position in real time using MediaPipe Face Mesh to determine whether the operator is looking straight at the camera or looking away, displayed clearly in the HUD interface.
- **`Rock-Paper-Scissors Duel (Startup Gatekeeper)` (⚔️)**: The application starts in Rock-Paper-Scissors mode. **No flight gestures are recognized** until the duel is completed. Press **`[R]`** on the keyboard to start the **5-second countdown** (`5... 4... 3... 2... 1... SHOOT!`). Players show their move (✊ Rock = `Closed_Fist`, ✋ Paper = `Open_Palm`, ✌️ Scissors = `Victory`). The referee resolves the winner and crowns them pilot with exclusive drone flight gesture control! Press `[R]` anytime for a rematch.
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
| **✊ Closing Hand** | **Move Forward** by **40cm** (dynamic speed mapping based on gesture speed) |
| **✋ Opening Hand** | **Move Backward** by **40cm** (dynamic speed mapping based on gesture speed) |
| **👍 Thumb Up** | **Climb (Move Up)** by **10cm** |
| **👎 Thumb Down** | **Descend (Move Down)** by **10cm** |
| **Neutral / No Hand** | **Hover** in place |
| **`H`** | **Set Default Point**: Anchors Safety Box (Fwd/Bwd ±1.0m, Alt ±30cm, Lat ±50cm) |
| **`K`** | **Clear Default Point**: Disables Safety Box |
| **`M`** | **Toggle Drone Movement** (Live Flight vs Dry Run Mode) |
| **`Spacebar`** | **Emergency Stop (E-Stop)**: Instantly pauses/resumes gesture tracking |
| **`G`** | **Toggle Gesture Control** On / Off (manual keys only) |
| **`I`** | **Toggle Forward / Backward Inversion** on the fly |
| **`W` / `S`** | Manual Forward / Backward (40cm) |
| **`A` / `D`** | Manual Roll Left / Right (30cm) |
| **`U` / `J`** | Manual Altitude Up / Down (10cm) |
| **`Q` / `E`** | Manual Yaw Rotate CCW / CW (30°) |
| **`T`** | Auto-Takeoff |
| **`L`** | Auto-Landing |
| **`C`** | Confirm Landing |
| **`P`** | Capture Photo |
| **`+` / `-`** | Increase / Decrease step distance (+/- 5cm) |
| **`Esc` or `X`** | Exit Application |
