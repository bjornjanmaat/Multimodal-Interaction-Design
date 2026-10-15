#!/usr/bin/env python3
"""
DJI Drone Mac Controller & Live Stream HUD
==========================================
Connects to DJI Mobile SDK Android App Bridge for:
1. Low-latency RTSP video display with an interactive Heads-Up Display (HUD)
2. Real-time drone flight control via Keyboard and Gamepad/Joystick
3. Live drone telemetry monitoring (Battery, Altitude, Heading, Flight State)
"""

import os
import sys
import time
import json
import socket
import threading
import argparse

# Suppress noisy FFmpeg macroblock decode warnings from OpenCV stderr
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

import numpy as np
import cv2
import pygame

class DroneBridgeClient:
    """Manages the TCP control and telemetry socket connection to Android."""
    def __init__(self, host='127.0.0.1', port=9090):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False
        self.running = False
        self.lock = threading.Lock()

        # Telemetry state
        self.telemetry = {
            "connected": False,
            "battery": 0,
            "altitude": 0.0,
            "heading": 0.0,
            "isFlying": False,
            "isMotorsOn": False,
            "virtualStickEnabled": False,
            "rtspUrl": "",
            "lastUpdate": 0
        }

        # Current stick inputs (-1.0 to 1.0)
        self.pitch = 0.0      # Forward (+) / Backward (-)
        self.roll = 0.0       # Right (+) / Left (-)
        self.yaw = 0.0        # Rotate CW (+) / CCW (-)
        self.throttle = 0.0   # Ascend (+) / Descend (-)

    def start(self):
        self.running = True
        self.connect_thread = threading.Thread(target=self._connection_loop, daemon=True)
        self.connect_thread.start()

        self.send_thread = threading.Thread(target=self._control_loop, daemon=True)
        self.send_thread.start()

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.connected = False

    def _connection_loop(self):
        while self.running:
            if not self.connected:
                try:
                    print(f"[BRIDGE] Connecting to Android drone bridge at {self.host}:{self.port}...")
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(3.0)
                    s.connect((self.host, self.port))
                    s.settimeout(None)
                    self.sock = s
                    self.connected = True
                    print(f"[BRIDGE] Connected successfully to {self.host}:{self.port}!")

                    # Read telemetry lines
                    buffer = ""
                    while self.running and self.connected:
                        data = s.recv(4096).decode('utf-8')
                        if not data:
                            break
                        buffer += data
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            self._handle_telemetry_line(line.strip())

                except Exception as e:
                    self.connected = False
                    if self.sock:
                        try:
                            self.sock.close()
                        except Exception:
                            pass
                        self.sock = None
                    time.sleep(1.5)
            else:
                time.sleep(0.5)

    def _handle_telemetry_line(self, line):
        if not line:
            return
        try:
            msg = json.loads(line)
            if msg.get("type") == "telemetry":
                with self.lock:
                    self.telemetry["connected"] = msg.get("connected", False)
                    self.telemetry["battery"] = msg.get("battery", 0)
                    self.telemetry["altitude"] = msg.get("altitude", 0.0)
                    self.telemetry["heading"] = msg.get("heading", 0.0)
                    self.telemetry["isFlying"] = msg.get("isFlying", False)
                    self.telemetry["isMotorsOn"] = msg.get("isMotorsOn", False)
                    self.telemetry["virtualStickEnabled"] = msg.get("virtualStickEnabled", False)
                    self.telemetry["rtspUrl"] = msg.get("rtspUrl", "")
                    self.telemetry["lastUpdate"] = time.time()
            elif msg.get("type") == "log":
                log_txt = msg.get("message", "")
                with self.lock:
                    self.telemetry["lastLog"] = log_txt
                print(f"[DRONE STATUS] {log_txt}")
        except Exception as e:
            pass

    def send_command(self, cmd_dict):
        if not self.connected or not self.sock:
            return False
        try:
            line = json.dumps(cmd_dict) + "\n"
            self.sock.sendall(line.encode('utf-8'))
            return True
        except Exception as e:
            self.connected = False
            return False

    def _control_loop(self):
        """Continuously sends stick commands at ~20 Hz."""
        while self.running:
            if self.connected:
                with self.lock:
                    cmd = {
                        "cmd": "stick",
                        "pitch": round(float(self.pitch), 3),
                        "roll": round(float(self.roll), 3),
                        "yaw": round(float(self.yaw), 3),
                        "throttle": round(float(self.throttle), 3)
                    }
                self.send_command(cmd)
            time.sleep(0.05) # 20 Hz

    def takeoff(self):
        print("[ACTION] Requesting Takeoff...")
        self.send_command({"cmd": "takeoff"})

    def land(self):
        print("[ACTION] Requesting Auto Landing...")
        self.send_command({"cmd": "land"})

    def enable_virtual_stick(self):
        print("[ACTION] Enabling Virtual Stick authority...")
        self.send_command({"cmd": "enable_virtual_stick"})

    def disable_virtual_stick(self):
        print("[ACTION] Disabling Virtual Stick authority...")
        self.send_command({"cmd": "disable_virtual_stick"})

    def emergency_hover(self):
        with self.lock:
            self.pitch = 0.0
            self.roll = 0.0
            self.yaw = 0.0
            self.throttle = 0.0
        self.send_command({"cmd": "emergency"})
        print("[ACTION] Emergency Hover triggered (all sticks zeroed).")

    def arm_motors(self):
        print("[ACTION] Requesting CSC Motor Arm (Spin Up Motors)...")
        self.send_command({"cmd": "arm_motors"})


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
                time.sleep(1.0) # Backoff before retrying to prevent console spam

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


def draw_hud(frame, telemetry, bridge_client):
    """Draws an aircraft HUD overlay directly onto the video frame."""
    h, w, _ = frame.shape
    overlay = frame.copy()

    # Center Crosshair
    cx, cy = w // 2, h // 2
    cv2.line(overlay, (cx - 24, cy), (cx + 24, cy), (0, 255, 0), 2)
    cv2.line(overlay, (cx, cy - 24), (cx, cy + 24), (0, 255, 0), 2)
    cv2.circle(overlay, (cx, cy), 4, (0, 255, 0), -1)

    # Top Status Bar
    cv2.rectangle(overlay, (0, 0), (w, 50), (20, 20, 20), -1)

    # Left: Flight Status & Drone Connection
    dji_status = "CONNECTED" if telemetry["connected"] else "DISCONNECTED"
    dji_color = (0, 255, 0) if telemetry["connected"] else (0, 0, 255)
    cv2.putText(overlay, f"DRONE: {dji_status}", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, dji_color, 2)

    # Virtual Stick Status Indicator
    vs_on = telemetry.get("virtualStickEnabled", False)
    vs_txt = "STICK: ENABLED" if vs_on else "STICK: DISABLED (Press E)"
    vs_col = (0, 255, 0) if vs_on else (0, 140, 255)
    cv2.putText(overlay, vs_txt, (260, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.55, vs_col, 2)

    # Center: Flight Mode & Motors
    motors_txt = "MOTORS: ON" if telemetry["isMotorsOn"] else "MOTORS: OFF"
    flying_txt = "AIRBORNE" if telemetry["isFlying"] else "STANDBY"
    cv2.putText(overlay, f"{flying_txt} | {motors_txt}", (cx - 80, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)

    # Right: Battery & Altitude
    batt = telemetry["battery"]
    batt_color = (0, 255, 0) if batt > 30 else (0, 165, 255) if batt > 15 else (0, 0, 255)
    cv2.putText(overlay, f"BATT: {batt}%", (w - 280, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, batt_color, 2)
    cv2.putText(overlay, f"ALT: {telemetry['altitude']:.1f}m", (w - 140, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)

    # Drone Event Notification Banner
    last_log = telemetry.get("lastLog")
    if last_log:
        cv2.rectangle(overlay, (0, 50), (w, 80), (10, 10, 10), -1)
        cv2.putText(overlay, f"STATUS: {last_log}", (20, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

    # Bottom Stick Input Gauge Overlay
    bw, bh = 220, 90
    bx, by = 20, h - bh - 20
    cv2.rectangle(overlay, (bx, by), (bx + bw, by + bh), (30, 30, 30), -1)
    cv2.putText(overlay, "INPUT METERS", (bx + 10, by + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
    cv2.putText(overlay, f"P: {bridge_client.pitch:+.2f}  R: {bridge_client.roll:+.2f}", (bx + 10, by + 46), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
    cv2.putText(overlay, f"Y: {bridge_client.yaw:+.2f}  T: {bridge_client.throttle:+.2f}", (bx + 10, by + 74), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)

    # Controls Helper
    cv2.putText(overlay, "W/S: Pitch | A/D: Roll | Up/Dn: Throttle | Left/Rt: Yaw | Space: Takeoff | C: Arm | L: Land | E: Stick | X: Hover", 
                (bx + bw + 20, h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (220, 220, 220), 1)

    # Blend overlay with original frame for subtle transparency
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    return frame


def get_default_gateway():
    try:
        import subprocess
        out = subprocess.check_output(["netstat", "-nr"], text=True)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "default":
                gw = parts[1]
                if "." in gw and not gw.startswith("127."):
                    return gw
    except Exception:
        pass
    return "127.0.0.1"


def main():
    detected_gw = get_default_gateway()
    parser = argparse.ArgumentParser(description="DJI Drone Mac Controller & Video HUD")
    parser.add_argument("--host", default=detected_gw, help=f"Android device IP (auto-detected default: {detected_gw})")
    parser.add_argument("--port", type=int, default=9090, help="Control TCP port (default 9090)")
    parser.add_argument("--rtsp", default="", help="RTSP stream URL (auto-configured if omitted)")
    args = parser.parse_args()

    # Initialize Pygame Display & Subsystems
    pygame.init()
    pygame.joystick.init()

    # Create native Pygame window so macOS delivers keyboard and mouse focus directly to Pygame
    win_w, win_h = 1280, 720
    screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
    pygame.display.set_caption("DJI Drone Flight Controller & Live HUD")

    joystick = None
    if pygame.joystick.get_count() > 0:
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        print(f"[INPUT] Gamepad detected: {joystick.get_name()}")
    else:
        print("[INPUT] No gamepad detected. Keyboard controls active.")

    # Start Bridge Client
    client = DroneBridgeClient(host=args.host, port=args.port)
    client.start()

    # Start Video Stream Receiver using the specified host
    initial_rtsp = args.rtsp or f"rtsp://admin:123456@{args.host}:8554/streaming/live/1"
    video = VideoReceiver(initial_rtsp)
    video.start()

    clock = pygame.time.Clock()

    print("\n" + "=" * 65)
    print(" DJI DRONE MAC CONTROLLER ACTIVE (Pygame Window Focused)")
    print("=" * 65)
    print(f" Target Drone Bridge: {args.host}:{args.port}")
    print(f" Target Video Stream: {initial_rtsp}")
    print("-" * 65)
    print(" CONTROLS (Click on the window to focus):")
    print("   [W] / [S]         : Pitch Forward / Backward")
    print("   [A] / [D]         : Roll Left / Right")
    print("   [UP] / [DOWN]     : Throttle Ascend / Descend (or I / K)")
    print("   [LEFT] / [RIGHT]  : Yaw Rotate CCW / CW (or J / L)")
    print("   [SPACE]           : Auto Takeoff")
    print("   [C]               : Arm Motors (CSC stick gesture)")
    print("   [L]               : Auto Landing")
    print("   [E]               : Enable Virtual Stick Authority")
    print("   [X] / [ESC]       : Emergency Hover (Neutralize all sticks)")
    print("   [Q]               : Quit Application")
    print("=" * 65 + "\n")

    running = True
    try:
        while running:
            # Update RTSP URL if discovered from telemetry
            discovered_url = client.telemetry.get("rtspUrl")
            if not args.rtsp and discovered_url:
                if "@" in discovered_url:
                    parts = discovered_url.split("@")
                    url_to_use = f"{parts[0]}@{args.host}:8554/streaming/live/1"
                else:
                    url_to_use = f"rtsp://admin:123456@{args.host}:8554/streaming/live/1"
                video.update_url(url_to_use)

            # Process Pygame window and key events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    win_w, win_h = event.w, event.h
                    screen = pygame.display.set_mode((win_w, win_h), pygame.RESIZABLE)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        print("[ACTION] Quit requested.")
                        running = False
                    elif event.key == pygame.K_SPACE:
                        print("[KEY] SPACE -> Auto Takeoff")
                        client.takeoff()
                    elif event.key == pygame.K_l:
                        print("[KEY] L -> Auto Landing")
                        client.land()
                    elif event.key == pygame.K_e:
                        print("[KEY] E -> Enable Virtual Stick")
                        client.enable_virtual_stick()
                    elif event.key == pygame.K_c:
                        print("[KEY] C -> Arm Motors (CSC)")
                        client.arm_motors()
                    elif event.key == pygame.K_x or event.key == pygame.K_ESCAPE:
                        print("[KEY] X/ESC -> Emergency Hover")
                        client.emergency_hover()

            # Continuous stick inputs
            if joystick:
                # Standard dual-stick gamepad layout
                roll = joystick.get_axis(0)
                pitch = -joystick.get_axis(1)     # Invert Y axis
                yaw = joystick.get_axis(2) if joystick.get_numaxes() > 2 else joystick.get_axis(3)
                throttle = -joystick.get_axis(3) if joystick.get_numaxes() > 3 else -joystick.get_axis(4)

                # Deadzone
                roll = roll if abs(roll) > 0.08 else 0.0
                pitch = pitch if abs(pitch) > 0.08 else 0.0
                yaw = yaw if abs(yaw) > 0.08 else 0.0
                throttle = throttle if abs(throttle) > 0.08 else 0.0

                with client.lock:
                    client.roll = roll
                    client.pitch = pitch
                    client.yaw = yaw
                    client.throttle = throttle
            else:
                # Keyboard continuous stick inputs
                keys = pygame.key.get_pressed()
                p = 0.0
                r = 0.0
                t = 0.0
                y = 0.0

                if keys[pygame.K_w]: p += 1.0
                if keys[pygame.K_s]: p -= 1.0
                if keys[pygame.K_d]: r += 1.0
                if keys[pygame.K_a]: r -= 1.0

                if keys[pygame.K_UP] or keys[pygame.K_i]: t += 1.0
                if keys[pygame.K_DOWN] or keys[pygame.K_k]: t -= 1.0
                if keys[pygame.K_RIGHT] or keys[pygame.K_l]: y += 1.0
                if keys[pygame.K_LEFT] or keys[pygame.K_j]: y -= 1.0

                with client.lock:
                    client.pitch = p
                    client.roll = r
                    client.throttle = t
                    client.yaw = y

            # Video & HUD rendering
            frame = video.get_frame()
            if frame is None:
                # Standby HUD when waiting for video stream
                frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                cv2.putText(frame, "WAITING FOR RTSP VIDEO STREAM...", (380, 350), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (120, 120, 120), 2)
                cv2.putText(frame, f"Stream Target: {video.rtsp_url}", (340, 390), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 80), 1)

            frame = draw_hud(frame, client.telemetry, client)

            # Convert BGR frame to RGB for Pygame
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            cur_w, cur_h = screen.get_size()
            if (frame_rgb.shape[1], frame_rgb.shape[0]) != (cur_w, cur_h):
                frame_rgb = cv2.resize(frame_rgb, (cur_w, cur_h), interpolation=cv2.INTER_LINEAR)

            # Render to Pygame window
            surface = pygame.image.frombuffer(frame_rgb.tobytes(), (cur_w, cur_h), 'RGB')
            screen.blit(surface, (0, 0))
            pygame.display.flip()

            clock.tick(30) # 30 FPS display loop

    except KeyboardInterrupt:
        print("\n[CONTROLLER] Shutting down...")
    finally:
        client.stop()
        video.stop()
        pygame.quit()
        print("[CONTROLLER] Closed successfully.")

if __name__ == "__main__":
    main()
