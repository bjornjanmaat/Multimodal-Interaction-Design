#!/usr/bin/env python3
"""
Supabase to Arduino LED & Buzzer Bridge (Switch-Triggered)
Listens for switch toggle signals from Arduino (Pin 12).
When toggled ON ("FETCH"), queries Supabase public.ratings,
calculates the average score (1-5), and sends the result to Arduino
to light up LEDs (Pins 2-6) and trigger the Piezo Buzzer (Pin 13) gradually.
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
    """Fetch all rows from public.ratings and calculate average score."""
    endpoint = f"{url}/rest/v1/ratings?select=rating"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}"
    }

    try:
        response = requests.get(endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data:
            return 0, 0.0

        scores = [int(item["rating"]) for item in data if item.get("rating") is not None]
        if not scores:
            return 0, 0.0

        total = len(scores)
        avg = sum(scores) / total
        return total, avg

    except requests.RequestException as e:
        print(f"⚠️  Supabase fetch error: {e}")
        return None, None


def try_connect_arduino(explicit_port=None, baud=9600):
    """Attempt connection to explicit port or any detected USB Arduino."""
    ports_to_try = [explicit_port] if explicit_port else find_arduino_ports()

    for p in ports_to_try:
        if not p:
            continue
        try:
            ser = serial.Serial(p, baud, timeout=0.1)
            time.sleep(2)  # Wait for Arduino bootloader reset
            print(f" Connected to Arduino on {p}")
            return ser, p
        except (serial.SerialException, OSError):
            continue

    return None, None


def main():
    parser = argparse.ArgumentParser(description="Switch-triggered Supabase ratings to Arduino LEDs & Buzzer.")
    parser.add_argument("--port", type=str, default=None, help="Serial port for Arduino (e.g. /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=9600, help="Baud rate (default: 9600)")
    args = parser.parse_args()

    explicit_port = args.port
    baud = args.baud

    url, key = get_supabase_credentials()

    print("=" * 65)
    print("🌟 Supabase → Arduino LED & Buzzer Bridge (Pin 12 Switch Trigger)")
    print(f"📡 Supabase URL: {url}")
    print(f"💡 LEDs: Pins 2, 3, 4, 5, 6 (Gradual activation)")
    print(f"🔊 Buzzer: Pin 13 (Ascending pitches C5, E5, G5, A5, C6)")
    print(f"🔘 Switch: Pin 12 (Flip switch ON to fetch and show ratings)")
    print("=" * 65)

    arduino = None
    connected_port = None

    try:
        while True:
            # Connect or Reconnect if serial is closed
            if arduino is None or not arduino.is_open:
                arduino, connected_port = try_connect_arduino(explicit_port, baud)
                if arduino is None:
                    print("⏳ Waiting for Arduino USB connection...", end="\r", flush=True)
                    time.sleep(1.5)
                    continue
                else:
                    print(f"\n Listening for switch toggles on {connected_port}...")

            # Read serial messages sent by the Arduino
            try:
                line = arduino.readline().decode(errors="ignore").strip()
            except (serial.SerialException, OSError) as err:
                print(f"\n❌ Serial connection dropped ({err}). Reconnecting...")
                if arduino:
                    try:
                        arduino.close()
                    except Exception:
                        pass
                arduino = None
                time.sleep(1.5)
                continue

            if not line:
                time.sleep(0.05)
                continue

            # Arduino reports bootloader ready
            if line == "READY":
                print(" Arduino reported READY. Waiting for Pin 12 switch...")

            # Arduino switch toggled ON -> trigger fetch
            elif line.upper() in ["FETCH", "TRIGGER", "ON"]:
                print("\n🔘 [Pin 12 Switch: ON] Fetching ratings from Supabase...")
                total, avg = fetch_ratings_and_average(url, key)

                if total is not None:
                    level = max(0, min(5, round(avg))) if total > 0 else 0
                    active_pins = [f"Pin {p}" for p in range(2, 2 + level)]
                    pins_str = ", ".join(active_pins) if active_pins else "None"

                    print(f"📊 Total Ratings: {total} | Average: {avg:.2f}/5.00")
                    print(f"✨ Sending Level {level}/5 to Arduino (Gradual LEDs: {pins_str} + Buzzer pitches)")

                    try:
                        arduino.write(f"{level}\n".encode())
                        arduino.flush()
                    except (serial.SerialException, OSError) as write_err:
                        print(f"❌ Failed to send to Arduino: {write_err}")

            # Arduino switch toggled OFF
            elif line.upper() == "OFF":
                print("🔘 [Pin 12 Switch: OFF] LEDs turned OFF & Buzzer silenced")

            else:
                print(f"   [Arduino] {line}")

    except KeyboardInterrupt:
        print("\n👋 Bridge stopped by user.")
    finally:
        if arduino and arduino.is_open:
            try:
                arduino.write(b"0\n")
                arduino.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
