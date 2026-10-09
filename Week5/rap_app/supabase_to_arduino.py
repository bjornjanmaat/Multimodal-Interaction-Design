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


def compute_partition_leds(man_votes, machine_votes):
    """
    Calculate 0-3 LED partition for Man and Machine.
    - If total == 0: 0, 0 LEDs.
    - If one party has 100% of votes: 3 LEDs for winner, 0 for loser.
    - Only if both parties received the same votes (e.g. 4 to 4, 2 to 2):
        both parties have the SAME amount of LEDs (2, 2).
    - If one party has more votes:
        the party with more votes ALWAYS shows more LEDs (at least +1 LED).
        E.g. in 2 to 1 votes: 2 LEDs for the leader and 1 LED for the trailer.
    """
    total = man_votes + machine_votes
    if total <= 0:
        return 0, 0

    # 100% of votes
    if machine_votes == 0:
        return 3, 0
    if man_votes == 0:
        return 0, 3

    # Only if both parties received the same votes: equal LEDs (2 and 2)
    if man_votes == machine_votes:
        return 2, 2

    # If one party has more votes, always show more LEDs for the leader
    if man_votes > machine_votes:
        if man_votes >= 3 * machine_votes:
            return 3, 1
        return 2, 1
    else:
        if machine_votes >= 3 * man_votes:
            return 1, 3
        return 1, 2


def try_connect_arduino(explicit_port=None, baud=9600):
    """Attempt connection to explicit port or any detected USB Arduino."""
    ports_to_try = [explicit_port] if explicit_port else find_arduino_ports()

    for p in ports_to_try:
        if not p:
            continue
        try:
            ser = serial.Serial(p, baud, timeout=0.1)
            print(f"⏳ Waiting for Arduino on {p} to finish booting...")
            start_wait = time.time()
            ready_found = False
            while time.time() - start_wait < 3.5:
                if ser.in_waiting:
                    line = ser.readline().decode("utf-8", "ignore").strip()
                    if line:
                        print(f"   [Arduino boot] {line}")
                    if "READY" in line:
                        ready_found = True
                        break
                time.sleep(0.05)

            time.sleep(0.2)
            print(f"✅ Connected and synchronized with Arduino on {p}")
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
            time.sleep(0.03)
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
    print("🌟 Supabase Auto-Polling Vote Partition Monitor")
    print(f"📡 Supabase URL: {url}")
    print(f"💡 Man LEDs (3 LEDs):     Pins 8, 9, 10")
    print(f"💡 Machine LEDs (3 LEDs): Pins 11, 12, 13")
    print(f"⏱️  Auto-Poll Interval:    {interval}s")
    print("=" * 65)

    arduino = None
    connected_port = None

    last_total = None
    last_man_leds = None
    last_machine_leds = None

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
                    if last_man_leds is not None and last_machine_leds is not None:
                        send_to_arduino(arduino, f"LEDS:{last_man_leds},{last_machine_leds}")

            # 2. Fetch latest scores from Supabase
            total, machine_count, man_count, machine_ratio = fetch_ratings_and_average(url, key)

            if total is not None:
                man_leds, machine_leds = compute_partition_leds(man_count, machine_count)
                print(f"💡 [Votes Fetched] LEDs shown: 🧑 Man: {man_leds}/3 LEDs ({man_count} votes) | 🤖 Machine: {machine_leds}/3 LEDs ({machine_count} votes) (Total: {total})")

                # Initial fetch
                if last_total is None:
                    last_total = total
                    last_man_leds = man_leds
                    last_machine_leds = machine_leds

                    send_to_arduino(arduino, f"LEDS:{man_leds},{machine_leds}")
                    send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")

                    man_pins = [f"Pin {p}" for p in [8, 9, 10][:man_leds]] or ["None"]
                    machine_pins = [f"Pin {p}" for p in [11, 12, 13][:machine_leds]] or ["None"]
                    print(f" Initial State: {total} votes total")
                    print(f"   🧑 Man:     {man_count} votes → {man_leds}/3 LEDs ({', '.join(man_pins)})")
                    print(f"   🤖 Machine: {machine_count} votes → {machine_leds}/3 LEDs ({', '.join(machine_pins)})")

                else:
                    # Check if new votes arrived
                    if total > last_total:
                        diff = total - last_total
                        print(f"\n🗳️  [NEW VOTE] +{diff} new vote(s) received! (Total: {total} | Man: {man_count}, Machine: {machine_count})")
                        send_to_arduino(arduino, f"NEW_VOTE:{diff}")
                        time.sleep(diff * 0.15)
                        send_to_arduino(arduino, f"LEDS:{man_leds},{machine_leds}")
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")

                    # Check if LED partition changed
                    elif man_leds != last_man_leds or machine_leds != last_machine_leds:
                        print(f"📊 [PARTITION SHIFT] Man: {last_man_leds}→{man_leds}/3 LEDs | Machine: {last_machine_leds}→{machine_leds}/3 LEDs")
                        send_to_arduino(arduino, f"LEDS:{man_leds},{machine_leds}")
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")

                    else:
                        # Heartbeat re-sync so LEDs never desynchronize
                        send_to_arduino(arduino, f"LEDS:{man_leds},{machine_leds}")
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")

                    last_total = total
                    last_man_leds = man_leds
                    last_machine_leds = machine_leds

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
