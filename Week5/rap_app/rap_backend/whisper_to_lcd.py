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

import os
import sys
import time
import glob
import textwrap
import argparse
import subprocess
import requests
import numpy as np
import speech_recognition as sr
import whisper
from dotenv import load_dotenv

# Load .env file (for GROK_API_KEY)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv()

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

# Grok & Voice Configuration
GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
GROK_MODEL = "grok-3"  # Standard xAI model
DEFAULT_VOICE = "eve"  # xAI TTS voice (e.g., eve, rex, ara, leo)
TTS_TEMP_FILE = "/tmp/grok_tts_reply.mp3"


def speak_text_grok_tts(text, voice_id=DEFAULT_VOICE):
    """
    Generate speech using xAI's official Text-to-Speech API (https://api.x.ai/v1/tts)
    and play it immediately via macOS 'afplay'.
    """
    if not text:
        return

    clean = text.replace("*", "").replace("#", "").replace('"', '').strip()

    if GROK_API_KEY:
        try:
            print(f"🎙️  Synthesizing with Grok TTS (voice: '{voice_id}')...")
            url = "https://api.x.ai/v1/tts"
            headers = {
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json",
            }
            payload = {
                "text": clean,
                "voice_id": voice_id,
                "language": "en",
            }

            response = requests.post(url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                with open(TTS_TEMP_FILE, "wb") as f:
                    f.write(response.content)
                print(f"🔊 Playing Grok voice ({len(response.content)} bytes)...")
                subprocess.run(["afplay", TTS_TEMP_FILE], check=False)
                return
            else:
                print(f"⚠️  xAI TTS returned {response.status_code}: {response.text}")
        except Exception as e:
            print(f"⚠️  xAI TTS error: {e}")

    # Fallback to local macOS voice if xAI TTS fails or offline
    try:
        print(f"🔊 Fallback speaking with macOS TTS: \"{clean}\"")
        subprocess.run(["say", clean], check=False)
    except Exception as e:
        print(f"⚠️  TTS fallback error: {e}")


def ask_grok(user_input, history=None):
    """
    Send recognized user input to xAI Grok and return a punchy response/rap back.
    """
    if not GROK_API_KEY:
        print("⚠️  No GROK_API_KEY found in .env. Skipping Grok response.")
        return None

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }

    system_prompt = (
        "You are an energetic, witty freestyle rap battle opponent and hype host. "
        "The user will rap or speak to you. Respond directly with 2 to 4 punchy, rhyming rap bars "
        "reacting to what they said. Keep it concise, clever, and rhythmic. Do not include introductory notes."
    )

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])  # Keep last 4 turns for context
    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": GROK_MODEL,
        "messages": messages,
        "max_tokens": 120,
        "temperature": 0.8
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=12)
        if response.status_code == 200:
            data = response.json()
            reply = data["choices"][0]["message"]["content"].strip()
            return reply
        else:
            print(f"⚠️  Grok API returned status {response.status_code}: {response.text}")
            return None
    except requests.RequestException as e:
        print(f"⚠️  Grok request error: {e}")
        return None


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
    parser.add_argument("--voice", type=str, default=DEFAULT_VOICE, help=f"xAI TTS voice ID (default: {DEFAULT_VOICE}, e.g. eve, rex, ara, leo)")
    parser.add_argument("--no-grok", action="store_true", help="Disable Grok AI response generation")
    args = parser.parse_args()

    explicit_port = args.port
    baud = args.baud
    model_name = args.model
    language = None if args.language.lower() == "auto" else args.language
    phrase_time_limit = args.phrase_limit
    voice_name = args.voice
    use_grok = not args.no_grok

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
    conversation_history = []

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

            # 1. Send what user said to Arduino LCD
            if arduino and arduino.is_open:
                update_lcd(arduino, f"You: {transcript}")
            else:
                print("⚠️  [LCD Offline] Formatted Preview:")
                for row_txt in format_text_for_lcd(f"You: {transcript}"):
                    print(f"   │{row_txt.ljust(LCD_COLS)}│")

            # 2. Send OSC messages (compatible with voice.py)
            if osc_client:
                osc_client.send_message("/speech/raw", transcript)
                osc_client.send_message("/speech", transcript.lower())

            # 3. Generate reactive response with Grok & Voice output
            if use_grok and GROK_API_KEY:
                print("\n🤖 Grok is writing bars in response...")
                if arduino and arduino.is_open:
                    send_to_arduino(arduino, "LINE:3:Grok thinking...")
                grok_reply = ask_grok(transcript, conversation_history)
                if grok_reply:
                    conversation_history.append({"role": "user", "content": transcript})
                    conversation_history.append({"role": "assistant", "content": grok_reply})
                    print(f"\n🔥 Grok: \"{grok_reply}\"")

                    # Display Grok's reply on the LCD (auto-scrolls if long)
                    if arduino and arduino.is_open:
                        update_lcd(arduino, f"Grok: {grok_reply}")

                    # Broadcast Grok's reply over OSC
                    if osc_client:
                        osc_client.send_message("/grok/reply", grok_reply)

                    # Speak Grok's response out loud via xAI Grok TTS API
                    speak_text_grok_tts(grok_reply, voice_id=voice_name)

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
