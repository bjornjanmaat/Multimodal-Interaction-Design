# DJI Unified Gestures: Startup & Control Instructions

Step-by-step instructions for running the **MediaPipe Gesture-Controlled Drone System** (`DJIUnifiedGestures`).

---

## Prerequisites

1. **Android Phone**:
   - DJI RC Controller or Android phone connected to your drone (e.g., DJI Mini 3).
   - Drone turned on and linked to the remote controller.
   - Phone and Mac connected to the **same Wi-Fi network** (or Mac connected to phone's Personal Hotspot).

2. **Python Environment**:
   - The pre-configured virtual environment is located at:
     `/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/myenv`

---

## Step 1: Start the Android App

### Option A: App Already Installed on Phone
1. Open the **DJI Control Server** app on your Android phone.
2. Ensure the top status bar shows:
   - **Registered! SDK Version: 5.18.0**
   - **Connected To: [Your Drone Model]**
   - **Control Server IP**: e.g., `192.168.2.8:8080`
   - **RTSP Live Stream**: `rtsp://admin:123456@192.168.2.8:8554/streaming/live/1`
3. Note down your phone's IP address (e.g. `192.168.2.8`).

### Option B: Install or Update via USB
If you need to install or update the app on your phone:
1. Plug your phone into your Mac via USB (USB Debugging enabled).
2. Open Terminal and run:
   ```bash
   cd "/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/Project/DJIUnifiedGestures"
   ./install_and_run.sh
   ```

---

## Step 2: Test Network Connection (Quick Check)

On your Mac, test that your laptop can reach the phone's flight server:
```bash
curl http://<PHONE_IP>:8080/
```
*(Example: `curl http://192.168.2.8:8080/`)*

Expected output:
```text
Connected
```

---

## Step 3: Launch the Gesture Controller

Navigate to the `python/` directory:
```bash
cd "/Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/Project/DJIUnifiedGestures/python"
```

### Mode 0: Local Simulator Mode (No Drone Needed - Laptop Camera)
*Test your hand gestures and virtual drone controls anytime directly using your Mac's built-in webcam. No drone, Android app, or Wi-Fi network required!*
```bash
./run_simulator.sh
```
*(Or run: `./run.sh --sim`)*

---

### Mode 1: Safe Dry-Run Mode (With Real Drone Connected)
*Recognizes gestures from the live camera stream and shows simulated movements without physically flying the drone.*
```bash
./run.sh --host <PHONE_IP> --dry-run
```
*(Example: `./run.sh --host 192.168.2.8 --dry-run`)*

### Mode 2: Live Flight Mode
```bash
./run.sh --host <PHONE_IP>
```
*(Example: `./run.sh --host 192.168.2.8`)*

### Mode 3: Over USB (Zero-Latency / No Wi-Fi)
If your phone is plugged in via USB cable:
```bash
./setup_usb_forwarding.sh
./run.sh --host 127.0.0.1
```

---

## Controls & Gestures

### Hand Gestures (Detected via Drone Camera or Laptop Webcam)

| Gesture | Action | Notes |
|---|---|---|
| **✋ $\rightarrow$ ✊ Closing Hand (Open to Closed)** | **Move Forward** | **Speed-responsive**: Fast snap = Fast flight (~0.75m/s), Slow squeeze = Slow crawl (~0.18m/s) |
| **✊ $\rightarrow$ ✋ Opening Hand (Closed to Open)** | **Move Backward** | **Speed-responsive**: Fast snap = Fast flight (~0.75m/s), Slow open = Slow crawl (~0.18m/s) |
| **👍 Thumb Up** | **Climb / Move Up** | Moves up by step distance (default 10cm) |
| **👎 Thumb Down** | **Descend / Move Down** | Moves down by step distance (default 10cm) |
| **Neutral / No Hand** | **Hover in Place** | Hand steady or out of frame |

> [!TIP]
> **Dynamic Hand Speed Control**:
> - **Fast Snap ($\le 0.20\text{s}$)**: The drone accelerates quickly up to **$0.80\text{ m/s}$** (`[FAST]`).
> - **Normal Pace ($\sim 0.35\text{s}$)**: The drone cruises at **$0.35 - 0.50\text{ m/s}$** (`[NORMAL]`).
> - **Slow Gentle Move ($\ge 0.55\text{s}$)**: The drone creeps at a precision crawl of **$0.15 - 0.25\text{ m/s}$** (`[SLOW]`).

---

### Keyboard Shortcuts (Active in Video Window & Terminal)

| Key | Action | Notes |
|---|---|---|
| **`H`** | **Set Default Point (50cm Safety Box)** | Sets current position as anchor; blocks any movement > 50cm in all directions |
| **`K`** | **Clear Default Point** | Disables the 50cm safety boundary box |
| **`M`** | **Toggle Drone Movement** | Switch between **Dry Run** (simulated) and **Live Flight** |
| **`Space`** | **E-Stop / Pause Gestures** | Instantly freeze gesture commands |
| **`G`** | **Toggle Gesture Tracking** | Switch between gesture control and manual keys only |
| **`T`** | **Auto Takeoff** | Initiates takeoff to ~1.2m hover |
| **`L`** | **Auto Land** | Initiates safe landing |
| **`C`** | **Confirm Landing** | Confirms landing if drone asks |
| **`W` / `S`** | **Move Forward / Backward** | Moves by configured step distance |
| **`A` / `D`** | **Move Left / Right** | Moves by configured step distance |
| **`U` / `J`** | **Move Up / Down** | Manual vertical climb/descend |
| **`Q` / `E`** | **Rotate CCW / CW** | Yaw turn (30°) |
| **`+` / `-`** | **Tune Step Distance** | Increase / decrease distance by +/- 5cm |
| **`P`** | **Take Photo** | Captures still camera shot |
| **`Esc` or `X`** | **Quit Application** | Safely stops video and exits |

---

## Troubleshooting

- **`Connection refused` on port 8080:**
  1. Make sure the Android app is open and in the foreground.
  2. Verify that your Mac and phone are on the exact same Wi-Fi network.
  3. Re-verify the IP address shown on the phone screen.

- **`RTSP Stream Failed to Connect`:**
  - Verify that the drone camera is powered on and streaming.
  - The HUD will show a standby crosshair screen until video packets arrive.

- **Gesture not recognized:**
  - Ensure your hand is clearly visible to the drone camera with adequate lighting.
  - Hold the Thumb Up or Thumb Down steadily for ~0.3 seconds to confirm the gesture.
  - Press `+` or `-` to adjust the climb/descend step size to your preference.
