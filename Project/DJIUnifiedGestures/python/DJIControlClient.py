#!/usr/bin/env python3
"""
DJIControlClient (Unified MSDK V5 Edition)
===========================================
Python client library for communicating with DJIUnified Android Server over HTTP REST.
Supports 6DOF flight controls, telemetry, camera actions, and RTSP video streaming control.
"""

from typing import Any, Dict, List, Union, Optional
import requests
from enum import Enum


class VelocityProfile(Enum):
    CONSTANT = 1
    TRAPEZOIDAL = 2
    S_CURVE = 3


class ControlMode(Enum):
    POSITION = 1
    VELOCITY = 2


class DJIControlClient:

    def __init__(self, ip: str = "127.0.0.1", port: int = 8080, timeout: float = 8.0) -> None:
        # Strip protocols and trailing ports if accidentally passed
        clean_ip = ip.strip()
        if clean_ip.startswith("http://"):
            clean_ip = clean_ip[7:]
        elif clean_ip.startswith("https://"):
            clean_ip = clean_ip[8:]
        if ":" in clean_ip:
            clean_ip, port_str = clean_ip.split(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                pass

        self.ip = clean_ip
        self.port = port
        self.timeout = timeout
        self.server_addr = f"http://{self.ip}:{self.port}"

        try:
            r = requests.get(url=self.server_addr, timeout=self.timeout)
            assert r.content == b"Connected", f"Unexpected response from server: {r.content}"
        except Exception as e:
            raise ConnectionError(f"Could not connect to DJIControlServer at {self.server_addr}: {e}")

    def makeReqAndReturnJSON(self, route: str) -> Dict[str, Any]:
        url = f"{self.server_addr}{route}"
        r = requests.get(url=url, timeout=self.timeout)
        try:
            return r.json()
        except Exception:
            return {"raw": r.text, "status_code": r.status_code}

    # --- Take off, Land, & Safety ---

    def takeOff(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/takeoff')

    def land(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/land')

    def confirmLanding(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/confirmLanding')

    def getLandingProtectionState(self) -> Union[bool, Dict[str, Any]]:
        state = self.makeReqAndReturnJSON('/isLandingProtectionEnabled')
        return state.get('state', state)

    def setLandingProtectionState(self, enabled: bool) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/enableLandingProtection' if enabled else '/disableLandingProtection')

    # --- Video Streaming (RTSP) ---

    def getLiveStreamInfo(self) -> Dict[str, Any]:
        """Returns dict with streaming status, rtsp url, ip, and port."""
        info = self.makeReqAndReturnJSON('/getLiveStreamUrl')
        return info.get('state', info)

    def startLiveStream(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/startLiveStream')

    def stopLiveStream(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/stopLiveStream')

    # --- Control Modes & Movement Speeds ---

    def getControlMode(self) -> ControlMode:
        res = self.makeReqAndReturnJSON('/getControlMode')
        if res.get('state') == 'POSITION':
            return ControlMode.POSITION
        return ControlMode.VELOCITY

    def setControlMode(self, mode: ControlMode) -> Dict[str, Any]:
        mode_str = "POSITION" if mode == ControlMode.POSITION else "VELOCITY"
        return self.makeReqAndReturnJSON(f'/setControlMode/{mode_str}')

    def getMaxSpeed(self) -> Union[float, Dict[str, Any]]:
        res = self.makeReqAndReturnJSON('/getMaxSpeed')
        return res.get('state', res)

    def setMaxSpeed(self, speed: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/setMaxSpeed/{speed}')

    def getMaxAngularSpeed(self) -> Union[float, Dict[str, Any]]:
        res = self.makeReqAndReturnJSON('/getMaxAngularSpeed')
        return res.get('state', res)

    def setMaxAngularSpeed(self, speed: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/setMaxAngularSpeed/{speed}')

    def getVelocityProfile(self) -> VelocityProfile:
        res = self.makeReqAndReturnJSON('/getVelocityProfile')
        name = res.get('state', '')
        if name == 'TRAPEZOIDAL':
            return VelocityProfile.TRAPEZOIDAL
        elif name == 'S_CURVE':
            return VelocityProfile.S_CURVE
        return VelocityProfile.CONSTANT

    def setVelocityProfile(self, profile: VelocityProfile) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/setVelocityProfile/{profile.name}')

    # --- Velocity Control (Continuous Flight) ---

    def startVelocityControl(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/startVelocityControl')

    def setVelocityCommand(self, xVel: float, yVel: float, zVel: float, yawRate: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/setVelocityCommand/{xVel}/{yVel}/{zVel}/{yawRate}')

    def stopVelocityControl(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/stopVelocityControl')

    def getCurrentVelocityCommand(self) -> Dict[str, Any]:
        res = self.makeReqAndReturnJSON('/getCurrentVelocityCommand')
        return res.get('state', res)

    # --- Position Control (Discrete Step Movement) ---

    def moveUp(self, distance: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/moveUp/{distance}')

    def moveDown(self, distance: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/moveDown/{distance}')

    def moveForward(self, distance: float) -> Dict[str, Any]:
        # On the drone's VirtualStick BODY coordinate frame, pitch velocity/axes are reversed:
        # Calling Android endpoint /moveBackward/ moves the physical drone Forward.
        return self.makeReqAndReturnJSON(f'/moveBackward/{distance}')

    def moveBackward(self, distance: float) -> Dict[str, Any]:
        # Calling Android endpoint /moveForward/ moves the physical drone Backward.
        return self.makeReqAndReturnJSON(f'/moveForward/{distance}')

    def moveLeft(self, distance: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/moveLeft/{distance}')

    def moveRight(self, distance: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/moveRight/{distance}')

    def rotateClockwise(self, angle: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/rotateClockwise/{angle}')

    def rotateCounterClockwise(self, angle: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/rotateCounterClockwise/{angle}')

    # --- Telemetry & State ---

    def getAltitude(self) -> float:
        res = self.makeReqAndReturnJSON('/getAltitude')
        return float(res.get('state', 0.0))

    def getHeading(self) -> float:
        res = self.makeReqAndReturnJSON('/getHeading')
        return float(res.get('state', 0.0))

    def getCurrentIMUState(self) -> Dict[str, Any]:
        res = self.makeReqAndReturnJSON('/getCurrentIMUState')
        return res.get('state', res)

    def startCollectingIMUState(self, interval_ms: int = 40) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/startCollectingIMUState/{interval_ms}')

    def stopCollectingIMUState(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/stopCollectingIMUState')

    def getCollectedIMUStates(self) -> List[Dict[str, float]]:
        res = self.makeReqAndReturnJSON('/getCollectedIMUStates')
        return res.get('state', [])

    def clearCollectedIMUStates(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/clearCollectedIMUStates')

    # --- Camera Actions ---

    def captureShot(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/captureShot')

    def startVideoRecording(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/startVideoRecording')

    def stopVideoRecording(self) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON('/stopVideoRecording')

    def pitchGimbal(self, angle: float) -> Dict[str, Any]:
        return self.makeReqAndReturnJSON(f'/pitchGimbal/{angle}')


class MockDJIControlClient:
    """Mock DJI Control Client for local testing & simulation without physical drone."""
    def __init__(self, ip: str = "127.0.0.1", port: int = 8080):
        self.ip = ip
        self.port = port
        self.altitude = 0.0
        self.heading = 0.0
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.is_flying = False
        self.max_speed = 0.3
        self.control_mode = ControlMode.POSITION
        self.landing_protection = False
        print("[SIMULATOR] Mock DJI Control Client initialized (Virtual Drone).")

    def takeOff(self) -> Dict[str, Any]:
        self.is_flying = True
        self.altitude = 1.20
        self.z = 1.20
        print("[SIMULATOR] Virtual Drone: Takeoff -> Hovering at 1.20m")
        return {"code": 0, "message": "Simulator: Takeoff Successful"}

    def land(self) -> Dict[str, Any]:
        self.is_flying = False
        self.altitude = 0.0
        self.z = 0.0
        print("[SIMULATOR] Virtual Drone: Landing -> On Ground (0.00m)")
        return {"code": 0, "message": "Simulator: Landed"}

    def confirmLanding(self) -> Dict[str, Any]:
        return {"code": 0, "message": "Simulator: Landing Confirmed"}

    def captureShot(self) -> Dict[str, Any]:
        print("[SIMULATOR] Virtual Drone: Snapshot captured")
        return {"code": 0, "message": "Simulator: Snapshot Captured"}

    def setControlMode(self, mode: ControlMode) -> Dict[str, Any]:
        self.control_mode = mode
        return {"code": 0, "message": "OK"}

    def getControlMode(self) -> ControlMode:
        return self.control_mode

    def setMaxSpeed(self, speed: float) -> Dict[str, Any]:
        self.max_speed = speed
        return {"code": 0, "message": "OK"}

    def getMaxSpeed(self) -> float:
        return self.max_speed

    def setLandingProtectionState(self, enabled: bool) -> Dict[str, Any]:
        self.landing_protection = enabled
        return {"code": 0, "message": "OK"}

    def moveUp(self, distance: float) -> Dict[str, Any]:
        self.altitude = round(self.altitude + distance, 2)
        self.z = round(self.z + distance, 2)
        print(f"[SIMULATOR] Virtual Drone: Move Up +{int(distance*100)}cm -> Alt: {self.altitude:.2f}m")
        return {"code": 0, "state": "SUCCESS"}

    def moveDown(self, distance: float) -> Dict[str, Any]:
        self.altitude = max(0.0, round(self.altitude - distance, 2))
        self.z = max(0.0, round(self.z - distance, 2))
        print(f"[SIMULATOR] Virtual Drone: Move Down -{int(distance*100)}cm -> Alt: {self.altitude:.2f}m")
        return {"code": 0, "state": "SUCCESS"}

    def moveForward(self, distance: float) -> Dict[str, Any]:
        self.x = round(self.x + distance, 2)
        print(f"[SIMULATOR] Virtual Drone: Move Forward +{int(distance*100)}cm @ {self.max_speed:.2f} m/s -> Pos (X:{self.x:+.2f}m, Y:{self.y:+.2f}m)")
        return {"code": 0, "state": "SUCCESS"}

    def moveBackward(self, distance: float) -> Dict[str, Any]:
        self.x = round(self.x - distance, 2)
        print(f"[SIMULATOR] Virtual Drone: Move Backward -{int(distance*100)}cm @ {self.max_speed:.2f} m/s -> Pos (X:{self.x:+.2f}m, Y:{self.y:+.2f}m)")
        return {"code": 0, "state": "SUCCESS"}

    def moveLeft(self, distance: float) -> Dict[str, Any]:
        self.y = round(self.y - distance, 2)
        print(f"[SIMULATOR] Virtual Drone: Move Left -{int(distance*100)}cm -> Pos (X:{self.x:+.2f}m, Y:{self.y:+.2f}m)")
        return {"code": 0, "state": "SUCCESS"}

    def moveRight(self, distance: float) -> Dict[str, Any]:
        self.y = round(self.y + distance, 2)
        print(f"[SIMULATOR] Virtual Drone: Move Right +{int(distance*100)}cm -> Pos (X:{self.x:+.2f}m, Y:{self.y:+.2f}m)")
        return {"code": 0, "state": "SUCCESS"}

    def rotateClockwise(self, angle: float) -> Dict[str, Any]:
        self.heading = (self.heading + angle) % 360.0
        print(f"[SIMULATOR] Virtual Drone: Rotate CW {angle}° -> Heading: {self.heading:.1f}°")
        return {"code": 0, "state": "SUCCESS"}

    def rotateCounterClockwise(self, angle: float) -> Dict[str, Any]:
        self.heading = (self.heading - angle) % 360.0
        print(f"[SIMULATOR] Virtual Drone: Rotate CCW {angle}° -> Heading: {self.heading:.1f}°")
        return {"code": 0, "state": "SUCCESS"}

    def getAltitude(self) -> float:
        return float(self.altitude)

    def getHeading(self) -> float:
        return float(self.heading)

    def getLiveStreamInfo(self) -> Dict[str, Any]:
        return {"streaming": True, "url": "webcam"}

    def startLiveStream(self) -> Dict[str, Any]:
        return {"code": 0, "message": "OK"}

    def stopLiveStream(self) -> Dict[str, Any]:
        return {"code": 0, "message": "OK"}

