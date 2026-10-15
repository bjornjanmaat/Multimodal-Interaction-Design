#!/usr/bin/env python3
"""
DJI Unified Gesture Controller & Live Stream HUD
=================================================
Recognizes hand gestures (Thumbs Up / Thumbs Down) from the drone's live camera
stream using Google MediaPipe to command drone vertical motion (Climb / Descend).

Controls:
  - Thumbs Up (👍)    -> Drone climbs (Up) by step distance
  - Thumbs Down (👎)  -> Drone descends (Down) by step distance
  - No Hand / Neutral -> Drone hovers in place
  - Spacebar          -> Emergency Stop / Toggle Gesture Control
  - T                 -> Auto Takeoff
  - L                 -> Auto Land
  - W / S / A / D     -> Manual Pitch / Roll
  - Q / E             -> Manual Yaw (Rotate)
  - + / -             -> Adjust step distance (+/- 5cm)
  - G                 -> Toggle gesture tracking on/off
  - Esc / X           -> Exit

Run with project virtualenv:
  /Users/bjornjanmaat/Developer/Multimodal Interaction Design/projects/myenv/bin/python gesture_controller.py --host <PHONE_IP>
"""

import os
import sys
import time
import threading
import argparse

# Suppress noisy FFmpeg macroblock decode warnings
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

import cv2
import numpy as np
import mediapipe as mp

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from DJIControlClient import DJIControlClient, ControlMode


class VideoReceiver:
    """Manages the RTSP video stream in a background thread."""
    def __init__(self, rtsp_url):
        self.rtsp_url = rtsp_url
        self.cap = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        self.connected = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.thread.start()

    def update_url(self, new_url):
        if new_url and new_url != self.rtsp_url:
            self.rtsp_url = new_url
            if self.cap:
                self.cap.release()
                self.cap = None

    def _stream_loop(self):
        while self.running:
            if not self.rtsp_url:
                time.sleep(0.5)
                continue

            if self.cap is None or not self.cap.isOpened():
                print(f"[VIDEO] Connecting to RTSP Stream: {self.rtsp_url}")
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            ret, frame = self.cap.read()
            if ret:
                self.connected = True
                with self.lock:
                    self.frame = frame
            else:
                self.connected = False
                if self.cap:
                    self.cap.release()
                    self.cap = None
                time.sleep(1.0)

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


def init_mediapipe_recognizer(model_path):
    """Initializes MediaPipe GestureRecognizer."""
    if not os.path.exists(model_path):
        alt_path = os.path.join(os.path.dirname(__file__), "..", "..", "gesture_recognizer.task")
        if os.path.exists(alt_path):
            model_path = alt_path

    BaseOptions = mp.tasks.BaseOptions
    GestureRecognizer = mp.tasks.vision.GestureRecognizer
    GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
    RunningMode = mp.tasks.vision.RunningMode

    options = GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=model_path),
        running_mode=RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )
    return GestureRecognizer.create_from_options(options)


def draw_hud(frame, telemetry, step_dist, gesture_info, estop, gesture_enabled, last_action=""):
    """Draws rich aviation HUD with gesture indicators directly onto video frame."""
    h, w, _ = frame.shape
    overlay = frame.copy()

    # Center Crosshair
    cx, cy = w // 2, h // 2
    cv2.line(overlay, (cx - 20, cy), (cx + 20, cy), (0, 255, 0), 2)
    cv2.line(overlay, (cx, cy - 20), (cx, cy + 20), (0, 255, 0), 2)
    cv2.circle(overlay, (cx, cy), 4, (0, 255, 0), -1)

    # Top Status Bar
    cv2.rectangle(overlay, (0, 0), (w, 50), (20, 20, 20), -1)

    # Drone Connection Status
    dji_status = "CONNECTED" if telemetry["connected"] else "OFFLINE"
    dji_color = (0, 255, 0) if telemetry["connected"] else (0, 0, 255)
    cv2.putText(overlay, f"DRONE: {dji_status}", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, dji_color, 2)

    # Telemetry: Altitude & Heading
    alt_txt = f"ALT: {telemetry['altitude']:.2f} m"
    hdg_txt = f"HDG: {telemetry['heading']:.1f}°"
    cv2.putText(overlay, alt_txt, (cx - 150, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    cv2.putText(overlay, hdg_txt, (cx + 30, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    # Step Distance Badge
    step_cm = int(round(step_dist * 100))
    step_txt = f"STEP: {step_cm}cm ({step_dist:.2f}m)"
    cv2.putText(overlay, step_txt, (w - 240, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 2)

    # --- Gesture Recognition HUD Card (Top Left) ---
    card_x, card_y, card_w, card_h = 20, 65, 360, 110
    cv2.rectangle(overlay, (card_x, card_y), (card_x + card_w, card_y + card_h), (25, 25, 30), -1)
    cv2.rectangle(overlay, (card_x, card_y), (card_x + card_w, card_y + card_h), (80, 80, 80), 1)

    label = gesture_info.get("label", "None")
    score = gesture_info.get("score", 0.0)
    action = gesture_info.get("action", "HOVER")

    if estop:
        g_badge = "GESTURES: PAUSED (E-STOP)"
        g_color = (0, 0, 255)
        action_txt = "ACTION: PAUSED [Press SPACE]"
        action_color = (0, 0, 255)
    elif not gesture_enabled:
        g_badge = "GESTURES: DISABLED"
        g_color = (150, 150, 150)
        action_txt = "ACTION: MANUAL KEYS ONLY [Press G]"
        action_color = (180, 180, 180)
    else:
        if label == "Thumb_Up":
            g_badge = f"👍 THUMB UP ({score:.0%})"
            g_color = (0, 255, 0)
            action_txt = f"ACTION: CLIMBING (+{step_cm}cm)"
            action_color = (0, 255, 0)
        elif label == "Thumb_Down":
            g_badge = f"👎 THUMB DOWN ({score:.0%})"
            g_color = (0, 140, 255)
            action_txt = f"ACTION: DESCENDING (-{step_cm}cm)"
            action_color = (0, 140, 255)
        else:
            g_badge = f"HAND: {label} ({score:.0%})" if label != "None" else "HAND: None (Hovering)"
            g_color = (200, 200, 200)
            action_txt = "ACTION: HOVER IN PLACE"
            action_color = (220, 220, 220)

    cv2.putText(overlay, g_badge, (card_x + 12, card_y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, g_color, 2)
    cv2.putText(overlay, action_txt, (card_x + 12, card_y + 68), cv2.FONT_HERSHEY_SIMPLEX, 0.60, action_color, 2)

    # Indicator light
    ind_color = g_color if (gesture_enabled and not estop) else (0, 0, 255)
    cv2.circle(overlay, (card_x + card_w - 24, card_y + 30), 8, ind_color, -1)

    # Bottom Control Bar
    cv2.rectangle(overlay, (0, h - 45), (w, h), (20, 20, 20), -1)
    controls_txt = "[SPACE] E-Stop | [G] Toggle Gestures | [W/S/A/D] Move | [T] Takeoff | [L] Land | [+/-] Step | [Esc] Exit"
    cv2.putText(overlay, controls_txt, (20, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

    # Last Action Banner
    if last_action:
        cv2.putText(overlay, f"> {last_action}", (20, h - 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 200), 1)

    alpha = 0.88
    return cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)


def create_standby_frame(width=1024, height=576, message="Connecting to Live Drone Video..."):
    """Generates an aesthetic standby screen when camera stream is initializing."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        val = int(25 * (1 - y / height))
        frame[y, :] = (val, val, val + 10)

    for x in range(0, width, 60):
        cv2.line(frame, (x, 0), (x, height), (30, 30, 35), 1)
    for y in range(0, height, 60):
        cv2.line(frame, (0, y), (width, y), (30, 30, 35), 1)

    cx, cy = width // 2, height // 2
    cv2.circle(frame, (cx, cy), 40, (0, 200, 255), 2)
    cv2.line(frame, (cx - 60, cy), (cx + 60, cy), (0, 200, 255), 1)
    cv2.line(frame, (cx, cy - 60), (cx, cy + 60), (0, 200, 255), 1)

    cv2.putText(frame, message, (cx - 180, cy + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (255, 255, 255), 2)
    cv2.putText(frame, "Gestures & flight controls active in window", (cx - 190, cy + 120), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (160, 160, 160), 1)
    return frame


def main():
    parser = argparse.ArgumentParser(description="DJI Unified Gesture Controller")
    parser.add_argument("--host", default="127.0.0.1", help="Android Phone IP or Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="REST API Port (default: 8080)")
    parser.add_argument("--step", type=float, default=0.10, help="Step distance in meters (default: 0.10 = 10cm)")
    parser.add_argument("--speed", type=float, default=0.3, help="Max speed in m/s (default: 0.3)")
    parser.add_argument("--model", default="gesture_recognizer.task", help="MediaPipe model task path")
    parser.add_argument("--min-score", type=float, default=0.65, help="Minimum gesture recognition confidence (default: 0.65)")
    parser.add_argument("--hold-time", type=float, default=0.25, help="Debounce hold time in seconds (default: 0.25)")
    parser.add_argument("--rtsp", default="", help="Custom RTSP URL (leave empty to auto-detect)")
    args = parser.parse_args()

    # Parse host
    host = args.host.strip()
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    if ":" in host:
        host, port_str = host.split(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            port = args.port
    else:
        port = args.port

    print("=" * 65)
    print("   DJI UNIFIED GESTURE CONTROLLER (MediaPipe Thumbs Up/Down)")
    print("=" * 65)
    print(f"Connecting to REST API at http://{host}:{port}...")

    try:
        client = DJIControlClient(ip=host, port=port)
        print("Connected to Flight REST Server successfully!")
    except Exception as e:
        print(f"\nConnection Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Is the DJIUnifiedGestures Android app open on your phone?")
        print("  2. If using Wi-Fi, pass: --host <PHONE_IP> (e.g. --host 192.168.2.8)")
        print("  3. If using USB, run: ./setup_usb_forwarding.sh first")
        sys.exit(1)

    # Initialize drone flight mode
    step_dist = round(args.step, 2)
    step_angle = 30.0
    try:
        client.setControlMode(ControlMode.POSITION)
        client.setMaxSpeed(args.speed)
        client.setLandingProtectionState(False)
    except Exception as e:
        print(f"Notice during flight init: {e}")

    # Initialize MediaPipe Gesture Recognizer
    print(f"Initializing MediaPipe Gesture Recognizer ({args.model})...")
    model_path = args.model
    if not os.path.exists(model_path):
        model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gesture_recognizer.task")
    recognizer = init_mediapipe_recognizer(model_path)
    print("MediaPipe Gesture Recognizer loaded successfully!")

    # Determine RTSP stream URL
    rtsp_url = args.rtsp
    if not rtsp_url:
        try:
            stream_info = client.getLiveStreamInfo()
            if isinstance(stream_info, dict) and stream_info.get("url"):
                raw_url = stream_info.get("url")
                if host in ("127.0.0.1", "localhost"):
                    rtsp_url = "rtsp://admin:123456@127.0.0.1:8554/streaming/live/1"
                else:
                    rtsp_url = raw_url
        except Exception:
            pass

    if not rtsp_url:
        rtsp_url = f"rtsp://admin:123456@{host}:8554/streaming/live/1"

    print(f"Starting Video Receiver on: {rtsp_url}")
    video = VideoReceiver(rtsp_url)
    video.start()

    # Telemetry State
    telemetry = {"connected": True, "altitude": 0.0, "heading": 0.0}
    running = True

    def telemetry_loop():
        while running:
            try:
                alt = client.getAltitude()
                hdg = client.getHeading()
                telemetry["altitude"] = alt
                telemetry["heading"] = hdg
                telemetry["connected"] = True
            except Exception:
                telemetry["connected"] = False
            time.sleep(0.5)

    threading.Thread(target=telemetry_loop, daemon=True).start()

    # Gesture recognition state
    candidate_label = "None"
    candidate_since = time.time()
    active_gesture = "None"
    gesture_info = {"label": "None", "score": 0.0, "action": "HOVER"}
    last_action = "System Ready"

    estop = False              # Emergency Stop toggle
    gesture_enabled = True     # Gesture control enable toggle
    last_command_time = 0.0
    command_interval = 0.70    # Rate limiter between step triggers (700ms)
    action_in_flight = False

    def do_action(action_fn, desc):
        nonlocal last_action, action_in_flight
        if action_in_flight:
            return
        action_in_flight = True
        last_action = desc
        print(f">> {desc}...")
        def _task():
            nonlocal last_action, action_in_flight
            try:
                action_fn()
                last_action = f"{desc} -> Done"
            except Exception as e:
                last_action = f"{desc} -> Error: {e}"
                print(f"Action error: {e}")
            finally:
                action_in_flight = False
        threading.Thread(target=_task, daemon=True).start()

    window_name = "DJI Drone - MediaPipe Gesture Flight Control"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1024, 576)

    print("\n" + "-" * 65)
    print("GESTURE & KEYBOARD CONTROLS:")
    print("  [👍 Thumb Up]    Climb (Move Up by step distance)")
    print("  [👎 Thumb Down]  Descend (Move Down by step distance)")
    print("  [SPACE]          E-Stop / Pause Gesture Control")
    print("  [G]              Toggle Gesture Tracking On/Off")
    print("  [W / S / A / D]  Manual Pitch & Roll")
    print("  [U / J]          Manual Altitude Up / Down")
    print("  [Q / E]          Manual Yaw (Rotate)")
    print("  [T / Spc]        Take Off")
    print("  [L]              Land")
    print("  [+ / -]          Step Distance (+/- 5cm)")
    print("  [Esc / X]        Exit")
    print("-" * 65)

    try:
        while running:
            frame = video.get_frame()
            if frame is None:
                display_frame = create_standby_frame(1024, 576, f"Waiting for Drone RTSP Stream: {rtsp_url}")
            else:
                display_frame = frame

                # Run MediaPipe Gesture Recognizer on incoming frame
                if gesture_enabled and not estop:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    recognition_result = recognizer.recognize(mp_image)

                    detected_label = "None"
                    detected_score = 0.0

                    if recognition_result.gestures:
                        top_gesture = recognition_result.gestures[0][0]
                        detected_label = top_gesture.category_name
                        detected_score = top_gesture.score

                    if detected_score < args.min_score or detected_label not in ("Thumb_Up", "Thumb_Down"):
                        detected_label = "None"

                    # Debounce gesture state
                    now = time.time()
                    if detected_label != candidate_label:
                        candidate_label = detected_label
                        candidate_since = now

                    if now - candidate_since >= args.hold_time:
                        active_gesture = candidate_label
                    if detected_label == "None":
                        active_gesture = "None"

                    gesture_info["label"] = detected_label
                    gesture_info["score"] = detected_score
                    gesture_info["action"] = "CLIMB" if active_gesture == "Thumb_Up" else "DESCEND" if active_gesture == "Thumb_Down" else "HOVER"

                    # Trigger drone movement if gesture is active and rate limit allows
                    if active_gesture == "Thumb_Up" and (now - last_command_time >= command_interval):
                        last_command_time = now
                        do_action(lambda: client.moveUp(step_dist), f"Gesture: Move Up {int(step_dist*100)}cm")

                    elif active_gesture == "Thumb_Down" and (now - last_command_time >= command_interval):
                        last_command_time = now
                        do_action(lambda: client.moveDown(step_dist), f"Gesture: Move Down {int(step_dist*100)}cm")

                else:
                    gesture_info["label"] = "Paused"
                    gesture_info["score"] = 0.0
                    gesture_info["action"] = "PAUSED"

            # Draw HUD
            hud_frame = draw_hud(display_frame, telemetry, step_dist, gesture_info, estop, gesture_enabled, last_action)
            cv2.imshow(window_name, hud_frame)

            # Key check
            key = cv2.waitKey(25) & 0xFF

            if key in (27, ord('x'), ord('X')):
                print("Exit requested. Quitting...")
                break

            elif key == ord(' '):
                estop = not estop
                last_action = "E-STOP ACTIVATED [Gestures Paused]" if estop else "E-STOP RELEASED [Gestures Resumed]"
                print(f">> {last_action}")

            elif key in (ord('g'), ord('G')):
                gesture_enabled = not gesture_enabled
                last_action = f"Gesture Tracking {'ENABLED' if gesture_enabled else 'DISABLED'}"
                print(f">> {last_action}")

            elif key in (ord('w'), ord('W')):
                do_action(lambda: client.moveForward(step_dist), f"Manual Move Forward {int(step_dist*100)}cm")

            elif key in (ord('s'), ord('S')):
                do_action(lambda: client.moveBackward(step_dist), f"Manual Move Backward {int(step_dist*100)}cm")

            elif key in (ord('a'), ord('A')):
                do_action(lambda: client.moveLeft(step_dist), f"Manual Move Left {int(step_dist*100)}cm")

            elif key in (ord('d'), ord('D')):
                do_action(lambda: client.moveRight(step_dist), f"Manual Move Right {int(step_dist*100)}cm")

            elif key in (ord('u'), ord('U')):
                do_action(lambda: client.moveUp(step_dist), f"Manual Move Up {int(step_dist*100)}cm")

            elif key in (ord('j'), ord('J')):
                do_action(lambda: client.moveDown(step_dist), f"Manual Move Down {int(step_dist*100)}cm")

            elif key in (ord('q'), ord('Q')):
                do_action(lambda: client.rotateCounterClockwise(step_angle), f"Manual Rotate CCW {step_angle}°")

            elif key in (ord('e'), ord('E')):
                do_action(lambda: client.rotateClockwise(step_angle), f"Manual Rotate CW {step_angle}°")

            elif key in (ord('t'), ord('T')):
                do_action(lambda: client.takeOff(), "Auto Takeoff")

            elif key in (ord('l'), ord('L')):
                do_action(lambda: client.land(), "Auto Landing")

            elif key in (ord('c'), ord('C')):
                do_action(lambda: client.confirmLanding(), "Confirm Landing")

            elif key in (ord('p'), ord('P')):
                do_action(lambda: client.captureShot(), "Capture Photo")

            elif key in (ord('+'), ord('=')):
                step_dist = round(step_dist + 0.05, 2)
                last_action = f"Step distance set to: {int(step_dist*100)}cm ({step_dist:.2f}m)"
                print(f">> {last_action}")

            elif key in (ord('-'), ord('_')):
                step_dist = max(0.01, round(step_dist - 0.05, 2))
                last_action = f"Step distance set to: {int(step_dist*100)}cm ({step_dist:.2f}m)"
                print(f">> {last_action}")

    except KeyboardInterrupt:
        print("\nInterrupt received. Exiting...")
    finally:
        running = False
        video.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
