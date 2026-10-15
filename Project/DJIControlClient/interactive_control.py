#!/usr/bin/env python3
"""
Interactive Terminal Drone Controller using DJIControlClient
============================================================
Allows sending discrete flight commands (Takeoff, Land, Movement, Rotation)
interactively from the terminal.
"""

import sys
import os
import time
import argparse

# Add current directory to path so DJIControlClient can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from DJIControlClient import DJIControlClient, ControlMode, VelocityProfile


def format_dist(dist_m):
    return f"{dist_m * 100:.0f}cm ({dist_m:.2f}m)"


def print_menu(step_dist, step_angle):
    print("\n" + "=" * 55)
    print("   DJI DRONE INTERACTIVE TERMINAL CONTROLLER")
    print("=" * 55)
    print(f" Current Step Distance: {format_dist(step_dist)} | Step Angle: {step_angle}°")
    print("-" * 55)
    print(" FLIGHT ACTIONS:")
    print("   [T]  Take Off (initiates auto-takeoff)")
    print("   [L]  Land")
    print("   [C]  Confirm Landing (if landing protection enabled)")
    print("")
    print(" TRANSLATION (Position Mode):")
    print(f"   [W]  Move Forward  (+{format_dist(step_dist)})")
    print(f"   [S]  Move Backward (-{format_dist(step_dist)})")
    print(f"   [A]  Move Left     ({format_dist(step_dist)})")
    print(f"   [D]  Move Right    ({format_dist(step_dist)})")
    print(f"   [U]  Move Up       (+{format_dist(step_dist)})")
    print(f"   [J]  Move Down     (-{format_dist(step_dist)})")
    print("")
    print(" ROTATION:")
    print(f"   [Q]  Rotate CCW    (-{step_angle}°)")
    print(f"   [E]  Rotate CW     (+{step_angle}°)")
    print("")
    print(" TELEMETRY & CAMERA:")
    print("   [H]  Get Altitude & Heading")
    print("   [P]  Capture Photo")
    print("")
    print(" CONFIGURATION:")
    print("   [+]  Increase step distance (+5cm)")
    print("   [-]  Decrease step distance (-5cm, min 1cm)")
    print("   [X]  Exit / Quit")
    print("=" * 55)


def main():
    parser = argparse.ArgumentParser(description="DJI Control Client Terminal Controller")
    parser.add_argument("--host", default="127.0.0.1", help="Server IP / Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Server Port (default: 8080)")
    parser.add_argument("--step", type=float, default=0.10, help="Step distance in meters (default: 0.10 = 10cm)")
    parser.add_argument("--speed", type=float, default=0.3, help="Max Speed in m/s (default: 0.3)")
    args = parser.parse_args()

    # Clean up host input in case user passes "http://ip" or "ip:8080"
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

    print(f"Connecting to DJIControlServer at http://{host}:{port}...")
    try:
        client = DJIControlClient(ip=host, port=port)
        print(" Connected successfully!")
    except Exception as e:
        print(f"\n Connection failed: {e}")
        print("\nTroubleshooting:")
        print("  1. Is the DJIControlServer app running on Android?")
        print("  2. If using Wi-Fi, pass --host <PHONE_IP> (e.g. --host 192.168.2.8).")
        print("  3. If using USB, did you run 'adb forward tcp:8080 tcp:8080'?")
        sys.exit(1)

    # Initialize configuration
    step_dist = round(args.step, 2)  # default 0.05 m = 5 cm
    step_angle = 30.0                # degrees

    try:
        client.setControlMode(ControlMode.POSITION)
        client.setMaxSpeed(args.speed)
        client.setLandingProtectionState(False)
    except Exception as e:
        print(f"Warning during initialization: {e}")

    print_menu(step_dist, step_angle)

    while True:
        try:
            cmd = input(f"\n[dist={format_dist(step_dist)}] Enter command > ").strip().lower()
            if not cmd:
                continue

            if cmd == 'x':
                print("Exiting controller...")
                break

            elif cmd == 't':
                confirm = input("⚠️ Confirm TAKEOFF? (y/n): ").strip().lower()
                if confirm == 'y':
                    print("Sending Takeoff command...")
                    res = client.takeOff()
                    print("Takeoff response:", res)
                    print("Waiting 5s for takeoff to complete...")
                    time.sleep(5)

            elif cmd == 'l':
                confirm = input("⚠️ Confirm LAND? (y/n): ").strip().lower()
                if confirm == 'y':
                    print("Sending Land command...")
                    res = client.land()
                    print("Land response:", res)

            elif cmd == 'c':
                print("Sending Confirm Landing...")
                print(client.confirmLanding())

            elif cmd == 'w':
                print(f"Moving Forward {format_dist(step_dist)}...")
                print(client.moveForward(step_dist))

            elif cmd == 's':
                print(f"Moving Backward {format_dist(step_dist)}...")
                print(client.moveBackward(step_dist))

            elif cmd == 'a':
                print(f"Moving Left {format_dist(step_dist)}...")
                print(client.moveLeft(step_dist))

            elif cmd == 'd':
                print(f"Moving Right {format_dist(step_dist)}...")
                print(client.moveRight(step_dist))

            elif cmd == 'u':
                print(f"Moving Up {format_dist(step_dist)}...")
                print(client.moveUp(step_dist))

            elif cmd == 'j':
                print(f"Moving Down {format_dist(step_dist)}...")
                print(client.moveDown(step_dist))

            elif cmd == 'q':
                print(f"Rotating CCW {step_angle}°...")
                print(client.rotateCounterClockwise(step_angle))

            elif cmd == 'e':
                print(f"Rotating CW {step_angle}°...")
                print(client.rotateClockwise(step_angle))

            elif cmd == 'h':
                alt = client.getAltitude()
                hdg = client.getHeading()
                print(f"Telemetry -> Altitude: {alt} m | Heading: {hdg}°")

            elif cmd == 'p':
                print("Capturing photo...")
                print(client.captureShot())

            elif cmd == '+':
                step_dist = round(step_dist + 0.05, 2)
                print(f"Step distance set to: {format_dist(step_dist)}")

            elif cmd == '-':
                step_dist = max(0.01, round(step_dist - 0.05, 2))
                print(f"Step distance set to: {format_dist(step_dist)}")

            elif cmd == 'm':
                print_menu(step_dist, step_angle)

            else:
                print(f"Unknown command '{cmd}'. Press 'm' to show menu.")

        except KeyboardInterrupt:
            print("\nInterrupt received. Exiting...")
            break
        except Exception as e:
            print(f"Error executing command: {e}")


if __name__ == "__main__":
    main()
