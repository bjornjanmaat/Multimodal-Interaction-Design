#!/usr/bin/env python3
"""
DJI Unified Flight Controller & Live Stream HUD
================================================
Combines:
1. Low-latency RTSP Live Video Stream decoding & Interactive Aviation HUD
2. Precision 6DOF Flight Control (20cm steps, translation, rotation, takeoff, landing)
3. Real-time Telemetry Display (Altitude, Heading, Connection, Battery)

Usage:
  # Over Wi-Fi:
  python3 controller.py --host 192.168.2.8

  # Over USB (via adb forward):
  ./setup_usb_forwarding.sh
  python3 controller.py --host 127.0.0.1
"""

import os
import sys
import time
import threading
import argparse

# Suppress noisy FFmpeg macroblock decode warnings from OpenCV stderr
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

import cv2
import numpy as np

# Add local path for DJIControlClient
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from DJIControlClient import DJIControlClient, ControlMode, VelocityProfile


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


def draw_hud(frame, telemetry, step_dist, step_angle, last_action=""):
    """Draws an aviation HUD overlay directly onto the video frame."""
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

    # Step Distance & Angle Badge
    step_cm = int(round(step_dist * 100))
    step_txt = f"STEP: {step_cm}cm ({step_dist:.2f}m)"
    cv2.putText(overlay, step_txt, (w - 240, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 2)

    # Bottom Control Bar
    cv2.rectangle(overlay, (0, h - 45), (w, h), (20, 20, 20), -1)
    controls_txt = "[W/S] Fwd/Back | [A/D] Left/Right | [U/J] Up/Down | [Q/E] Yaw | [T] Takeoff | [L] Land | [P] Photo | [+/-] Step"
    cv2.putText(overlay, controls_txt, (20, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

    # Last Action Banner
    if last_action:
        cv2.putText(overlay, f"> {last_action}", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 255, 200), 2)

    # Alpha blend HUD overlay
    alpha = 0.88
    return cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0)


def create_standby_frame(width=960, height=540, message="Connecting to Live Drone Video..."):
    """Generates an aesthetic standby screen when camera stream is initializing."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        val = int(25 * (1 - y / height))
        frame[y, :] = (val, val, val + 10)

    # Grid lines
    for x in range(0, width, 60):
        cv2.line(frame, (x, 0), (x, height), (30, 30, 35), 1)
    for y in range(0, height, 60):
        cv2.line(frame, (0, y), (width, y), (30, 30, 35), 1)

    cx, cy = width // 2, height // 2
    cv2.circle(frame, (cx, cy), 40, (0, 200, 255), 2)
    cv2.line(frame, (cx - 60, cy), (cx + 60, cy), (0, 200, 255), 1)
    cv2.line(frame, (cx, cy - 60), (cx, cy + 60), (0, 200, 255), 1)

    cv2.putText(frame, message, (cx - 180, cy + 90), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (255, 255, 255), 2)
    cv2.putText(frame, "Flight controls active in terminal & window", (cx - 190, cy + 120), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (160, 160, 160), 1)
    return frame


def main():
    parser = argparse.ArgumentParser(description="DJI Unified Flight & Live Stream Controller")
    parser.add_argument("--host", default="127.0.0.1", help="Android Phone IP or Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="REST API Port (default: 8080)")
    parser.add_argument("--step", type=float, default=0.20, help="Initial step distance in meters (default: 0.20 = 20cm)")
    parser.add_argument("--speed", type=float, default=0.5, help="Max speed in m/s (default: 0.5)")
    parser.add_argument("--rtsp", default="", help="Custom RTSP URL (leave empty to auto-detect from Android)")
    args = parser.parse_args()

    # Parse and clean host
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

    print("=" * 60)
    print("      DJI UNIFIED FLIGHT CONTROLLER & LIVE STREAM")
    print("=" * 60)
    print(f"Connecting to REST API at http://{host}:{port}...")

    try:
        client = DJIControlClient(ip=host, port=port)
        print("Connected to Flight REST Server successfully!")
    except Exception as e:
        print(f"\nConnection Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Is the DJIUnified Android app open on your phone?")
        print("  2. If using Wi-Fi, pass: --host <PHONE_IP> (e.g. --host 192.168.2.8)")
        print("  3. If using USB, run: ./setup_usb_forwarding.sh first")
        sys.exit(1)

    # Initialize drone flight settings
    step_dist = round(args.step, 2)
    step_angle = 30.0
    try:
        client.setControlMode(ControlMode.POSITION)
        client.setMaxSpeed(args.speed)
        client.setLandingProtectionState(False)
    except Exception as e:
        print(f"Notice during flight init: {e}")

    # Determine RTSP Stream URL
    rtsp_url = args.rtsp
    if not rtsp_url:
        try:
            stream_info = client.getLiveStreamInfo()
            if isinstance(stream_info, dict) and stream_info.get("url"):
                # If connecting via USB forward, replace the IP with localhost
                raw_url = stream_info.get("url")
                if host in ("127.0.0.1", "localhost"):
                    rtsp_url = f"rtsp://admin:123456@127.0.0.1:8554/streaming/live/1"
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
    telemetry = {
        "connected": True,
        "altitude": 0.0,
        "heading": 0.0,
        "battery": 0
    }
    running = True

    # Background Telemetry Poller
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

    t_thread = threading.Thread(target=telemetry_loop, daemon=True)
    t_thread.start()

    last_action = "System Ready"
    show_hud = True
    window_name = "DJI Drone Flight & Live Stream (HUD)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1024, 576)

    print("\n" + "-" * 60)
    print("CONTROLS:")
    print("  [W / S]  Move Forward / Backward (by step distance)")
    print("  [A / D]  Move Left / Right")
    print("  [U / J]  Move Up / Down")
    print("  [Q / E]  Rotate CCW / CW")
    print("  [T / Spc] Take Off")
    print("  [L]      Land")
    print("  [C]      Confirm Landing")
    print("  [P]      Take Photo")
    print("  [+ / -]  Increase / Decrease step distance (+/- 5cm)")
    print("  [V]      Toggle HUD Display")
    print("  [Esc/X]  Quit")
    print("-" * 60)

    # Non-blocking flight action worker
    def do_action(action_fn, desc):
        nonlocal last_action
        last_action = desc
        print(f">> {desc}...")
        def _task():
            nonlocal last_action
            try:
                res = action_fn()
                last_action = f"{desc} -> Done"
            except Exception as e:
                last_action = f"{desc} -> Error: {e}"
                print(f"Action error: {e}")
        threading.Thread(target=_task, daemon=True).start()

    try:
        while running:
            frame = video.get_frame()
            if frame is None:
                display_frame = create_standby_frame(1024, 576, f"Connecting to RTSP: {rtsp_url}")
            else:
                display_frame = frame

            if show_hud:
                display_frame = draw_hud(display_frame, telemetry, step_dist, step_angle, last_action)

            cv2.imshow(window_name, display_frame)

            # Check for keys pressed in the OpenCV window (non-blocking 25ms delay)
            key = cv2.waitKey(25) & 0xFF

            if key in (27, ord('x'), ord('X')):  # Esc or X
                print("Exit requested. Closing...")
                break

            elif key in (ord('w'), ord('W')):
                do_action(lambda: client.moveForward(step_dist), f"Move Forward {int(step_dist*100)}cm")

            elif key in (ord('s'), ord('S')):
                do_action(lambda: client.moveBackward(step_dist), f"Move Backward {int(step_dist*100)}cm")

            elif key in (ord('a'), ord('A')):
                do_action(lambda: client.moveLeft(step_dist), f"Move Left {int(step_dist*100)}cm")

            elif key in (ord('d'), ord('D')):
                do_action(lambda: client.moveRight(step_dist), f"Move Right {int(step_dist*100)}cm")

            elif key in (ord('u'), ord('U'), 0):  # U or Up arrow
                do_action(lambda: client.moveUp(step_dist), f"Move Up {int(step_dist*100)}cm")

            elif key in (ord('j'), ord('J'), 1):  # J or Down arrow
                do_action(lambda: client.moveDown(step_dist), f"Move Down {int(step_dist*100)}cm")

            elif key in (ord('q'), ord('Q'), 2):  # Q or Left arrow
                do_action(lambda: client.rotateCounterClockwise(step_angle), f"Rotate CCW {step_angle}°")

            elif key in (ord('e'), ord('E'), 3):  # E or Right arrow
                do_action(lambda: client.rotateClockwise(step_angle), f"Rotate CW {step_angle}°")

            elif key in (ord('t'), ord('T'), 32):  # T or Space
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

            elif key in (ord('v'), ord('V')):
                show_hud = not show_hud
                last_action = f"HUD {'Enabled' if show_hud else 'Disabled'}"

    except KeyboardInterrupt:
        print("\nInterrupt received. Exiting...")
    finally:
        running = False
        video.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
