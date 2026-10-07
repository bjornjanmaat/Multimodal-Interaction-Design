#!/usr/bin/env python3
"""
Supabase to Arduino Auto-Polling Monitor
- Automatically polls Supabase public.ratings every 1.5s
- Sends signals to Arduino to control LEDs (pins 2, 3, 4, 5, 6):
    - LEDs always display the current rounded average rating (1 to 5)
- Sounds (Piezo buzzer on Pin 13):
    - Every time a new vote is added -> high beep ("NEW_VOTE")
    - If rounded average increases -> high-pitch alert ("AVG_UP")
    - If rounded average decreases -> low-pitch alert ("AVG_DOWN")
"""

import os
import sys
import time
import glob
import argparse
import requests
from dotenv import load_dotenv

try:
    import serial
except ImportError:
    print("pyserial is required. Install with: pip3 install pyserial")
    sys.exit(1)


def find_arduino_ports():
    """Find all active Arduino serial ports on macOS / Linux / Windows."""
    patterns = [
        "/dev/cu.usbmodem*",
        "/dev/cu.usbserial*",
        "/dev/ttyUSB*",
        "/dev/ttyACM*"
    ]
    matches = []
    for p in patterns:
        matches.extend(glob.glob(p))
    return sorted(list(set(matches)))


def get_supabase_credentials():
    """Locate and load .env file from vote_app folder or parent dirs."""
    env_paths = [
        os.path.join(os.path.dirname(__file__), "vote_app", ".env"),
        os.path.join(os.path.dirname(__file__), ".env"),
        os.path.join(os.getcwd(), "vote_app", ".env"),
        os.path.join(os.getcwd(), ".env")
    ]
    
    for path in env_paths:
        if os.path.isfile(path):
            load_dotenv(path)
            break

    url = os.getenv("VITE_SUPABASE_URL")
    key = os.getenv("VITE_SUPABASE_ANON_KEY")

    if not url or not key:
        print("❌ Error: Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in .env file.")
        print("Please check vote_app/.env and configure your Supabase project credentials.")
        sys.exit(1)

    return url.rstrip("/"), key


def fetch_ratings_and_average(url, key):
    """Fetch all rows from public.ratings and calculate vote ratio."""
    endpoint = f"{url}/rest/v1/ratings?select=winner"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}"
    }

    try:
        response = requests.get(endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()

        total = len(data)
        machine_count = sum(1 for item in data if (item.get("winner") or "").strip().lower() in ("machine", "bot"))
        man_count = sum(1 for item in data if (item.get("winner") or "").strip().lower() in ("man", "person"))
        machine_ratio = (machine_count / total) if total > 0 else 0.0

        return total, machine_count, man_count, machine_ratio

    except requests.RequestException as e:
        print(f"⚠️  Supabase fetch error: {e}")
        return None, None, None, None


def try_connect_arduino(explicit_port=None, baud=9600):
    """Attempt connection to explicit port or any detected USB Arduino."""
    ports_to_try = [explicit_port] if explicit_port else find_arduino_ports()

    for p in ports_to_try:
        if not p:
            continue
        try:
            ser = serial.Serial(p, baud, timeout=0.1)
            time.sleep(2)  # Wait for Arduino reset
            print(f" Connected to Arduino on {p}")
            return ser, p
        except (serial.SerialException, OSError):
            continue

    return None, None


def send_to_arduino(arduino, command):
    """Send text command line to Arduino with error handling."""
    if arduino and arduino.is_open:
        try:
            arduino.write(f"{command}\n".encode())
            arduino.flush()
            time.sleep(0.05)
            return True
        except (serial.SerialException, OSError) as e:
            print(f"❌ Serial write error: {e}")
            return False
    return False


def main():
    parser = argparse.ArgumentParser(description="Auto-fetch Supabase ratings with dynamic sound and LED triggers.")
    parser.add_argument("--port", type=str, default=None, help="Serial port for Arduino (e.g. /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    parser.add_argument("--interval", type=float, default=1.5, help="Poll interval in seconds (default: 1.5s)")
    args = parser.parse_args()

    explicit_port = args.port
    baud = args.baud
    interval = args.interval

    url, key = get_supabase_credentials()

    print("=" * 65)
    print("🌟 Supabase Auto-Polling Rating Monitor")
    print(f"📡 Supabase URL: {url}")
    print(f"💡 LEDs: Pins 2, 3, 4, 5, 6 (displays rounded average 1-5)")
    print(f"🔊 Buzzer: Pin 13")
    print(f"   • High beep on every new vote")
    print(f"   • High pitch alert if rounded average goes UP")
    print(f"   • Low pitch alert if rounded average goes DOWN")
    print(f"⏱️  Auto-Poll Interval: {interval}s")
    print("=" * 65)

    arduino = None
    connected_port = None

    last_total = None
    last_rounded_avg = None

    try:
        while True:
            # 1. Ensure Arduino is connected
            if arduino is None or not arduino.is_open:
                arduino, connected_port = try_connect_arduino(explicit_port, baud)
                if arduino is None:
                    print("⏳ Waiting for Arduino USB connection...", end="\r", flush=True)
                    time.sleep(0.1)
                    continue
                else:
                    print(f"\n Active connection on {connected_port}. Monitoring Supabase...")
                    # Resend current level if known
                    if last_rounded_avg is not None:
                        send_to_arduino(arduino, f"LEVEL:{last_rounded_avg}")

            # 2. Fetch latest scores from Supabase
            total, machine_count, man_count, machine_ratio = fetch_ratings_and_average(url, key)

            if total is not None:
                rounded_level = max(0, min(5, round(machine_ratio * 5))) if total > 0 else 0

                # Initial fetch
                if last_total is None:
                    last_total = total
                    last_rounded_avg = rounded_level
                    send_to_arduino(arduino, f"LEVEL:{rounded_level}")
                    active_pins = [f"Pin {p}" for p in range(2, 2 + rounded_level)]
                    pins_str = ", ".join(active_pins) if active_pins else "None"
                    print(f" Initial State: {total} votes (Machine: {machine_count}, Man: {man_count}) | Machine share: {machine_ratio * 100:.0f}% → LEDs: Level {rounded_level}/5 ({pins_str})")

                else:
                    # Check if new votes arrived
                    if total > last_total:
                        diff = total - last_total
                        print(f"\n🗳️  [NEW VOTE] +{diff} new vote(s) received! (Total: {total} | Machine: {machine_count}, Man: {man_count})")
                        # Send count so Arduino beeps once per new vote
                        send_to_arduino(arduino, f"NEW_VOTE:{diff}")
                        # Allow time for beeps to complete (160ms tone + 90ms gap = ~250ms each)
                        time.sleep(diff * 0.26)

                    # Check if machine level changed
                    if rounded_level > last_rounded_avg:
                        print(f"📈 [RATIO SHIFT] Machine share went up: Level {last_rounded_avg} → {rounded_level} ({machine_ratio * 100:.0f}% Machine)")
                        send_to_arduino(arduino, "AVG_UP")
                        time.sleep(0.2)
                        send_to_arduino(arduino, f"LEVEL:{rounded_level}")

                    elif rounded_level < last_rounded_avg:
                        print(f"📉 [RATIO SHIFT] Machine share went down: Level {last_rounded_avg} → {rounded_level} ({machine_ratio * 100:.0f}% Machine)")
                        send_to_arduino(arduino, "AVG_DOWN")
                        time.sleep(0.2)
                        send_to_arduino(arduino, f"LEVEL:{rounded_level}")

                    elif total > last_total:
                        # Share remained the same, but still refresh LED level just in case
                        send_to_arduino(arduino, f"LEVEL:{rounded_level}")

                    last_total = total
                    last_rounded_avg = rounded_level

            # Read any serial responses from Arduino (non-blocking)
            try:
                if arduino and arduino.in_waiting > 0:
                    msg = arduino.readline().decode(errors="ignore").strip()
                    if msg:
                        print(f"   [Arduino] {msg}")
            except (serial.SerialException, OSError):
                arduino = None

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n👋 Monitor stopped by user.")
    finally:
        if arduino and arduino.is_open:
            try:
                arduino.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
