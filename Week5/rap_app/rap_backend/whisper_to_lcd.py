#!/usr/bin/env python3
"""
Whisper Speech-to-Text to Arduino LCD Bridge
--------------------------------------------
- Uses OpenAI Whisper (exactly like voice.py) for offline speech recognition.
- Captures audio from the microphone using speech_recognition.
- Formats recognized speech into 20x4 character lines.
- Transmits text over Serial to the Arduino LCD (like arduino_lcd_text).
- Also broadcasts to OSC (port 9000) for UI/visualizer compatibility.
"""

import sys
import time
import glob
import textwrap
import argparse
import numpy as np
import speech_recognition as sr
import whisper

try:
    from pythonosc import udp_client
    HAS_OSC = True
except ImportError:
    HAS_OSC = False

try:
    import serial
except ImportError:
    print("pyserial is required. Install with: pip3 install pyserial")
    sys.exit(1)


# -----------------------------
# DEFAULT SETTINGS
# -----------------------------
DEFAULT_MODEL = "base"        # Options: tiny, base, small, medium, large
DEFAULT_LANGUAGE = "en"       # Language code or None for auto-detect
DEFAULT_BAUD = 9600
OSC_IP = "127.0.0.1"
OSC_PORT = 9000

LCD_COLS = 20
LCD_ROWS = 4


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


def try_connect_arduino(explicit_port=None, baud=DEFAULT_BAUD):
    """Attempt connection to explicit port or any detected USB Arduino."""
    ports_to_try = [explicit_port] if explicit_port else find_arduino_ports()

    for p in ports_to_try:
        if not p:
            continue
        try:
            ser = serial.Serial(p, baud, timeout=0.1)
            time.sleep(2)  # Wait for Arduino reset
            print(f"✅ Connected to Arduino on {p}")
            return ser, p
        except (serial.SerialException, OSError):
            continue

    return None, None


def send_to_arduino(arduino, command):
    """Send text command line to Arduino with error handling."""
    if arduino and arduino.is_open:
        try:
            arduino.write(f"{command}\n".encode("utf-8"))
            arduino.flush()
            time.sleep(0.04)
            return True
        except (serial.SerialException, OSError) as e:
            print(f"⚠️  Serial write error: {e}")
            return False
    return False


def format_text_for_lcd(text, max_cols=LCD_COLS, max_rows=LCD_ROWS):
    """
    Wrap text into at most max_rows lines of max_cols characters.
    If text exceeds max_rows, show the most recent lines (scrolling effect).
    """
    wrapped = textwrap.wrap(text.strip(), width=max_cols)
    if not wrapped:
        wrapped = [""]
    
    # If longer than 4 lines, keep the last 4 lines so latest words stay visible
    if len(wrapped) > max_rows:
        wrapped = wrapped[-max_rows:]
    
    # Pad up to max_rows with empty lines
    while len(wrapped) < max_rows:
        wrapped.append("")
        
    return wrapped


def update_lcd(arduino, text):
    """Format and send text to Arduino LCD."""
    lines = format_text_for_lcd(text)
    
    print("┌" + "─" * LCD_COLS + "┐")
    for row, line in enumerate(lines):
        padded_line = line[:LCD_COLS]
        print(f"│{padded_line.ljust(LCD_COLS)}│")
    print("└" + "─" * LCD_COLS + "┘")
    # Send full text to Arduino so it can scroll if longer than 4 lines
    clean_text = " ".join(text.strip().split())
    send_to_arduino(arduino, f"TEXT:{clean_text}")


def main():
    parser = argparse.ArgumentParser(description="Whisper Speech-to-Text to Arduino LCD")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="Whisper model (tiny, base, small, medium, large)")
    parser.add_argument("--language", type=str, default=DEFAULT_LANGUAGE, help="Language code (e.g. en, nl, sv) or auto")
    parser.add_argument("--port", type=str, default=None, help="Serial port (e.g. /dev/cu.usbmodem1101)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default: 9600)")
    parser.add_argument("--phrase-limit", type=int, default=4, help="Max phrase record duration in seconds (default: 4s)")
    args = parser.parse_args()

    explicit_port = args.port
    baud = args.baud
    model_name = args.model
    language = None if args.language.lower() == "auto" else args.language
    phrase_time_limit = args.phrase_limit

    # -----------------------------
    # OSC SETUP
    # -----------------------------
    osc_client = None
    if HAS_OSC:
        try:
            osc_client = udp_client.SimpleUDPClient(OSC_IP, OSC_PORT)
            print(f"📡 OSC client broadcasting to {OSC_IP}:{OSC_PORT}")
        except Exception as e:
            print(f"⚠️  OSC initialization skipped: {e}")

    # -----------------------------
    # WHISPER SETUP
    # -----------------------------
    print(f"\n🧠 Loading Whisper model '{model_name}'...")
    model = whisper.load_model(model_name)
    print("✨ Whisper model loaded.")

    # -----------------------------
    # ARDUINO SERIAL SETUP
    # -----------------------------
    print("\n🔌 Searching for Arduino LCD...")
    arduino, connected_port = try_connect_arduino(explicit_port, baud)
    if arduino:
        update_lcd(arduino, "Whisper STT Ready\nSpeak into mic...")
    else:
        print("⚠️  Arduino not found initially. Script will keep listening and auto-reconnect when plugged in.")

    # -----------------------------
    # MICROPHONE SETUP
    # -----------------------------
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    microphone = sr.Microphone()

    print("\n🎤 Calibrating microphone noise level...")
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)

    print("\n" + "=" * 50)
    print("🎙️  SYSTEM READY - Toggle mic with the button on Pin 7!")
    print(f"   Model: {model_name} | Language: {language or 'Auto-detect'} | Phrase limit: {phrase_time_limit}s")
    print("=" * 50 + "\n")

    mic_enabled = True  # Tracks whether microphone listening is enabled
    last_displayed_status = None

    # -----------------------------
    # MAIN LOOP
    # -----------------------------
    while True:
        try:
            # Check / reconnect Arduino if connection lost
            if arduino is None or not arduino.is_open:
                arduino, connected_port = try_connect_arduino(explicit_port, baud)
                if arduino:
                    send_to_arduino(arduino, "STATUS")

            # Check for button events or status messages from Arduino
            if arduino and arduino.is_open:
                while arduino.in_waiting > 0:
                    line = arduino.readline().decode(errors="ignore").strip()
                    if not line:
                        continue
                    if line == "BTN:ON":
                        if not mic_enabled:
                            mic_enabled = True
                            print("🟢 [Button] Mic turned ON")
                            update_lcd(arduino, "Mic Active\nListening...")
                    elif line == "BTN:OFF":
                        if mic_enabled:
                            mic_enabled = False
                            print("🔴 [Button] Mic turned OFF (Muted)")
                            update_lcd(arduino, "Mic Muted\nToggle switch/btn\nto speak...")
                    elif line.startswith("ACK:"):
                        pass
                    else:
                        print(f"   [Arduino] {line}")

            # If microphone is muted, wait briefly and continue checking button
            if not mic_enabled:
                time.sleep(0.1)
                continue

            with microphone as source:
                print("🎧 Listening...")
                audio = recognizer.listen(
                    source,
                    timeout=2,
                    phrase_time_limit=phrase_time_limit
                )

            # Check if mic was toggled off while listening before transcribing
            if arduino and arduino.is_open:
                while arduino.in_waiting > 0:
                    line = arduino.readline().decode(errors="ignore").strip()
                    if line == "BTN:OFF":
                        mic_enabled = False
                        print("🔴 [Button] Mic turned OFF")
                        update_lcd(arduino, "Mic Muted\nToggle switch/btn\nto speak...")

            if not mic_enabled:
                continue

            # Convert audio: 16 kHz, 16-bit PCM mono
            raw_audio = audio.get_raw_data(
                convert_rate=16000,
                convert_width=2
            )

            # Convert to float32 NumPy array in range -1.0 to 1.0
            audio_array = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32)
            audio_array /= 32768.0

            print("⚡ Transcribing with Whisper...")
            transcribe_kwargs = {
                "audio": audio_array,
                "fp16": False
            }
            if language:
                transcribe_kwargs["language"] = language

            result = model.transcribe(**transcribe_kwargs)
            transcript = result["text"].strip()

            if not transcript:
                print("   (Empty audio segment)")
                continue

            print(f"\n🎤 Heard: \"{transcript}\"")

            # 1. Send to Arduino LCD
            if arduino and arduino.is_open:
                update_lcd(arduino, transcript)
            else:
                print("⚠️  [LCD Offline] Formatted Preview:")
                for row_txt in format_text_for_lcd(transcript):
                    print(f"   │{row_txt.ljust(LCD_COLS)}│")

            # 2. Send OSC messages (compatible with voice.py)
            if osc_client:
                osc_client.send_message("/speech/raw", transcript)
                osc_client.send_message("/speech", transcript.lower())

        except sr.WaitTimeoutError:
            # Silence / timeout is normal when nobody is speaking
            pass

        except KeyboardInterrupt:
            print("\n👋 Stopped by user.")
            if arduino and arduino.is_open:
                send_to_arduino(arduino, "CLEAR")
                send_to_arduino(arduino, "LINE:0:Whisper Stopped")
                arduino.close()
            break

        except Exception as error:
            print(f"❌ Error: {error}")
            time.sleep(0.5)


if __name__ == "__main__":
    main()
