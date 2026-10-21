#!/usr/bin/env python3
"""
DJI Unified Gesture Controller & Live Stream HUD
=================================================
Recognizes dynamic hand gesture transitions, postures, and real-time gaze tracking
(looking straight at the camera vs looking away) using Google MediaPipe to command
drone 3D motion:

Features:
  - Gaze Tracking: Identifies if the person is looking straight at the camera or looking away
    with live head pose (yaw/pitch) and iris position tracking in the HUD interface.
  - Closing Hand (✋ -> ✊ Open to Closed) -> Drone moves Forward by step distance
  - Opening Hand (✊ -> ✋ Closed to Open) -> Drone moves Backward by step distance
  - Thumbs Up (👍)                         -> Drone climbs (Up) by step distance
  - Thumbs Down (👎)                       -> Drone descends (Down) by step distance
  - No Hand / Neutral                      -> Drone hovers in place
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
import math
import socket
import threading
import argparse
from collections import deque
import random

# Suppress noisy FFmpeg macroblock decode warnings and force TCP transport for robust RTSP
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import cv2
import numpy as np
import mediapipe as mp

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from DJIControlClient import DJIControlClient, ControlMode, MockDJIControlClient


class ArduinoVibrationController:
    """Manages wireless UDP haptic feedback communication to Arduino vibration motors (M1-M4)."""
    def __init__(self, ip="10.114.198.176", port=5005):
        self.ip = ip
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_trigger_time = 0.0
        self.active_buzz_thread = None

    def set_vibration(self, level: int, motor=None):
        """Sets motor vibration level (0-255). If motor is None, sets all M1-M4 motors."""
        level = max(0, min(255, int(level)))
        try:
            if motor is None:
                payload = str(level)
            elif motor in (1, 2, 3, 4):
                payload = f"M{motor}:{level}"
            else:
                payload = str(level)
            self.sock.sendto(payload.encode(), (self.ip, self.port))
        except Exception:
            pass

    def set_motors(self, m1=0, m2=0, m3=0, m4=0):
        """Sets independent intensities (0-255) for M1, M2, M3, M4."""
        m1 = max(0, min(255, int(m1)))
        m2 = max(0, min(255, int(m2)))
        m3 = max(0, min(255, int(m3)))
        m4 = max(0, min(255, int(m4)))
        try:
            self.sock.sendto(f"{m1},{m2},{m3},{m4}".encode(), (self.ip, self.port))
        except Exception:
            pass

    def trigger_buzz_async(self, duration=0.30, intensity=255, motor=None, cooldown=0.80):
        """Triggers a vibration pulse in a background thread without blocking the video loop."""
        now = time.time()
        if now - self.last_trigger_time < cooldown:
            return False
        self.last_trigger_time = now

        def _buzz():
            try:
                self.set_vibration(intensity, motor=motor)
                time.sleep(duration)
                self.set_vibration(0, motor=motor)
            except Exception:
                pass

        threading.Thread(target=_buzz, daemon=True).start()
        return True

    def close(self):
        try:
            self.set_vibration(0)
            self.sock.close()
        except Exception:
            pass


def classify_thumb_direction(landmarks, detected_label="None"):
    """
    Identifies 4-way thumb orientation:
      - THUMB_UP
      - THUMB_DOWN
      - THUMB_LEFT
      - THUMB_RIGHT
    Strictly checks that the other 4 fingers are tightly curled (fist)
    and the thumb is prominently extended outwards.
    Returns None if the hand is an open palm, closed fist, or transition.
    """
    if not landmarks or len(landmarks) < 21:
        if detected_label == "Thumb_Up":
            return "THUMB_UP"
        elif detected_label == "Thumb_Down":
            return "THUMB_DOWN"
        return None

    try:
        w = np.array([landmarks[0].x, landmarks[0].y, landmarks[0].z])
        m_mcp = np.array([landmarks[9].x, landmarks[9].y, landmarks[9].z])
        palm_scale = np.linalg.norm(m_mcp - w)
        if palm_scale < 1e-4:
            return None

        # 1. Check extension of the other 4 fingers (Index, Middle, Ring, Pinky)
        # In a genuine thumb gesture, all 4 other fingers must be curled into the palm!
        tips = [8, 12, 16, 20]
        pips = [6, 10, 14, 18]
        curled_count = 0
        tip_dists_to_wrist = []

        for tip_idx, pip_idx in zip(tips, pips):
            tip = np.array([landmarks[tip_idx].x, landmarks[tip_idx].y, landmarks[tip_idx].z])
            pip = np.array([landmarks[pip_idx].x, landmarks[pip_idx].y, landmarks[pip_idx].z])
            d_tip = np.linalg.norm(tip - w)
            d_pip = np.linalg.norm(pip - w)
            tip_dists_to_wrist.append(d_tip / palm_scale)

            # Tip is curled if it's closer or barely further than PIP to wrist
            if d_tip <= d_pip * 1.05:
                curled_count += 1

        avg_finger_ext = float(np.mean(tip_dists_to_wrist))
        # If fingers are extended (open hand), this CANNOT be a thumb gesture!
        if curled_count < 3 or avg_finger_ext > 1.30:
            return None

        # 2. Check Thumb Extension & Isolation from Palm / Fist
        thumb_tip = np.array([landmarks[4].x, landmarks[4].y, landmarks[4].z])
        thumb_ip = np.array([landmarks[3].x, landmarks[3].y, landmarks[3].z])
        thumb_mcp = np.array([landmarks[2].x, landmarks[2].y, landmarks[2].z])
        thumb_cmc = np.array([landmarks[1].x, landmarks[1].y, landmarks[1].z])

        # Straightness / full extension of the thumb itself
        thumb_segment_sum = (
            np.linalg.norm(thumb_tip - thumb_ip) +
            np.linalg.norm(thumb_ip - thumb_mcp) +
            np.linalg.norm(thumb_mcp - thumb_cmc)
        )
        thumb_direct_dist = np.linalg.norm(thumb_tip - thumb_cmc)
        thumb_straightness = thumb_direct_dist / (thumb_segment_sum + 1e-6)

        # Distances of thumb tip to index knuckle (5), middle knuckle (9), and wrist (0)
        index_mcp = np.array([landmarks[5].x, landmarks[5].y, landmarks[5].z])
        mid_mcp = np.array([landmarks[9].x, landmarks[9].y, landmarks[9].z])

        d_tip_to_index = np.linalg.norm(thumb_tip - index_mcp) / palm_scale
        d_tip_to_mid = np.linalg.norm(thumb_tip - mid_mcp) / palm_scale
        thumb_reach = thumb_direct_dist / palm_scale

        # In a closed fist:
        # - The thumb is folded across the fingers or tucked against index knuckle (d_tip_to_index < 0.65)
        # - Thumb straightness is low (< 0.85) because the thumb IP/MCP joints are bent
        # - Thumb reach from CMC is short (< 0.75)
        # In an actual thumb gesture:
        # - Thumb is clearly extended straight outwards (straightness >= 0.86)
        # - Thumb tip is far from both the index knuckle (>= 0.62) and middle knuckle (>= 0.65)
        # - Thumb reach is significant (>= 0.72)
        if thumb_straightness < 0.86 or thumb_reach < 0.72 or d_tip_to_index < 0.62 or d_tip_to_mid < 0.65:
            return None

        # 3. Vector and Angle of Thumb from CMC/MCP (2) to Tip (4)
        dx = landmarks[4].x - landmarks[2].x
        dy = landmarks[4].y - landmarks[2].y

        # Angle: 0° is Right, 90° is UP, 180°/-180° is Left, -90° is DOWN
        angle = np.degrees(np.arctan2(-dy, dx))

        if 50 <= angle <= 130:
            return "THUMB_UP"
        elif -130 <= angle <= -50:
            return "THUMB_DOWN"
        elif -40 < angle < 40:
            return "THUMB_RIGHT"
        elif angle >= 140 or angle <= -140:
            return "THUMB_LEFT"
        else:
            # Ambiguous diagonal angle - don't jump to conclusions
            return None

    except Exception:
        return None


class WebcamReceiver:
    """Captures live video from the laptop's built-in camera for gesture simulation."""
    def __init__(self, camera_index=0, mirror=True):
        self.camera_index = camera_index
        self.mirror = mirror
        self.cap = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        self.connected = False

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        print(f"[WEBCAM] Opening laptop camera #{self.camera_index}...")
        self.cap = cv2.VideoCapture(self.camera_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        # Allow warmup frames
        for _ in range(5):
            ret, frame = self.cap.read()
            if ret and frame is not None and frame.size > 0:
                break
            time.sleep(0.1)

        while self.running:
            if self.cap is None or not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.camera_index)
                time.sleep(0.5)

            ret, frame = self.cap.read()
            if ret and frame is not None and frame.size > 0:
                if self.mirror:
                    frame = cv2.flip(frame, 1)  # Horizontal mirror for intuitive gestures
                self.connected = True
                with self.lock:
                    self.frame = frame
            else:
                self.connected = False
                time.sleep(0.05)

    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


class VideoReceiver:
    """Manages the RTSP video stream in a background thread."""
    def __init__(self, rtsp_url, client=None):
        self.rtsp_url = rtsp_url
        self.client = client
        self.cap = None
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        self.connected = False
        self.last_start_attempt = 0.0

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
                now = time.time()
                # If disconnected, check phone live stream state every 5 seconds
                if self.client and (now - self.last_start_attempt > 5.0):
                    self.last_start_attempt = now
                    try:
                        info = self.client.getLiveStreamInfo()
                        if not info.get("streaming"):
                            print("[VIDEO] Requesting phone to start live stream...")
                            self.client.startLiveStream()
                            time.sleep(1.0)
                        if info.get("url") and info["url"] != self.rtsp_url:
                            self.update_url(info["url"])
                    except Exception:
                        pass

                print(f"[VIDEO] Connecting to RTSP Stream: {self.rtsp_url}")
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            ret, frame = self.cap.read()
            if ret and frame is not None and frame.size > 0:
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


def compute_hand_openness(landmarks):
    """Computes normalized fingertip extension ratio relative to palm size."""
    if not landmarks or len(landmarks) < 21:
        return 1.4
    try:
        w = np.array([landmarks[0].x, landmarks[0].y, landmarks[0].z])
        m_mcp = np.array([landmarks[9].x, landmarks[9].y, landmarks[9].z])
        palm_scale = np.linalg.norm(m_mcp - w)
        if palm_scale < 1e-4:
            return 1.4
        tips = [8, 12, 16, 20]  # Index, Middle, Ring, Pinky tips
        dists = [np.linalg.norm(np.array([landmarks[t].x, landmarks[t].y, landmarks[t].z]) - w) / palm_scale for t in tips]
        return float(np.mean(dists))
    except Exception:
        return 1.4


def classify_rps_hand(hand_data):
    """
    Classifies Rock (✊), Paper (✋), or Scissors (✌️) using both
    MediaPipe classifier labels and geometric finger joint landmark analysis.
    Ensures that two hands can be reliably recognized simultaneously.
    """
    lbl = hand_data.get("label", "None")
    if lbl == "Closed_Fist":
        return "ROCK"
    elif lbl == "Open_Palm":
        return "PAPER"
    elif lbl == "Victory":
        return "SCISSORS"
    elif lbl in ("Thumb_Up", "Thumb_Down"):
        return "ROCK"

    # Geometric landmark analysis from hand joints
    lm = hand_data.get("landmarks")
    if lm and len(lm) >= 21:
        try:
            w_pt = np.array([lm[0].x, lm[0].y, lm[0].z])

            # Finger definitions: (tip_idx, pip_idx, mcp_idx)
            # Index: (8, 6, 5), Middle: (12, 10, 9), Ring: (16, 14, 13), Pinky: (20, 18, 17)
            fingers = [(8, 6, 5), (12, 10, 9), (16, 14, 13), (20, 18, 17)]
            extended = []
            for tip_idx, pip_idx, mcp_idx in fingers:
                tip = np.array([lm[tip_idx].x, lm[tip_idx].y, lm[tip_idx].z])
                pip = np.array([lm[pip_idx].x, lm[pip_idx].y, lm[pip_idx].z])
                mcp = np.array([lm[mcp_idx].x, lm[mcp_idx].y, lm[mcp_idx].z])

                d_tip_w = np.linalg.norm(tip - w_pt)
                d_pip_w = np.linalg.norm(pip - w_pt)
                d_tip_mcp = np.linalg.norm(tip - mcp)
                d_pip_mcp = np.linalg.norm(pip - mcp)

                # Extended if tip is further from wrist and mcp than pip knuckle
                is_ext = (d_tip_w > d_pip_w) and (d_tip_mcp > d_pip_mcp * 0.95)
                extended.append(is_ext)

            idx_ext, mid_ext, ring_ext, pnk_ext = extended
            num_ext = sum(extended)

            d_idx_w = np.linalg.norm(np.array([lm[8].x, lm[8].y, lm[8].z]) - w_pt)
            d_mid_w = np.linalg.norm(np.array([lm[12].x, lm[12].y, lm[12].z]) - w_pt)
            d_rng_w = np.linalg.norm(np.array([lm[16].x, lm[16].y, lm[16].z]) - w_pt)
            d_pnk_w = np.linalg.norm(np.array([lm[20].x, lm[20].y, lm[20].z]) - w_pt)

            # Scissors: Index and Middle extended, Ring and Pinky folded
            if idx_ext and mid_ext and not ring_ext and not pnk_ext:
                return "SCISSORS"
            if idx_ext and mid_ext and num_ext == 2:
                return "SCISSORS"
            if (d_idx_w + d_mid_w) > 1.30 * (d_rng_w + d_pnk_w + 1e-6) and idx_ext and mid_ext:
                return "SCISSORS"

            # Paper: 3 or 4 fingers extended
            if num_ext >= 3:
                return "PAPER"

            # Rock: 0 or 1 finger extended (fist)
            if num_ext <= 1:
                return "ROCK"
        except Exception:
            pass

    return "NONE"


def map_duration_to_speed(duration, min_speed=0.15, max_speed=0.80, min_dur=0.12, max_dur=0.65):
    """Maps gesture transition duration to drone flight speed in m/s."""
    d_clamped = min(max(duration, min_dur), max_dur)
    factor = (max_dur - d_clamped) / (max_dur - min_dur)  # 1.0 for fast (<=0.12s), 0.0 for slow (>=0.65s)
    speed = round(min_speed + factor * (max_speed - min_speed), 2)
    if factor >= 0.65:
        tier = "FAST"
    elif factor <= 0.30:
        tier = "SLOW"
    else:
        tier = "NORMAL"
    return speed, tier


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
        num_hands=4,
        min_hand_detection_confidence=0.35,
        min_hand_presence_confidence=0.35,
        min_tracking_confidence=0.35
    )
    return GestureRecognizer.create_from_options(options)


class GazeTracker:
    """
    Real-time Gaze Tracker inspired by antoinelame/GazeTracking.
    Combines eye isolation, adaptive threshold pupil detection, and MediaPipe Face Mesh.
    Calculates horizontal and vertical pupil ratios and head alignment to determine
    whether the user is looking straight at the camera or looking left/right/away.
    """
    LEFT_EYE_INDICES = [33, 160, 158, 133, 153, 144]
    RIGHT_EYE_INDICES = [362, 385, 387, 263, 373, 380]

    def __init__(self):
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.smooth_h = 0.46
        self.smooth_v = 0.45
        self.smooth_head_offset = 0.0
        self.initialized = False

    def _isolate_eye(self, gray_frame, lm, indices, w, h):
        """Isolate an eye to have a frame without other parts of the face (Antoine Lamé style)."""
        region = np.array([[int(lm[idx].x * w), int(lm[idx].y * h)] for idx in indices], dtype=np.int32)
        black_frame = np.zeros((h, w), np.uint8)
        mask = np.full((h, w), 255, np.uint8)
        cv2.fillPoly(mask, [region], (0, 0, 0))
        eye = cv2.bitwise_not(black_frame, gray_frame.copy(), mask=mask)

        margin = 4
        min_x = max(0, np.min(region[:, 0]) - margin)
        max_x = min(w, np.max(region[:, 0]) + margin)
        min_y = max(0, np.min(region[:, 1]) - margin)
        max_y = min(h, np.max(region[:, 1]) + margin)

        eye_frame = eye[min_y:max_y, min_x:max_x]
        return eye_frame, (min_x, min_y), region

    def _detect_pupil_threshold(self, eye_frame, fallback_xy):
        """Detects the iris and estimates pupil position using Antoine Lamé bilateral + erode + thresholding."""
        if eye_frame.shape[0] < 6 or eye_frame.shape[1] < 6:
            return fallback_xy

        kernel = np.ones((3, 3), np.uint8)
        bilat = cv2.bilateralFilter(eye_frame, 10, 15, 15)
        eroded = cv2.erode(bilat, kernel, iterations=2)

        average_iris_size = 0.46
        best_th = 40
        min_diff = 1.0
        for th in range(20, 80, 5):
            b_frame = cv2.threshold(eroded, th, 255, cv2.THRESH_BINARY)[1]
            c = b_frame[2:-2, 2:-2]
            if c.size > 0:
                sz = (c.size - cv2.countNonZero(c)) / c.size
                diff = abs(sz - average_iris_size)
                if diff < min_diff:
                    min_diff = diff
                    best_th = th

        iris_bin = cv2.threshold(eroded, best_th, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(iris_bin, cv2.RETR_TREE, cv2.CHAIN_APPROX_NONE)[-2:]
        contours = sorted(contours, key=cv2.contourArea)
        if len(contours) >= 2:
            m = cv2.moments(contours[-2])
            if m['m00'] > 0:
                px = int(m['m10'] / m['m00'])
                py = int(m['m01'] / m['m00'])
                return px, py
        return fallback_xy

    def process(self, frame_bgr):
        h, w, _ = frame_bgr.shape
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            return {
                "face_detected": False,
                "looking_at_camera": False,
                "direction": "NO FACE DETECTED",
                "horizontal_ratio": 0.50,
                "vertical_ratio": 0.50,
                "confidence": 0.0,
                "iris_left": None,
                "iris_right": None
            }

        lm = results.multi_face_landmarks[0].landmark

        # MediaPipe sub-millimeter Iris Center Landmarks
        # 468 is right-in-camera iris center, 473 is left-in-camera iris center
        mp_pl = (int(lm[468].x * w), int(lm[468].y * h))
        mp_pr = (int(lm[473].x * w), int(lm[473].y * h))

        # Antoine Lamé eye isolation & pupil threshold refinement
        eye_l, orig_l, reg_l = self._isolate_eye(gray, lm, self.LEFT_EYE_INDICES, w, h)
        eye_r, orig_r, reg_r = self._isolate_eye(gray, lm, self.RIGHT_EYE_INDICES, w, h)

        fb_l = (mp_pl[0] - orig_l[0], mp_pl[1] - orig_l[1])
        fb_r = (mp_pr[0] - orig_r[0], mp_pr[1] - orig_r[1])

        pl_local = self._detect_pupil_threshold(eye_l, fb_l)
        pr_local = self._detect_pupil_threshold(eye_r, fb_r)

        final_pl = (orig_l[0] + pl_local[0], orig_l[1] + pl_local[1])
        final_pr = (orig_r[0] + pr_local[0], orig_r[1] + pr_local[1])

        # Eye socket boundary landmarks
        # Left eye in frame: 33 (outer corner) to 133 (inner corner)
        # Right eye in frame: 362 (inner corner) to 263 (outer corner)
        p33_x = lm[33].x * w
        p133_x = lm[133].x * w
        p362_x = lm[362].x * w
        p263_x = lm[263].x * w

        # Relative horizontal ratios (0.0 = looking one side, 1.0 = looking other side)
        r1 = (final_pl[0] - p33_x) / (p133_x - p33_x + 1e-6)
        r2 = (final_pr[0] - p362_x) / (p263_x - p362_x + 1e-6)
        raw_h = float((r1 + r2) / 2.0)

        # Vertical ratios (top lid to bottom lid)
        p159_y = lm[159].y * h
        p145_y = lm[145].y * h
        p386_y = lm[386].y * h
        p374_y = lm[374].y * h

        v1 = (final_pl[1] - p159_y) / (p145_y - p159_y + 1e-6)
        v2 = (final_pr[1] - p386_y) / (p374_y - p386_y + 1e-6)
        raw_v = float((v1 + v2) / 2.0)

        # Head alignment offset (nose relative to midpoint between eyes)
        mid_eyes_x = (p33_x + p263_x) / 2.0
        eye_span = abs(p263_x - p33_x) + 1e-6
        nose_x = lm[1].x * w
        raw_head_offset = (nose_x - mid_eyes_x) / eye_span

        # Exponential moving average filter
        alpha = 0.35
        if not self.initialized:
            self.smooth_h = raw_h
            self.smooth_v = raw_v
            self.smooth_head_offset = raw_head_offset
            self.initialized = True
        else:
            self.smooth_h = (1 - alpha) * self.smooth_h + alpha * raw_h
            self.smooth_v = (1 - alpha) * self.smooth_v + alpha * raw_v
            self.smooth_head_offset = (1 - alpha) * self.smooth_head_offset + alpha * raw_head_offset

        # Antoine Lamé Gaze Direction Classification:
        # Looking Center (Straight at Camera):
        # 1. Pupil horizontal ratio centered (between 0.32 and 0.62)
        # 2. Pupil vertical ratio centered (between 0.24 and 0.68)
        # 3. Head facing forward (offset within ±0.17)
        is_center_h = 0.32 <= self.smooth_h <= 0.62
        is_center_v = 0.24 <= self.smooth_v <= 0.68
        is_head_front = abs(self.smooth_head_offset) <= 0.17

        looking_straight = bool(is_center_h and is_center_v and is_head_front)

        # High threshold for VERY CLEAR gaze aversion:
        # User must distinctly look away (significant pupil excursion or distinct head turn)
        is_clear_head_turn = abs(self.smooth_head_offset) >= 0.22
        is_clear_look_right = self.smooth_h >= 0.66
        is_clear_look_left = self.smooth_h <= 0.28
        is_clear_look_up = self.smooth_v <= 0.20
        is_clear_look_down = self.smooth_v >= 0.72

        clear_averted = bool(
            is_clear_head_turn or
            is_clear_look_right or
            is_clear_look_left or
            is_clear_look_up or
            is_clear_look_down
        )

        # Determine gaze direction label (Antoine Lamé style: Center / Left / Right / Up / Down)
        if looking_straight:
            direction = "CENTER (LOOKING AT CAMERA)"
        elif abs(self.smooth_head_offset) > 0.17:
            direction = "LOOKING AWAY (HEAD TURNED)"
        elif self.smooth_h > 0.62:
            direction = "LOOKING RIGHT"
        elif self.smooth_h < 0.32:
            direction = "LOOKING LEFT"
        elif self.smooth_v < 0.24:
            direction = "LOOKING UP"
        else:
            direction = "LOOKING DOWN"

        # Continuous confidence metric
        h_dev = abs(self.smooth_h - 0.46) / 0.18
        v_dev = abs(self.smooth_v - 0.44) / 0.22
        head_dev = abs(self.smooth_head_offset) / 0.17
        confidence = float(np.clip(1.0 - 0.5 * h_dev - 0.25 * v_dev - 0.25 * head_dev, 0.0, 1.0))

        return {
            "face_detected": True,
            "looking_at_camera": looking_straight,
            "clear_averted": clear_averted,
            "direction": direction,
            "horizontal_ratio": self.smooth_h,
            "vertical_ratio": self.smooth_v,
            "head_offset": self.smooth_head_offset,
            "confidence": confidence,
            "iris_left": final_pl,
            "iris_right": final_pr
        }


class ConfettiEffect:
    """
    Celebratory animated confetti particle system on Player 1's side of the screen.
    Simulates floating, swaying, and spinning confetti flakes and sparkles.
    """
    COLORS = [
        (0, 215, 255),   # Gold / Yellow
        (50, 255, 100),  # Emerald Green
        (255, 255, 0),   # Bright Cyan
        (200, 50, 255),  # Magenta / Hot Pink
        (255, 180, 0),   # Sky Blue
        (0, 140, 255),   # Vibrant Orange
        (255, 50, 150),  # Neon Violet
        (0, 255, 255),   # Pure Yellow
        (255, 255, 255), # White Star
    ]

    def __init__(self, num_particles=150):
        self.num_particles = num_particles
        self.particles = []
        self._initialized = False

    def reset(self, width, height):
        self.particles = []
        max_x = int(width * 0.49)
        for _ in range(self.num_particles):
            self.particles.append(self._spawn_particle(max_x, height, random_y=True))
        self._initialized = True

    def _spawn_particle(self, max_x, height, random_y=False):
        return {
            "x": float(random.randint(10, max(20, max_x))),
            "y": float(random.randint(-height, 0)) if not random_y else float(random.randint(-height // 3, height)),
            "vx": random.uniform(-1.0, 1.0),
            "vy": random.uniform(3.5, 7.5),
            "w": float(random.choice([6, 8, 10, 12])),
            "h": float(random.choice([4, 6, 8, 10])),
            "angle": float(random.randint(0, 360)),
            "v_rot": random.uniform(-7.0, 7.0),
            "color": random.choice(self.COLORS),
            "sway_phase": random.uniform(0.0, 6.28),
            "is_sparkle": random.random() < 0.22
        }

    def update_and_draw(self, frame_or_overlay, width, height, current_time):
        max_x = int(width * 0.49)
        if not self._initialized or len(self.particles) < self.num_particles:
            self.reset(width, height)

        for p in self.particles:
            # Physics: gravity, sway, rotation
            p["y"] += p["vy"]
            p["x"] += p["vx"] + math.sin(current_time * 3.5 + p["sway_phase"]) * 1.5
            p["angle"] += p["v_rot"]

            # Wrap around when falling past bottom
            if p["y"] > height + 20:
                p["y"] = float(random.randint(-40, -10))
                p["x"] = float(random.randint(10, max_x))
                p["vy"] = random.uniform(3.5, 7.5)

            # Keep within Player 1's side (left half)
            if p["x"] < 8:
                p["x"] = 8.0
                p["vx"] = abs(p["vx"])
            elif p["x"] > max_x:
                p["x"] = float(max_x)
                p["vx"] = -abs(p["vx"])

            x, y = int(p["x"]), int(p["y"])
            if y < -15 or y >= height:
                continue

            if p["is_sparkle"]:
                r = int(p["w"] / 2.5)
                cv2.circle(frame_or_overlay, (x, y), max(2, r), p["color"], -1)
            else:
                cos_a = math.cos(math.radians(p["angle"]))
                sin_a = math.sin(math.radians(p["angle"]))
                hw = p["w"] / 2.0
                hh = p["h"] / 2.0
                pts = np.array([
                    [int(x - hw * cos_a + hh * sin_a), int(y - hw * sin_a - hh * cos_a)],
                    [int(x + hw * cos_a + hh * sin_a), int(y + hw * sin_a - hh * cos_a)],
                    [int(x + hw * cos_a - hh * sin_a), int(y + hw * sin_a + hh * cos_a)],
                    [int(x - hw * cos_a - hh * sin_a), int(y - hw * sin_a + hh * cos_a)]
                ], dtype=np.int32)
                cv2.fillPoly(frame_or_overlay, [pts], p["color"])


# Global confetti effect instance
confetti_effect = ConfettiEffect(num_particles=150)


class RockPaperScissorsGame:
    """
    Rock-Paper-Scissors Referee for Drone Control.
    The application starts in a WAITING state where NO flight gestures are recognized.
    When the user presses [R] on the keyboard:
      - Starts a 5-second countdown (5... 4... 3... 2... 1... SHOOT!).
      - Reads each player's gesture:
          * Rock: Closed_Fist (✊)
          * Paper: Open_Palm (✋)
          * Scissors: Victory (✌️)
      - If 2 players are detected: Player 1 (Left) vs Player 2 (Right).
      - If 1 player is detected: Player 1 (User) vs Drone AI Opponent.
      - Resolves the winner according to classic RPS rules.
      - Displays the winner and grants exclusive drone flight gesture control to the winner!
      - Press [R] at any time for a rematch.
    """
    GESTURE_MAP = {
        "Closed_Fist": "ROCK",
        "Open_Palm": "PAPER",
        "Victory": "SCISSORS"
    }

    EMOJI_MAP = {
        "ROCK": "✊ ROCK",
        "PAPER": "✋ PAPER",
        "SCISSORS": "✌️ SCISSORS",
        "NONE": "⏳ WAITING"
    }

    def __init__(self):
        self.mp_face_detection = mp.solutions.face_detection
        self.face_detector = self.mp_face_detection.FaceDetection(min_detection_confidence=0.5, model_selection=0)

        # Game state: "WAITING", "COUNTDOWN", "WINNER"
        self.state = "WAITING"
        self.active_controller = None  # None until RPS is won ("P1" or "P2")
        self.winner = None             # "P1", "P2", "TIE", or None
        self.winner_announce_time = 0.0

        # Countdown management (5 seconds)
        self.countdown_start = 0.0
        self.countdown_duration = 5.0
        self.face_count = 0
        self.mode = "2_PLAYER"

        # Moves
        self.p1_move = "NONE"
        self.p2_move = "NONE"
        self.p1_box = None
        self.p2_box = None
        self.duel_result_text = "Press [R] on keyboard to start Rock-Paper-Scissors!"

    def start_duel(self):
        """Starts the 5-second countdown duel when user presses key [R]."""
        self.state = "COUNTDOWN"
        self.countdown_start = time.time()
        self.countdown_duration = 5.0
        self.winner = None
        self.active_controller = None
        self.p1_move = "NONE"
        self.p2_move = "NONE"
        self.duel_result_text = "⚔️ DUEL STARTED! 5-second countdown..."
        print("\n🎮 [RPS DUEL] Rock-Paper-Scissors started! Counting down from 5 seconds...")

    def reset_duel(self):
        """Alias for start_duel() to rematch."""
        self.start_duel()

    def process(self, frame_bgr, hands_data):
        """
        Process frame for faces and hand gestures.
        hands_data: list of dicts: [{'label': str, 'score': float, 'cx': float, 'cy': float, 'landmarks': ...}]
        """
        h, w, _ = frame_bgr.shape
        now = time.time()

        # 1. Detect faces
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        detection_result = self.face_detector.process(rgb)

        detected_faces = []
        if detection_result.detections:
            for d in detection_result.detections:
                bb = d.location_data.relative_bounding_box
                x1 = int(max(0, bb.xmin * w))
                y1 = int(max(0, bb.ymin * h))
                box_w = int(bb.width * w)
                box_h = int(bb.height * h)
                x2 = min(w, x1 + box_w)
                y2 = min(h, y1 + box_h)
                cx = (x1 + x2) / 2.0
                detected_faces.append({"box": (x1, y1, x2, y2), "cx": cx})

        detected_faces = sorted(detected_faces, key=lambda f: f["cx"])
        self.face_count = len(detected_faces)

        if self.face_count >= 2:
            self.mode = "2_PLAYER"
            p1_face = detected_faces[0]
            p2_face = detected_faces[1]
            self.p1_box = p1_face["box"]
            self.p2_box = p2_face["box"]
            mid_x = (p1_face["cx"] + p2_face["cx"]) / 2.0
        elif self.face_count == 1:
            p1_face = detected_faces[0]
            self.p1_box = p1_face["box"]
            self.p2_box = None
            mid_x = w / 2.0
        else:
            self.p1_box = None
            self.p2_box = None
            mid_x = w / 2.0

        # Classify RPS moves for ALL detected hands using labels + finger joint analysis
        classified_hands = []
        for hand in hands_data:
            move = classify_rps_hand(hand)
            classified_hands.append({
                "cx": hand["cx"],
                "cy": hand.get("cy", 0),
                "move": move,
                "landmarks": hand.get("landmarks"),
                "label": hand.get("label", "None"),
                "score": hand.get("score", 0.0)
            })

        # Sort hands left to right across the camera screen
        classified_hands = sorted(classified_hands, key=lambda h_item: h_item["cx"])

        p1_detected_move = "NONE"
        p2_detected_move = "NONE"
        p1_hand_pos = None
        p2_hand_pos = None

        if len(classified_hands) >= 2:
            # Two or more hands detected:
            # Leftmost hand is ALWAYS Player 1, Rightmost hand is ALWAYS Player 2!
            p1_h = classified_hands[0]
            p2_h = classified_hands[-1]
            p1_detected_move = p1_h["move"]
            p2_detected_move = p2_h["move"]
            p1_hand_pos = (int(p1_h["cx"]), int(p1_h["cy"]))
            p2_hand_pos = (int(p2_h["cx"]), int(p2_h["cy"]))
            self.mode = "2_PLAYER"
        elif len(classified_hands) == 1:
            single_h = classified_hands[0]
            if single_h["cx"] < mid_x:
                p1_detected_move = single_h["move"]
                p1_hand_pos = (int(single_h["cx"]), int(single_h["cy"]))
            else:
                p2_detected_move = single_h["move"]
                p2_hand_pos = (int(single_h["cx"]), int(single_h["cy"]))
                self.mode = "2_PLAYER"

        # State Machine
        if self.state == "WAITING":
            return {
                "active": True,
                "state": "WAITING",
                "face_count": self.face_count,
                "countdown_remaining": 5.0,
                "winner": None,
                "active_controller": None,
                "p1_move": p1_detected_move,
                "p2_move": p2_detected_move,
                "p1_box": self.p1_box,
                "p2_box": self.p2_box,
                "p1_hand_pos": p1_hand_pos,
                "p2_hand_pos": p2_hand_pos,
                "mode": self.mode,
                "message": "Press [R] on keyboard to start Rock-Paper-Scissors!"
            }

        elif self.state == "COUNTDOWN":
            elapsed = now - self.countdown_start
            remaining = max(0.0, self.countdown_duration - elapsed)

            if p1_detected_move != "NONE":
                self.p1_move = p1_detected_move
            if p2_detected_move != "NONE":
                self.p2_move = p2_detected_move
                self.mode = "2_PLAYER"

            if remaining <= 0.0:
                self.winner = "P1"
                self.active_controller = "P1"
                self.state = "WINNER"
                self._resolve_winner(now)

            return {
                "active": True,
                "state": self.state,
                "face_count": self.face_count,
                "countdown_remaining": remaining,
                "winner": self.winner,
                "active_controller": self.active_controller,
                "p1_move": p1_detected_move if p1_detected_move != "NONE" else self.p1_move,
                "p2_move": p2_detected_move if p2_detected_move != "NONE" else self.p2_move,
                "p1_box": self.p1_box,
                "p2_box": self.p2_box,
                "p1_hand_pos": p1_hand_pos,
                "p2_hand_pos": p2_hand_pos,
                "mode": self.mode,
                "message": self.duel_result_text
            }

        elif self.state == "WINNER":
            return {
                "active": True,
                "state": "WINNER",
                "face_count": self.face_count,
                "countdown_remaining": 0.0,
                "winner": self.winner,
                "active_controller": self.active_controller,
                "p1_move": self.p1_move,
                "p2_move": self.p2_move,
                "p1_box": self.p1_box,
                "p2_box": self.p2_box,
                "p1_hand_pos": p1_hand_pos,
                "p2_hand_pos": p2_hand_pos,
                "mode": self.mode,
                "message": self.duel_result_text
            }

        return {
            "active": True,
            "state": "WAITING",
            "face_count": self.face_count,
            "countdown_remaining": 0.0,
            "winner": None,
            "active_controller": None,
            "p1_move": "NONE",
            "p2_move": "NONE",
            "p1_box": None,
            "p2_box": None,
            "p1_hand_pos": None,
            "p2_hand_pos": None,
            "mode": "SOLO",
            "message": ""
        }

    def _resolve_winner(self, now):
        """Hardcoded: Player 1 always wins unconditionally without showing gestures."""
        self.winner_announce_time = now
        self.winner = "P1"
        self.active_controller = "P1"
        self.duel_result_text = "PLAYER 1 WINS! CONTROL GRANTED TO PLAYER 1!"
        print("\n🏆 [RPS DUEL] PLAYER 1 WINS! Control granted to Player 1.")


def draw_hud(frame, telemetry, step_dist, gesture_info, estop, gesture_enabled, movement_enabled, safety_info, gaze_info=None, rps_info=None, last_action="", haptic_active=False):
    """Draws rich aviation HUD with gesture indicators directly onto video frame."""
    h, w, _ = frame.shape
    overlay = frame.copy()
    cx, cy = w // 2, h // 2

    # Check if currently in Rock-Paper-Scissors game (Waiting or Countdown)
    rps_active = bool(rps_info and rps_info.get("active", False))
    rps_state = rps_info.get("state", "WAITING") if rps_active else None
    in_rps_game = rps_active and (rps_state in ("WAITING", "COUNTDOWN"))

    # When NOT in the RPS game, draw all drone flight UI instruments:
    if not in_rps_game:
        # Center Crosshair
        cv2.line(overlay, (cx - 20, cy), (cx + 20, cy), (0, 255, 0), 2)
        cv2.line(overlay, (cx, cy - 20), (cx, cy + 20), (0, 255, 0), 2)
        cv2.circle(overlay, (cx, cy), 4, (0, 255, 0), -1)

        # Top Status Bar
        cv2.rectangle(overlay, (0, 0), (w, 50), (20, 20, 20), -1)

        # Drone Connection Status
        if telemetry.get("simulator", False):
            dji_status = "SIMULATOR (WEBCAM)"
            dji_color = (255, 200, 0)
        else:
            dji_status = "CONNECTED" if telemetry["connected"] else "OFFLINE"
            dji_color = (0, 255, 0) if telemetry["connected"] else (0, 0, 255)
        cv2.putText(overlay, f"DRONE: {dji_status}", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, dji_color, 2)

        # Telemetry: Altitude & Heading
        alt_txt = f"ALT: {telemetry['altitude']:.2f} m"
        hdg_txt = f"HDG: {telemetry['heading']:.1f}°"
        cv2.putText(overlay, alt_txt, (cx - 190, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2)
        cv2.putText(overlay, hdg_txt, (cx - 30, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 2)

        # Speed & Step Badges
        cur_spd = telemetry.get("speed", 0.35)
        spd_txt = f"SPD: {cur_spd:.2f}m/s"
        cv2.putText(overlay, spd_txt, (cx + 120, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 255, 180), 2)

        if isinstance(step_dist, (tuple, list)):
            step_fb, step_vert = step_dist
        else:
            step_fb, step_vert = step_dist, 0.10
        step_fb_cm = int(round(step_fb * 100))
        step_vert_cm = int(round(step_vert * 100))
        step_txt = f"STEP: FB {step_fb_cm}cm | UD {step_vert_cm}cm"
        cv2.putText(overlay, step_txt, (w - 290, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (0, 220, 255), 2)

        # Dry Run / Movement Disabled Warning Banner
        if not movement_enabled:
            cv2.rectangle(overlay, (cx - 250, 54), (cx + 250, 86), (0, 140, 255), -1)
            cv2.putText(overlay, "DRY RUN MODE: MOVEMENT LOCKED [Press M to Unlock]", (cx - 235, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)

        # --- Gesture Recognition HUD Card (Top Left) ---
        card_x, card_y, card_w, card_h = 20, 65, 410, 110
        cv2.rectangle(overlay, (card_x, card_y), (card_x + card_w, card_y + card_h), (25, 25, 30), -1)
        cv2.rectangle(overlay, (card_x, card_y), (card_x + card_w, card_y + card_h), (80, 80, 80), 1)

        label = gesture_info.get("label", "None")
        score = gesture_info.get("score", 0.0)
        action = gesture_info.get("action", "HOVER")

        sim_suffix = " [SIMULATED]" if not movement_enabled else ""

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
        elif label == "RPS_Locked":
            g_badge = "⚔️ GESTURES: LOCKED (PLAY RPS)"
            g_color = (0, 200, 255)
            action_txt = action if action else "ACTION: PRESS [R] TO START RPS DUEL"
            action_color = (0, 220, 255)
        elif label == "RPS_Match":
            g_badge = "⚔️ RPS DUEL IN PROGRESS"
            g_color = (0, 220, 255)
            action_txt = "FLIGHT GESTURES: LOCKED FOR DUEL"
            action_color = (0, 220, 255)
        else:
            if label == "Thumb_Up":
                g_badge = f"👍 THUMB UP ({score:.0%})"
                g_color = (0, 255, 0) if movement_enabled else (0, 200, 255)
                action_txt = f"ACTION: CLIMBING (+{step_vert_cm}cm){sim_suffix}"
                action_color = (0, 255, 0) if movement_enabled else (0, 200, 255)
            elif label == "Thumb_Down":
                g_badge = f"👎 THUMB DOWN ({score:.0%})"
                g_color = (0, 140, 255)
                action_txt = f"ACTION: DESCENDING (-{step_vert_cm}cm){sim_suffix}"
                action_color = (0, 140, 255)
            elif label == "Closing_Hand":
                spd_val = gesture_info.get("speed", 0.35)
                spd_tier = gesture_info.get("speed_tier", "NORMAL")
                g_badge = f"✊ CLOSING HAND [{spd_tier}]"
                g_color = (0, 255, 180) if movement_enabled else (0, 220, 255)
                action_txt = f"ACTION: FORWARD (+{step_fb_cm}cm @ {spd_val:.2f}m/s){sim_suffix}"
                action_color = (0, 255, 180) if movement_enabled else (0, 220, 255)
            elif label == "Opening_Hand":
                spd_val = gesture_info.get("speed", 0.35)
                spd_tier = gesture_info.get("speed_tier", "NORMAL")
                g_badge = f"✋ OPENING HAND [{spd_tier}]"
                g_color = (0, 165, 255) if movement_enabled else (100, 200, 255)
                action_txt = f"ACTION: BACKWARD (-{step_fb_cm}cm @ {spd_val:.2f}m/s){sim_suffix}"
                action_color = (0, 165, 255) if movement_enabled else (100, 200, 255)
            elif label == "Open_Palm":
                g_badge = f"✋ HAND OPEN ({score:.0%})"
                g_color = (180, 220, 255)
                action_txt = "READY: Close hand (fist) -> Forward"
                action_color = (200, 200, 200)
            elif label == "Closed_Fist":
                g_badge = f"✊ HAND CLOSED ({score:.0%})"
                g_color = (180, 255, 220)
                action_txt = "READY: Open hand -> Backward"
                action_color = (200, 200, 200)
            else:
                g_badge = f"HAND: {label} ({score:.0%})" if label != "None" else "HAND: None (Hovering)"
                g_color = (200, 200, 200)
                action_txt = "ACTION: HOVER IN PLACE"
                action_color = (220, 220, 220)

        cv2.putText(overlay, g_badge, (card_x + 12, card_y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, g_color, 2)
        cv2.putText(overlay, action_txt, (card_x + 12, card_y + 68), cv2.FONT_HERSHEY_SIMPLEX, 0.58, action_color, 2)

        # Indicator light
        ind_color = g_color if (gesture_enabled and not estop) else (0, 0, 255)
        cv2.circle(overlay, (card_x + card_w - 24, card_y + 30), 8, ind_color, -1)

        # --- Safety Boundary Box HUD Card (Top Right) ---
        safe_w, safe_h = 360, 110
        safe_x, safe_y = max(card_x + card_w + 10, w - safe_w - 20), 65
        cv2.rectangle(overlay, (safe_x, safe_y), (safe_x + safe_w, safe_y + safe_h), (25, 25, 30), -1)
        cv2.rectangle(overlay, (safe_x, safe_y), (safe_x + safe_w, safe_y + safe_h), (80, 80, 80), 1)

        max_fb_cm = int(round(safety_info.get("max_fb", 1.00) * 100))
        max_vert_cm = int(round(safety_info.get("max_vert", 0.30) * 100))
        max_lat_cm = int(round(safety_info.get("max_lat", 0.50) * 100))

        if safety_info.get("set", False):
            rx = int(round(safety_info.get("x", 0.0) * 100))
            ry = int(round(safety_info.get("y", 0.0) * 100))
            rz = int(round(safety_info.get("z", 0.0) * 100))

            is_limit = (abs(rx) >= max_fb_cm or abs(rz) >= max_vert_cm or abs(ry) >= max_lat_cm)
            is_near = (abs(rx) >= int(max_fb_cm * 0.75) or abs(rz) >= int(max_vert_cm * 0.75) or abs(ry) >= int(max_lat_cm * 0.75))

            if is_limit:
                s_color = (0, 0, 255)
                b_status = "LIMIT REACHED"
            elif is_near:
                s_color = (0, 165, 255)
                b_status = "NEAR BOUNDARY"
            else:
                s_color = (0, 255, 0)
                b_status = "SAFE"

            cv2.putText(overlay, f"SAFETY BOX: ACTIVE (X:±{max_fb_cm} Z:±{max_vert_cm}cm)", (safe_x + 12, safe_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, s_color, 2)
            cv2.putText(overlay, f"OFFSET: X:{rx:+d} Y:{ry:+d} Z:{rz:+d} cm", (safe_x + 12, safe_y + 56), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (220, 220, 220), 1)
            cv2.putText(overlay, f"STATUS: [{b_status}] Limits: X±{max_fb_cm} Z±{max_vert_cm}", (safe_x + 12, safe_y + 82), cv2.FONT_HERSHEY_SIMPLEX, 0.44, s_color, 2)
            cv2.putText(overlay, "Press [H] to Re-anchor | [K] to Clear", (safe_x + 12, safe_y + 102), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (160, 160, 160), 1)
            cv2.circle(overlay, (safe_x + safe_w - 20, safe_y + 26), 7, s_color, -1)
        else:
            cv2.putText(overlay, f"SAFETY BOX: UNSET (X:±{max_fb_cm} Z:±{max_vert_cm}cm)", (safe_x + 12, safe_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 140, 255), 2)
            cv2.putText(overlay, "Press [H] to Set Default Point", (safe_x + 12, safe_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.54, (255, 255, 255), 2)
            cv2.putText(overlay, f"Limits: Fwd/Bwd ±{max_fb_cm}cm | Alt ±{max_vert_cm}cm", (safe_x + 12, safe_y + 84), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (180, 180, 180), 1)
            cv2.putText(overlay, "[H] Anchor Default Point", (safe_x + 12, safe_y + 102), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (140, 140, 140), 1)
            cv2.circle(overlay, (safe_x + safe_w - 20, safe_y + 26), 7, (0, 140, 255), -1)

        # --- Gaze Tracking HUD Card (Below Gesture Card) ---
        if gaze_info is not None:
            gaze_x, gaze_y, gaze_w, gaze_h = card_x, card_y + card_h + 10, card_w, 82
            cv2.rectangle(overlay, (gaze_x, gaze_y), (gaze_x + gaze_w, gaze_y + gaze_h), (25, 25, 30), -1)
            cv2.rectangle(overlay, (gaze_x, gaze_y), (gaze_x + gaze_w, gaze_y + gaze_h), (80, 80, 80), 1)

            face_found = gaze_info.get("face_detected", False)
            is_looking = gaze_info.get("looking_at_camera", False)
            direction = gaze_info.get("direction", "NO FACE")
            conf = gaze_info.get("confidence", 0.0)
            h_ratio = gaze_info.get("horizontal_ratio", 0.50)
            v_ratio = gaze_info.get("vertical_ratio", 0.50)

            if not face_found:
                gz_title = "👀 GAZE: NO FACE DETECTED"
                gz_color = (130, 130, 130)
                gz_sub = "Status: Position face toward camera"
                gz_sub_col = (160, 160, 160)
            elif is_looking:
                gz_title = "👀 GAZE: LOOKING AT CAMERA"
                gz_color = (0, 255, 120)
                gz_sub = f"Status: {direction} (H:{h_ratio:.2f}, V:{v_ratio:.2f}, {conf:.0%})"
                gz_sub_col = (0, 255, 180)
            else:
                gz_title = f"👀 GAZE: {direction}"
                gz_color = (0, 140, 255)
                gz_sub = f"Status: AVERTED (H:{h_ratio:.2f}, V:{v_ratio:.2f}, {conf:.0%})"
                gz_sub_col = (0, 180, 255)

            cv2.putText(overlay, gz_title, (gaze_x + 12, gaze_y + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.60, gz_color, 2)
            cv2.putText(overlay, gz_sub, (gaze_x + 12, gaze_y + 58), cv2.FONT_HERSHEY_SIMPLEX, 0.45, gz_sub_col, 1)
            cv2.circle(overlay, (gaze_x + gaze_w - 24, gaze_y + 26), 8, gz_color, -1)

            # Draw subtle eye iris tracking reticles directly on eyes if detected
            iris_l = gaze_info.get("iris_left")
            iris_r = gaze_info.get("iris_right")
            reticle_color = (0, 255, 120) if is_looking else (0, 165, 255)
            if iris_l and iris_l[0] > 0 and iris_l[1] > 0:
                cv2.circle(overlay, iris_l, 4, reticle_color, -1)
                cv2.circle(overlay, iris_l, 8, reticle_color, 1)
            if iris_r and iris_r[0] > 0 and iris_r[1] > 0:
                cv2.circle(overlay, iris_r, 4, reticle_color, -1)
                cv2.circle(overlay, iris_r, 8, reticle_color, 1)

        # --- Haptic Vibration Alert Indicator ---
        if haptic_active:
            hap_w, hap_h = 360, 48
            hap_x = w - hap_w - 20
            hap_y = 185
            cv2.rectangle(overlay, (hap_x, hap_y), (hap_x + hap_w, hap_y + hap_h), (0, 0, 180), -1)
            cv2.rectangle(overlay, (hap_x, hap_y), (hap_x + hap_w, hap_y + hap_h), (0, 255, 255), 2)
            cv2.putText(overlay, "⚡ HAPTIC MOTOR BUZZ ACTIVE", (hap_x + 14, hap_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)

    # --- Rock-Paper-Scissors Duel Overlay ---
    if rps_info and rps_info.get("active", False):
        state = rps_info.get("state", "WAITING")
        p1_box = rps_info.get("p1_box")
        p2_box = rps_info.get("p2_box")
        p1_move = rps_info.get("p1_move", "NONE")
        p2_move = rps_info.get("p2_move", "NONE")
        winner = rps_info.get("winner")
        active_ctrl = rps_info.get("active_controller")
        msg = rps_info.get("message", "")
        mode = rps_info.get("mode", "2_PLAYER")

        # Draw Player 1 Face Box or Badge (Left)
        if p1_box:
            bx1, by1, bx2, by2 = p1_box
            is_p1_winner = (active_ctrl == "P1")
            b_col = (0, 255, 120) if is_p1_winner else (0, 200, 255)
            cv2.rectangle(overlay, (bx1, by1), (bx2, by2), b_col, 3 if is_p1_winner else 2)

            tag_txt = "PLAYER 1 (PILOT IN CONTROL 🎮)" if is_p1_winner else "PLAYER 1"
            cv2.rectangle(overlay, (bx1, max(0, by1 - 30)), (bx1 + 280, by1), (20, 20, 20), -1)
            cv2.putText(overlay, tag_txt, (bx1 + 6, by1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, b_col, 2)
        else:
            p1_x, p1_y, p1_w, p1_h = 20, 185, 270, 52
            is_p1_winner = (active_ctrl == "P1")
            p1_col = (0, 255, 120) if is_p1_winner else (0, 200, 255)
            cv2.rectangle(overlay, (p1_x, p1_y), (p1_x + p1_w, p1_y + p1_h), (20, 20, 20), -1)
            cv2.rectangle(overlay, (p1_x, p1_y), (p1_x + p1_w, p1_y + p1_h), p1_col, 2)
            cv2.putText(overlay, "PLAYER 1 (PILOT 🎮)" if is_p1_winner else "PLAYER 1 (YOU 👤)", (p1_x + 8, p1_y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.50, p1_col, 2)

        # Draw Player 2 Face Box or AI Opponent Badge (Right)
        if p2_box:
            bx1, by1, bx2, by2 = p2_box
            is_p2_winner = (active_ctrl == "P2")
            b_col = (0, 255, 120) if is_p2_winner else (255, 150, 0)
            cv2.rectangle(overlay, (bx1, by1), (bx2, by2), b_col, 3 if is_p2_winner else 2)

            tag_txt = "PLAYER 2 (PILOT IN CONTROL 🎮)" if is_p2_winner else "PLAYER 2"
            cv2.rectangle(overlay, (bx1, max(0, by1 - 30)), (bx1 + 280, by1), (20, 20, 20), -1)
            cv2.putText(overlay, tag_txt, (bx1 + 6, by1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, b_col, 2)
        elif mode == "2_PLAYER" or p2_move != "NONE" or p2_h_pos:
            p2_x, p2_y, p2_w, p2_h = w - 290, 185, 270, 52
            is_p2_winner = (active_ctrl == "P2")
            p2_col = (0, 255, 120) if is_p2_winner else (255, 150, 0)
            cv2.rectangle(overlay, (p2_x, p2_y), (p2_x + p2_w, p2_y + p2_h), (20, 20, 20), -1)
            cv2.rectangle(overlay, (p2_x, p2_y), (p2_x + p2_w, p2_y + p2_h), p2_col, 2)
            cv2.putText(overlay, "PLAYER 2 (PILOT 🎮)" if is_p2_winner else "PLAYER 2 (OPPONENT 👤)", (p2_x + 8, p2_y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.50, p2_col, 2)
        else:
            ai_x, ai_y, ai_w, ai_h = w - 290, 185, 270, 52
            is_ai_winner = (active_ctrl == "P2")
            ai_col = (0, 255, 120) if is_ai_winner else (180, 180, 180)
            cv2.rectangle(overlay, (ai_x, ai_y), (ai_x + ai_w, ai_y + ai_h), (20, 20, 20), -1)
            cv2.rectangle(overlay, (ai_x, ai_y), (ai_x + ai_w, ai_y + ai_h), ai_col, 2)
            cv2.putText(overlay, "DRONE AI (PILOT 🎮)" if is_ai_winner else "OPPONENT: DRONE AI 🤖", (ai_x + 8, ai_y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.50, ai_col, 2)

        # Draw on-screen hand markers for live tracking on both players (without showing gesture)
        p1_h_pos = rps_info.get("p1_hand_pos")
        p2_h_pos = rps_info.get("p2_hand_pos")
        if p1_h_pos and p1_h_pos[0] > 0 and p1_h_pos[1] > 0:
            hx, hy = p1_h_pos
            cv2.circle(overlay, (hx, hy), 24, (0, 255, 120), 2)
            cv2.putText(overlay, "PLAYER 1", (max(10, hx - 45), max(30, hy - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 255, 120), 2)
        if p2_h_pos and p2_h_pos[0] > 0 and p2_h_pos[1] > 0:
            hx, hy = p2_h_pos
            cv2.circle(overlay, (hx, hy), 24, (0, 200, 255), 2)
            cv2.putText(overlay, "PLAYER 2", (max(10, hx - 45), max(30, hy - 25)), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 200, 255), 2)

        # Center Arena Banner
        banner_w, banner_h = 720, 92
        banner_x = cx - banner_w // 2
        banner_y = 120
        cv2.rectangle(overlay, (banner_x, banner_y), (banner_x + banner_w, banner_y + banner_h), (15, 15, 20), -1)
        b_border_col = (0, 255, 120) if state == "WINNER" and winner in ("P1", "P2") else (0, 220, 255)
        cv2.rectangle(overlay, (banner_x, banner_y), (banner_x + banner_w, banner_y + banner_h), b_border_col, 2)

        if state == "WAITING":
            cv2.putText(overlay, "⚔️  ROCK-PAPER-SCISSORS DUEL FOR DRONE CONTROL", (banner_x + 45, banner_y + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 220, 255), 2)
            cv2.putText(overlay, "PRESS [R] ON KEYBOARD TO START 5s COUNTDOWN!", (banner_x + 55, banner_y + 72), cv2.FONT_HERSHEY_SIMPLEX, 0.64, (0, 255, 255), 2)

        elif state == "COUNTDOWN":
            rem = rps_info.get("countdown_remaining", 0.0)
            if rem > 4.0:
                step_txt = "5... GET READY!"
                step_color = (0, 200, 255)
            elif rem > 3.0:
                step_txt = "4... ROCK!"
                step_color = (0, 220, 255)
            elif rem > 2.0:
                step_txt = "3... PAPER!"
                step_color = (0, 255, 200)
            elif rem > 1.0:
                step_txt = "2... SCISSORS!"
                step_color = (0, 255, 120)
            else:
                step_txt = "1... SHOOT!"
                step_color = (0, 255, 255)

            cv2.putText(overlay, f"⚔️  DUEL COUNTDOWN: {rem:.1f}s", (banner_x + 210, banner_y + 32), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (200, 200, 200), 2)
            cv2.putText(overlay, step_txt, (banner_x + 200, banner_y + 74), cv2.FONT_HERSHEY_SIMPLEX, 0.95, step_color, 3)

        elif state == "WINNER":
            win_txt = "👑 PLAYER 1 WINS! CONTROL GRANTED TO PLAYER 1!"
            cv2.putText(overlay, "🎮 DRONE CONTROL DUEL RESULT:", (banner_x + 30, banner_y + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (200, 200, 200), 2)
            cv2.putText(overlay, win_txt, (banner_x + 30, banner_y + 68), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 255, 120), 2)

        # Celebratory Confetti on Player 1's side (Left side: 0 to w/2)
        if (state == "WINNER" and winner == "P1") or active_ctrl == "P1":
            confetti_effect.update_and_draw(overlay, w, h, time.time())
            cv2.putText(overlay, "🎉 WINNER! 👑", (30, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.70, (0, 255, 120), 2)

    # Bottom Control Bar & Last Action Banner (Only when NOT in RPS game)
    if not in_rps_game:
        cv2.rectangle(overlay, (0, h - 45), (w, h), (20, 20, 20), -1)
        controls_txt = "[R] RPS Rematch | [H] Anchor Pt | [M] Move Lock | [I] Invert Fwd | [SPACE] E-Stop | [G] Gestures | [W/S/A/D] Move | [T] Takeoff | [L] Land"
        cv2.putText(overlay, controls_txt, (15, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (200, 200, 200), 1)

        # Last Action Banner
        if last_action:
            color = (0, 0, 255) if "BLOCKED" in last_action else (0, 255, 200)
            cv2.putText(overlay, f"> {last_action}", (20, h - 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)

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
    parser.add_argument("--port", type=int, default=8080, help="Android REST Server Port (default: 8080)")
    parser.add_argument("--step-fb", type=float, default=0.40, help="Step distance for forward/backward in meters (default: 0.40 = 40cm)")
    parser.add_argument("--step-vert", type=float, default=0.10, help="Step distance for up/down in meters (default: 0.10 = 10cm)")
    parser.add_argument("--step", type=float, default=None, help="Forward/backward step distance override in meters")
    parser.add_argument("--boundary-fb", type=float, default=1.00, help="Forward/backward safety boundary limit in meters (default: 1.00 = 1m)")
    parser.add_argument("--boundary-vert", type=float, default=0.30, help="Up/down altitude safety boundary limit in meters (default: 0.30 = 30cm)")
    parser.add_argument("--boundary-lat", type=float, default=0.50, help="Lateral safety boundary limit in meters (default: 0.50 = 50cm)")
    parser.add_argument("--boundary", type=float, default=None, help="Uniform safety boundary override in meters")
    parser.add_argument("--speed", type=float, default=0.35, help="Base speed in m/s (default: 0.35)")
    parser.add_argument("--min-speed", type=float, default=0.15, help="Minimum speed for slow gestures in m/s (default: 0.15)")
    parser.add_argument("--max-speed", type=float, default=0.80, help="Maximum speed for fast gestures in m/s (default: 0.80)")
    parser.add_argument("--model", default="gesture_recognizer.task", help="MediaPipe model task path")
    parser.add_argument("--min-score", type=float, default=0.65, help="Minimum gesture recognition confidence (default: 0.65)")
    parser.add_argument("--hold-time", type=float, default=0.25, help="Debounce hold time in seconds (default: 0.25)")
    parser.add_argument("--rtsp", default="", help="Custom RTSP URL (leave empty to auto-detect)")
    parser.add_argument("--dry-run", action="store_true", help="Start with drone movement disabled (dry run mode)")
    parser.add_argument("--invert-forward", action="store_true", help="Invert forward/backward translation direction")
    parser.add_argument("--sim", action="store_true", help="Run in simulator mode using laptop webcam (no drone needed)")
    parser.add_argument("--webcam", action="store_true", help="Alias for --sim")
    parser.add_argument("--camera", type=int, default=0, help="Laptop webcam device index (default: 0)")
    parser.add_argument("--no-mirror", action="store_true", help="Disable horizontal flip (mirroring) on webcam")
    parser.add_argument("--arduino-ip", default="10.114.198.176", help="Arduino vibration motor IP (default: 10.114.198.176)")
    parser.add_argument("--arduino-port", type=int, default=5005, help="Arduino vibration motor UDP port (default: 5005)")
    args = parser.parse_args()

    is_simulator = args.sim or args.webcam

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

    if is_simulator:
        print("=" * 65)
        print("   DJI GESTURE SIMULATOR (LAPTOP WEBCAM)")
        print("=" * 65)
        print("Initializing Virtual Drone & Local Simulation...")
        client = MockDJIControlClient(ip="127.0.0.1", port=port, invert_forward=args.invert_forward)
    else:
        print("=" * 65)
        print("   DJI UNIFIED GESTURE CONTROLLER (MediaPipe Thumbs Up/Down)")
        print("=" * 65)
        print(f"Connecting to REST API at http://{host}:{port}...")

        try:
            client = DJIControlClient(ip=host, port=port, invert_forward=args.invert_forward)
            print("Connected to Flight REST Server successfully!")
        except Exception as e:
            print(f"\nConnection Error: {e}")
            print("\nTroubleshooting:")
            print("  1. Is the DJIUnifiedGestures Android app open on your phone?")
            print("  2. If using Wi-Fi, pass: --host <PHONE_IP> (e.g. --host 192.168.2.8)")
            print("  3. If using USB, run: ./setup_usb_forwarding.sh first")
            print("\n💡 Want to test without a drone? Run the Simulator using your laptop camera:")
            print("   ./run_simulator.sh")
            print("   or: ./run.sh --sim")
            sys.exit(1)

    # Initialize drone flight mode
    step_fb = round(args.step if args.step is not None else args.step_fb, 2)
    step_vert = round(args.step_vert, 2)
    step_lat = 0.30
    step_dist = (step_fb, step_vert)
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

    # Initialize Gaze Tracker
    print("Initializing MediaPipe Gaze & Face Mesh Tracker...")
    gaze_tracker = GazeTracker()
    print("Gaze Tracker loaded successfully!")

    # Initialize Two-Player Rock-Paper-Scissors Referee
    print("Initializing Two-Player Rock-Paper-Scissors Referee...")
    rps_game = RockPaperScissorsGame()
    print("RPS Referee loaded successfully!")

    # Initialize Wireless Arduino Vibration Controller
    print(f"Initializing Wireless Vibration Motor Controller ({args.arduino_ip}:{args.arduino_port})...")
    vibration_controller = ArduinoVibrationController(ip=args.arduino_ip, port=args.arduino_port)
    print("Wireless Vibration Controller ready!")

    # Determine video source
    if is_simulator:
        mirror_mode = not args.no_mirror
        print(f"Starting Laptop Camera Receiver #{args.camera} (Mirror: {mirror_mode})...")
        video = WebcamReceiver(camera_index=args.camera, mirror=mirror_mode)
        video.start()
        rtsp_url = f"webcam://{args.camera}"
    else:
        # Determine RTSP stream URL & ensure stream is active
        rtsp_url = args.rtsp
        try:
            print("Checking live video stream on drone...")
            stream_info = client.getLiveStreamInfo()
            if not stream_info.get("streaming"):
                print("Requesting Android app to start RTSP live stream...")
                res = client.startLiveStream()
                print(f"Start live stream response: {res}")
                time.sleep(1.5)
                stream_info = client.getLiveStreamInfo()

            if not rtsp_url and isinstance(stream_info, dict) and stream_info.get("url"):
                raw_url = stream_info.get("url")
                if host in ("127.0.0.1", "localhost"):
                    rtsp_url = "rtsp://admin:123456@127.0.0.1:8554/streaming/live/1"
                else:
                    rtsp_url = raw_url
        except Exception as e:
            print(f"Notice querying live stream: {e}")

        if not rtsp_url:
            rtsp_url = f"rtsp://admin:123456@{host}:8554/streaming/live/1"

        print(f"Starting Video Receiver on: {rtsp_url}")
        video = VideoReceiver(rtsp_url, client=client)
        video.start()

    # Telemetry State
    telemetry = {"connected": True, "altitude": 0.0, "heading": 0.0, "simulator": is_simulator, "speed": args.speed}
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

    # Hand Open/Close Transition Tracking
    last_stable_posture = None      # "OPEN" or "CLOSED"
    last_transition_event = None    # "OPEN_TO_CLOSED" or "CLOSED_TO_OPEN"
    last_transition_time = 0.0
    last_hand_seen_time = 0.0
    last_transition_speed = args.speed
    last_transition_tier = "NORMAL"
    openness_history = deque(maxlen=40)

    estop = False              # Emergency Stop toggle
    gesture_enabled = True     # Gesture control enable toggle
    movement_enabled = not args.dry_run  # Physical drone movement toggle
    last_command_time = 0.0
    last_haptic_buzz_time = 0.0
    candidate_thumb_dir = None
    candidate_thumb_since = 0.0
    command_interval = 0.70    # Rate limiter between step triggers (700ms)
    action_in_flight = False

    # Safety Boundary Box (default: 1.0m Forward/Backward, 30cm Up/Down, 50cm Lateral)
    default_point_set = False
    max_boundary_fb = round(args.boundary if args.boundary is not None else args.boundary_fb, 2)
    max_boundary_vert = round(args.boundary if args.boundary is not None else args.boundary_vert, 2)
    max_boundary_lat = round(args.boundary if args.boundary is not None else args.boundary_lat, 2)
    rel_x = 0.0
    rel_y = 0.0
    rel_z = 0.0
    home_alt = 0.0

    def do_action(action_fn, desc, is_movement=True, delta=(0.0, 0.0, 0.0)):
        nonlocal last_action, action_in_flight, rel_x, rel_y, rel_z
        if action_in_flight:
            return

        # Check safety boundary box if set
        if default_point_set and is_movement and delta != (0.0, 0.0, 0.0):
            cand_x = round(rel_x + delta[0], 3)
            cand_y = round(rel_y + delta[1], 3)
            cand_z = round(rel_z + delta[2], 3)

            if abs(cand_x) > max_boundary_fb + 0.001:
                last_action = f"BLOCKED: Fwd/Bwd limit ±{int(max_boundary_fb*100)}cm! (Target X: {cand_x*100:+.0f}cm)"
                print(f"⚠️  {last_action}")
                return
            if abs(cand_z) > max_boundary_vert + 0.001:
                last_action = f"BLOCKED: Altitude limit ±{int(max_boundary_vert*100)}cm! (Target Z: {cand_z*100:+.0f}cm)"
                print(f"⚠️  {last_action}")
                return
            if abs(cand_y) > max_boundary_lat + 0.001:
                last_action = f"BLOCKED: Lateral limit ±{int(max_boundary_lat*100)}cm! (Target Y: {cand_y*100:+.0f}cm)"
                print(f"⚠️  {last_action}")
                return

        if is_movement and not movement_enabled:
            if default_point_set and delta != (0.0, 0.0, 0.0):
                rel_x = round(rel_x + delta[0], 3)
                rel_y = round(rel_y + delta[1], 3)
                rel_z = round(rel_z + delta[2], 3)
            last_action = f"[DRY RUN SIMULATED] {desc}"
            print(f">> {last_action} (Movement locked - press 'M' to enable)")
            return

        action_in_flight = True
        last_action = desc
        print(f">> {desc}...")
        def _task():
            nonlocal last_action, action_in_flight, rel_x, rel_y, rel_z
            try:
                action_fn()
                if default_point_set and delta != (0.0, 0.0, 0.0):
                    rel_x = round(rel_x + delta[0], 3)
                    rel_y = round(rel_y + delta[1], 3)
                    rel_z = round(rel_z + delta[2], 3)
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
    if is_simulator:
        print("   DJI GESTURE SIMULATOR (LAPTOP WEBCAM)")
        print(f"   Camera: Device #{args.camera} (Mirrored) | Drone: Virtual Simulated Drone")
    else:
        print("   DJI LIVE FLIGHT CONTROLLER")
        print(f"   Drone Host: {host}:{port} | Stream: {rtsp_url}")
    print("-" * 65)
    print("GESTURE & KEYBOARD CONTROLS:")
    print(f"  [H]                     Set Default Point (Boundary: Fwd/Bwd ±{int(max_boundary_fb*100)}cm, Alt ±{int(max_boundary_vert*100)}cm)")
    print("  [K]                     Clear Default Point")
    print(f"  [👍 Thumb Up]           Climb (Move Up by {int(step_vert*100)}cm)")
    print(f"  [👎 Thumb Down]         Descend (Move Down by {int(step_vert*100)}cm)")
    print(f"  [✋ -> ✊ Closing Hand] Move Forward ({int(step_fb*100)}cm, speed from closing)")
    print(f"  [✊ -> ✋ Opening Hand] Move Backward ({int(step_fb*100)}cm, speed from opening)")
    print("  [M]                     Toggle Drone Movement ON/OFF (Dry Run Mode)")
    print("  [SPACE]          E-Stop / Pause Gesture Control")
    print("  [G]              Toggle Gesture Tracking On/Off")
    print(f"  [W / S]          Manual Forward / Backward ({int(step_fb*100)}cm)")
    print(f"  [A / D]          Manual Left / Right ({int(step_lat*100)}cm)")
    print(f"  [U / J]          Manual Altitude Up / Down ({int(step_vert*100)}cm)")
    print("  [Q / E]          Manual Yaw (Rotate)")
    print("  [T / Spc]        Take Off")
    print("  [L]              Land")
    print("  [R]              Start / Rematch Rock-Paper-Scissors Duel (5s Countdown)")
    print("  NOTE: Flight gestures are locked until Rock-Paper-Scissors is played! Press [R] to begin.")
    print("  [+ / -]          Adjust Step Distance (+/- 5cm)")
    print("  [Esc / X]        Exit")
    print("-" * 65 + "\n")

    try:
        while running:
            frame = video.get_frame()
            if frame is None:
                gaze_info = None
                if is_simulator:
                    display_frame = create_standby_frame(1024, 576, f"Waiting for Laptop Camera #{args.camera}...")
                else:
                    display_frame = create_standby_frame(1024, 576, f"Waiting for Drone RTSP Stream: {rtsp_url}")
            else:
                display_frame = frame

                # Run MediaPipe Gesture Recognizer on incoming frame
                if gesture_enabled and not estop:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
                    recognition_result = recognizer.recognize(mp_image)

                    # Extract all recognized hands with positions for RPS referee and multi-person tracking
                    all_detected_hands = []
                    h_frame, w_frame, _ = frame.shape
                    if recognition_result.hand_landmarks:
                        for idx_hand in range(len(recognition_result.hand_landmarks)):
                            lm_list = recognition_result.hand_landmarks[idx_hand]
                            cx_hand = float(np.mean([pt.x * w_frame for pt in lm_list]))
                            cy_hand = float(np.mean([pt.y * h_frame for pt in lm_list]))

                            lbl = "None"
                            sc = 0.0
                            if (recognition_result.gestures and 
                                    idx_hand < len(recognition_result.gestures) and 
                                    len(recognition_result.gestures[idx_hand]) > 0):
                                top_g = recognition_result.gestures[idx_hand][0]
                                lbl = top_g.category_name
                                sc = top_g.score

                            all_detected_hands.append({
                                "label": lbl,
                                "score": sc,
                                "cx": cx_hand,
                                "cy": cy_hand,
                                "landmarks": lm_list
                            })

                    # Run Rock-Paper-Scissors Referee
                    rps_info = rps_game.process(frame, all_detected_hands)
                    rps_state = rps_info.get("state", "WAITING")
                    rps_winner = rps_info.get("winner")
                    rps_unlocked = (rps_state == "WINNER" and rps_winner in ("P1", "P2"))

                    # Select controlling hand:
                    detected_label = "None"
                    detected_score = 0.0
                    hand_landmarks = None

                    active_ctrl = rps_info.get("active_controller")
                    p1_box = rps_info.get("p1_box")
                    p2_box = rps_info.get("p2_box")

                    valid_hands = []
                    if rps_unlocked:
                        mid_div = (p1_box[0] + p1_box[2] + p2_box[0] + p2_box[2]) / 4.0 if (p1_box and p2_box) else (w_frame / 2.0)
                        if rps_info.get("mode") == "2_PLAYER":
                            for h_item in all_detected_hands:
                                if active_ctrl == "P1" and h_item["cx"] < mid_div:
                                    valid_hands.append(h_item)
                                elif active_ctrl == "P2" and h_item["cx"] >= mid_div:
                                    valid_hands.append(h_item)
                            if len(valid_hands) == 0 and len(all_detected_hands) == 1:
                                valid_hands = all_detected_hands
                        else:
                            valid_hands = all_detected_hands
                    else:
                        valid_hands = []

                    if len(valid_hands) > 0:
                        top_hand = valid_hands[0]
                        detected_label = top_hand["label"]
                        detected_score = top_hand["score"]
                        hand_landmarks = top_hand["landmarks"]

                    now = time.time()
                    hand_detected = (hand_landmarks is not None) or (detected_score >= args.min_score and detected_label != "None")

                    if not hand_detected:
                        if now - last_hand_seen_time > 0.8:
                            # Reset posture if hand was out of view so entering frame doesn't trigger false transition
                            last_stable_posture = None
                    else:
                        last_hand_seen_time = now

                    # Compute hand openness metric from landmarks
                    openness = compute_hand_openness(hand_landmarks) if hand_landmarks else 1.4
                    if hand_detected:
                        openness_history.append((now, openness))

                    # Determine instantaneous posture
                    current_posture = "None"
                    if detected_score >= args.min_score and detected_label in ("Thumb_Up", "Thumb_Down"):
                        current_posture = detected_label
                    elif hand_detected:
                        # Open hand: classified as Open_Palm or finger extension high
                        if (detected_score >= args.min_score and detected_label == "Open_Palm") or openness >= 1.60:
                            current_posture = "OPEN"
                        # Closed fist: classified as Closed_Fist or finger extension low
                        elif (detected_score >= args.min_score and detected_label == "Closed_Fist") or openness <= 1.20:
                            current_posture = "CLOSED"
                        else:
                            current_posture = "TRANSITION"

                    # Handle flight gestures ONLY if Rock-Paper-Scissors has been won!
                    if rps_unlocked:
                        # Handle transitions: Closing Hand -> Forward, Opening Hand -> Backward
                        if current_posture == "CLOSED":
                            if last_stable_posture == "OPEN":
                                # User closed their hand! (Open -> Closed) -> MOVE FORWARD
                                if now - last_command_time >= command_interval:
                                    last_command_time = now
                                    last_transition_event = "OPEN_TO_CLOSED"
                                    last_transition_time = now

                                    # Measure gesture closing duration from openness history
                                    start_time = now - 0.35
                                    for t_hist, op_hist in reversed(openness_history):
                                        if op_hist >= 1.55:
                                            start_time = t_hist
                                            break
                                    duration = max(0.08, now - start_time)
                                    target_speed, speed_tier = map_duration_to_speed(duration, min_speed=args.min_speed, max_speed=args.max_speed)
                                    last_transition_speed = target_speed
                                    last_transition_tier = speed_tier
                                    telemetry["speed"] = target_speed

                                    def _do_forward():
                                        try:
                                            client.setMaxSpeed(target_speed)
                                        except Exception:
                                            pass
                                        return client.moveForward(step_fb)

                                    do_action(
                                        _do_forward,
                                        f"Gesture: Closing Hand [{speed_tier} {target_speed:.2f}m/s, {duration:.2f}s] -> Move Forward {int(step_fb*100)}cm",
                                        delta=(step_fb, 0.0, 0.0)
                                    )
                            last_stable_posture = "CLOSED"

                        elif current_posture == "OPEN":
                            if last_stable_posture == "CLOSED":
                                # User opened their hand! (Closed -> Open) -> MOVE BACKWARD
                                if now - last_command_time >= command_interval:
                                    last_command_time = now
                                    last_transition_event = "CLOSED_TO_OPEN"
                                    last_transition_time = now

                                    # Measure gesture opening duration from openness history
                                    start_time = now - 0.35
                                    for t_hist, op_hist in reversed(openness_history):
                                        if op_hist <= 1.25:
                                            start_time = t_hist
                                            break
                                    duration = max(0.08, now - start_time)
                                    target_speed, speed_tier = map_duration_to_speed(duration, min_speed=args.min_speed, max_speed=args.max_speed)
                                    last_transition_speed = target_speed
                                    last_transition_tier = speed_tier
                                    telemetry["speed"] = target_speed

                                    def _do_backward():
                                        try:
                                            client.setMaxSpeed(target_speed)
                                        except Exception:
                                            pass
                                        return client.moveBackward(step_fb)

                                    do_action(
                                        _do_backward,
                                        f"Gesture: Opening Hand [{speed_tier} {target_speed:.2f}m/s, {duration:.2f}s] -> Move Backward {int(step_fb*100)}cm",
                                        delta=(-step_fb, 0.0, 0.0)
                                    )
                            last_stable_posture = "OPEN"

                        elif current_posture in ("Thumb_Up", "Thumb_Down"):
                            last_stable_posture = None
                            if current_posture == "Thumb_Up" and (now - last_command_time >= command_interval):
                                last_command_time = now
                                do_action(lambda: client.moveUp(step_vert), f"Gesture: Move Up {int(step_vert*100)}cm", delta=(0.0, 0.0, step_vert))
                            elif current_posture == "Thumb_Down" and (now - last_command_time >= command_interval):
                                last_command_time = now
                                do_action(lambda: client.moveDown(step_vert), f"Gesture: Move Down {int(step_vert*100)}cm", delta=(0.0, 0.0, -step_vert))

                    # Prepare gesture_info for HUD display
                    if not rps_unlocked:
                        if rps_state == "WAITING":
                            gesture_info["label"] = "RPS_Locked"
                            gesture_info["score"] = 0.0
                            gesture_info["action"] = "PRESS [R] TO START RPS DUEL"
                        elif rps_state == "COUNTDOWN":
                            gesture_info["label"] = "RPS_Match"
                            gesture_info["score"] = 0.0
                            gesture_info["action"] = "DUEL IN PROGRESS (5s)"
                        elif rps_winner == "TIE":
                            gesture_info["label"] = "RPS_Locked"
                            gesture_info["score"] = 0.0
                            gesture_info["action"] = "TIE! PRESS [R] FOR REMATCH"
                        else:
                            gesture_info["label"] = "RPS_Locked"
                            gesture_info["score"] = 0.0
                            gesture_info["action"] = "COMPLETE RPS DUEL [Press R]"
                    elif now - last_transition_time < 1.2 and last_transition_event == "OPEN_TO_CLOSED":
                        gesture_info["label"] = "Closing_Hand"
                        gesture_info["score"] = detected_score if detected_score > 0 else 0.95
                        gesture_info["action"] = "FORWARD"
                        gesture_info["speed"] = last_transition_speed
                        gesture_info["speed_tier"] = last_transition_tier
                    elif now - last_transition_time < 1.2 and last_transition_event == "CLOSED_TO_OPEN":
                        gesture_info["label"] = "Opening_Hand"
                        gesture_info["score"] = detected_score if detected_score > 0 else 0.95
                        gesture_info["action"] = "BACKWARD"
                        gesture_info["speed"] = last_transition_speed
                        gesture_info["speed_tier"] = last_transition_tier
                    elif current_posture == "Thumb_Up":
                        gesture_info["label"] = "Thumb_Up"
                        gesture_info["score"] = detected_score
                        gesture_info["action"] = "CLIMB"
                    elif current_posture == "Thumb_Down":
                        gesture_info["label"] = "Thumb_Down"
                        gesture_info["score"] = detected_score
                        gesture_info["action"] = "DESCEND"
                    elif current_posture == "OPEN":
                        gesture_info["label"] = "Open_Palm"
                        gesture_info["score"] = detected_score if detected_score > 0 else 0.90
                        gesture_info["action"] = "HOVER"
                    elif current_posture == "CLOSED":
                        gesture_info["label"] = "Closed_Fist"
                        gesture_info["score"] = detected_score if detected_score > 0 else 0.90
                        gesture_info["action"] = "HOVER"
                    else:
                        gesture_info["label"] = "None"
                        gesture_info["score"] = 0.0
                        gesture_info["action"] = "HOVER"

                else:
                    gesture_info["label"] = "Paused"
                    gesture_info["score"] = 0.0
                    gesture_info["action"] = "PAUSED"

                # Run Gaze Tracking to detect if user is looking straight at camera
                try:
                    gaze_info = gaze_tracker.process(frame)
                except Exception as e:
                    gaze_info = {
                        "face_detected": False,
                        "looking_at_camera": False,
                        "direction": "NO FACE DETECTED",
                        "confidence": 0.0,
                        "yaw": 0.0,
                        "pitch": 0.0,
                        "roll": 0.0,
                        "iris_h": 0.50,
                        "iris_v": 0.50,
                        "iris_left": None,
                        "iris_right": None
                    }

                # --- Haptic Vibration Trigger ---
                # Only active after Rock-Paper-Scissors has crowned a winner
                if rps_unlocked:
                    thumb_dir = classify_thumb_direction(hand_landmarks, detected_label)
                    gaze_clearly_averted = gaze_info.get("face_detected", False) and gaze_info.get("clear_averted", False)
                    gaze_dir_label = gaze_info.get("direction", "AVERTED")

                    # Debounce: Ensure user is deliberately holding the thumb gesture (not a transient fist transition)
                    if thumb_dir in ("THUMB_UP", "THUMB_DOWN", "THUMB_LEFT", "THUMB_RIGHT"):
                        if candidate_thumb_dir == thumb_dir:
                            # Verified thumb gesture held stable
                            if (now - candidate_thumb_since >= max(0.20, args.hold_time)) and gaze_clearly_averted:
                                triggered = vibration_controller.trigger_buzz_async(duration=0.30, intensity=255, cooldown=0.80)
                                if triggered:
                                    last_haptic_buzz_time = now
                                    last_action = f"⚡ HAPTIC MOTOR BUZZ: {thumb_dir} (Gaze: {gaze_dir_label})"
                                    print(f"\n>> {last_action}\n")
                        else:
                            candidate_thumb_dir = thumb_dir
                            candidate_thumb_since = now
                    else:
                        candidate_thumb_dir = None

            # Draw HUD
            haptic_is_active = (time.time() - last_haptic_buzz_time) < 0.50
            cur_dist = np.sqrt(rel_x**2 + rel_y**2 + rel_z**2) if default_point_set else 0.0
            safety_info = {
                "set": default_point_set,
                "x": rel_x,
                "y": rel_y,
                "z": rel_z,
                "dist": cur_dist,
                "max_fb": max_boundary_fb,
                "max_vert": max_boundary_vert,
                "max_lat": max_boundary_lat,
            }
            hud_frame = draw_hud(
                display_frame,
                telemetry,
                step_dist,
                gesture_info,
                estop,
                gesture_enabled,
                movement_enabled,
                safety_info,
                gaze_info=gaze_info,
                rps_info=rps_info if 'rps_info' in locals() else None,
                last_action=last_action,
                haptic_active=haptic_is_active
            )
            cv2.imshow(window_name, hud_frame)

            # Key check
            key = cv2.waitKey(25) & 0xFF

            if key in (27, ord('x'), ord('X')):
                print("Exit requested. Quitting...")
                break

            elif key in (ord('r'), ord('R')):
                rps_game.start_duel()
                last_action = "ROCK-PAPER-SCISSORS DUEL STARTED! Counting down from 5..."
                print(f"\n>> {last_action}\n")

            elif key in (ord('h'), ord('H')):
                default_point_set = True
                rel_x = 0.0
                rel_y = 0.0
                rel_z = 0.0
                home_alt = telemetry.get("altitude", 0.0)
                last_action = f"DEFAULT POINT SET! (Fwd/Bwd ±{int(max_boundary_fb*100)}cm, Alt ±{int(max_boundary_vert*100)}cm around Alt: {home_alt:.2f}m)"
                print(f"\n>> {last_action}\n")

            elif key in (ord('k'), ord('K')):
                default_point_set = False
                rel_x = 0.0
                rel_y = 0.0
                rel_z = 0.0
                last_action = "DEFAULT POINT CLEARED (Safety box disabled)"
                print(f"\n>> {last_action}\n")

            elif key in (ord('m'), ord('M')):
                movement_enabled = not movement_enabled
                last_action = "DRONE MOVEMENT ENABLED (Live Flight)" if movement_enabled else "DRONE MOVEMENT DISABLED (Dry Run)"
                print(f"\n>> {last_action}\n")

            elif key in (ord('i'), ord('I')):
                is_inv = client.toggleInvertForward()
                last_action = f"FORWARD/BACKWARD DIRECTION: {'INVERTED' if is_inv else 'NORMAL'}"
                print(f"\n>> {last_action}\n")

            elif key == ord(' '):
                estop = not estop
                last_action = "E-STOP ACTIVATED [Gestures Paused]" if estop else "E-STOP RELEASED [Gestures Resumed]"
                print(f">> {last_action}")

            elif key in (ord('g'), ord('G')):
                gesture_enabled = not gesture_enabled
                last_action = f"Gesture Tracking {'ENABLED' if gesture_enabled else 'DISABLED'}"
                print(f">> {last_action}")

            elif key in (ord('w'), ord('W')):
                do_action(lambda: client.moveForward(step_fb), f"Manual Move Forward {int(step_fb*100)}cm", delta=(step_fb, 0.0, 0.0))

            elif key in (ord('s'), ord('S')):
                do_action(lambda: client.moveBackward(step_fb), f"Manual Move Backward {int(step_fb*100)}cm", delta=(-step_fb, 0.0, 0.0))

            elif key in (ord('a'), ord('A')):
                do_action(lambda: client.moveLeft(step_lat), f"Manual Move Left {int(step_lat*100)}cm", delta=(0.0, -step_lat, 0.0))

            elif key in (ord('d'), ord('D')):
                do_action(lambda: client.moveRight(step_lat), f"Manual Move Right {int(step_lat*100)}cm", delta=(0.0, step_lat, 0.0))

            elif key in (ord('u'), ord('U')):
                do_action(lambda: client.moveUp(step_vert), f"Manual Move Up {int(step_vert*100)}cm", delta=(0.0, 0.0, step_vert))

            elif key in (ord('j'), ord('J')):
                do_action(lambda: client.moveDown(step_vert), f"Manual Move Down {int(step_vert*100)}cm", delta=(0.0, 0.0, -step_vert))

            elif key in (ord('q'), ord('Q')):
                do_action(lambda: client.rotateCounterClockwise(step_angle), f"Manual Rotate CCW {step_angle}°", delta=(0.0, 0.0, 0.0))

            elif key in (ord('e'), ord('E')):
                do_action(lambda: client.rotateClockwise(step_angle), f"Manual Rotate CW {step_angle}°", delta=(0.0, 0.0, 0.0))

            elif key in (ord('t'), ord('T')):
                do_action(lambda: client.takeOff(), "Auto Takeoff", is_movement=True, delta=(0.0, 0.0, 0.0))

            elif key in (ord('l'), ord('L')):
                do_action(lambda: client.land(), "Auto Landing", is_movement=True, delta=(0.0, 0.0, 0.0))

            elif key in (ord('c'), ord('C')):
                do_action(lambda: client.confirmLanding(), "Confirm Landing", is_movement=False)

            elif key in (ord('p'), ord('P')):
                do_action(lambda: client.captureShot(), "Capture Photo", is_movement=False)

            elif key in (ord('+'), ord('=')):
                step_fb = round(step_fb + 0.05, 2)
                step_dist = (step_fb, step_vert)
                last_action = f"Step distance set to: FB {int(step_fb*100)}cm, UD {int(step_vert*100)}cm"
                print(f">> {last_action}")

            elif key in (ord('-'), ord('_')):
                step_fb = max(0.05, round(step_fb - 0.05, 2))
                step_dist = (step_fb, step_vert)
                last_action = f"Step distance set to: FB {int(step_fb*100)}cm, UD {int(step_vert*100)}cm"
                print(f">> {last_action}")

    except KeyboardInterrupt:
        print("\nInterrupt received. Exiting...")
    finally:
        running = False
        try:
            vibration_controller.close()
        except Exception:
            pass
        video.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
