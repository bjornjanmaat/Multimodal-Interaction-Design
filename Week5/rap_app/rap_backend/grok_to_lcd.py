#!/usr/bin/env python3
"""
Grok AI Voice Battle with Arduino Button & LCD
----------------------------------------------
- When Arduino button (Pin 7) is pressed/switched ON:
    1. Laptop microphone listens to the user.
    2. Transcribes user's speech using SpeechRecognition.
    3. Displays user's words on the Arduino 20x4 LCD.
    4. Sends prompt to xAI Grok (grok-3) to generate rhyming battle bars.
    5. Displays Grok's reply on the LCD screen (with auto-scroll).
    6. Synthesizes Grok's voice using official xAI TTS API (eve / rex)
       and plays it out loud through laptop audio via macOS 'afplay'.
- Press/release button again to mute or trigger the next turn.
- Can also type at the terminal prompt.
"""

import os
import sys
import time
import glob
import textwrap
import argparse
import threading
import subprocess
import requests
import speech_recognition as sr
from dotenv import load_dotenv

# Load .env (looking for GROK_API_KEY)
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
# CONFIGURATION
# -----------------------------
GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
GROK_MODEL = "grok-3"
DEFAULT_VOICE = "eve"          # xAI voice ID (e.g. eve, rex, ara, leo)
DEFAULT_BAUD = 9600
LCD_COLS = 20
LCD_ROWS = 4
OSC_IP = "127.0.0.1"
OSC_PORT_SEND = 9000
TTS_AUDIO_FILE = "/tmp/grok_tts_rap.mp3"
UHH_AUDIO_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "uhh.mpeg")
)


def find_arduino_ports():
    """Detect connected USB Arduinos on macOS / Linux."""
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
    """Connect to Arduino serial port."""
    ports_to_try = [explicit_port] if explicit_port else find_arduino_ports()
    for p in ports_to_try:
        if not p:
            continue
        try:
            ser = serial.Serial(p, baud, timeout=0.1)
            time.sleep(2)  # Wait for Arduino reset
            print(f"✅ Connected to Arduino LCD on {p}")
            return ser, p
        except (serial.SerialException, OSError):
            continue
    return None, None


def send_to_arduino(arduino, command):
    """Send text command line to Arduino."""
    if arduino and arduino.is_open:
        try:
            arduino.write(f"{command}\n".encode("utf-8"))
            arduino.flush()
            time.sleep(0.04)
            return True
        except (serial.SerialException, OSError) as e:
            print(f"⚠️  Serial write error: {e}")
    return False


def format_text_for_lcd(text, max_cols=LCD_COLS, max_rows=LCD_ROWS):
    """Wrap text into lines of up to 20 characters."""
    wrapped = textwrap.wrap(text.strip(), width=max_cols)
    if not wrapped:
        wrapped = [""]
    if len(wrapped) > max_rows:
        wrapped = wrapped[-max_rows:]
    while len(wrapped) < max_rows:
        wrapped.append("")
    return wrapped


def update_lcd(arduino, text):
    """Format and send full text to Arduino LCD (triggers auto-scrolling)."""
    lines = format_text_for_lcd(text)
    print("┌" + "─" * LCD_COLS + "┐")
    for line in lines:
        padded = line[:LCD_COLS]
        print(f"│{padded.ljust(LCD_COLS)}│")
    print("└" + "─" * LCD_COLS + "┘")
    clean_text = " ".join(text.strip().split())
    send_to_arduino(arduino, f"TEXT:{clean_text}")


def speak_with_grok_tts(text, voice_id=DEFAULT_VOICE):
    """Synthesize speech using official xAI Grok TTS and play via afplay."""
    if not text:
        return

    clean = text.replace("*", "").replace("#", "").replace('"', '').strip()

    if GROK_API_KEY:
        try:
            print(f"🎙️  Synthesizing Grok voice (voice: '{voice_id}')...")
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
            res = requests.post(url, headers=headers, json=payload, timeout=15)
            if res.status_code == 200:
                with open(TTS_AUDIO_FILE, "wb") as f:
                    f.write(res.content)
                print(f"🔊 Playing Grok voice ({len(res.content):,} bytes)...")
                subprocess.run(["afplay", TTS_AUDIO_FILE], check=False)
                return
            else:
                print(f"⚠️  xAI TTS returned {res.status_code}: {res.text}")
        except Exception as e:
            print(f"⚠️  xAI TTS error: {e}")

    # Fallback to local macOS TTS
    try:
        print(f"🔊 Fallback speaking with macOS TTS: \"{clean}\"")
        subprocess.run(["say", clean], check=False)
    except Exception as e:
        print(f"⚠️  TTS error: {e}")


def play_uhh_sound():
    """Play the assets/uhh.mpeg sound effect when the mic is switched off."""
    target_file = UHH_AUDIO_FILE
    if not os.path.exists(target_file):
        alt = os.path.abspath(os.path.join(os.getcwd(), "assets", "uhh.mpeg"))
        if os.path.exists(alt):
            target_file = alt
        else:
            print(f"⚠️  Audio file not found: {target_file}")
            return

    try:
        print(f"🔊 [Sound FX] Playing {os.path.basename(target_file)}...")
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", target_file])
        else:
            subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", target_file])
    except Exception as e:
        print(f"⚠️  Error playing sound effect: {e}")


def ask_grok(user_input, history=None):
    """Call Grok API to generate 2-4 punchy rhyming rap bars."""
    if not GROK_API_KEY:
        print("❌ Error: Missing GROK_API_KEY in .env.")
        return None

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "You are an energetic, witty freestyle rap battle host and opponent. "
        "The user will rap or speak to you. Respond directly with 2 couplets of rap. "
        "Punchy, rhyming freestyle rap bars reacting to what they said. Keep it clever and rhythmic. "
        "Output ONLY the rap lyrics without intro notes."
        "Talk fast like an actual rapper."
    )

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": user_input})

    payload = {
        "model": GROK_MODEL,
        "messages": messages,
        "max_tokens": 120,
        "temperature": 1
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()
        else:
            print(f"⚠️  Grok API returned {res.status_code}: {res.text}")
            return None
    except requests.RequestException as e:
        print(f"⚠️  Grok request error: {e}")
        return None


def handle_rap_interaction(prompt, arduino, osc_client, voice_name, history):
    """Send user input to Grok, display on LCD, and play voice."""
    print(f"\n🎤 Heard: \"{prompt}\"")
    if arduino and arduino.is_open:
        update_lcd(arduino, f"You: {prompt}")

    print("\n🤖 Grok is writing bars in response...")
    if arduino and arduino.is_open:
        send_to_arduino(arduino, "LINE:3:Grok thinking...")

    reply = ask_grok(prompt, history)
    if reply:
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": reply})
        print(f"\n🔥 Grok:\n{reply}\n")

        # 1. Update LCD screen (auto-scrolls if long)
        if arduino and arduino.is_open:
            update_lcd(arduino, f"Grok: {reply}")

        # 2. Broadcast via OSC
        if osc_client:
            osc_client.send_message("/grok/reply", reply)

        # 3. Speak via xAI Grok TTS
        speak_with_grok_tts(reply, voice_id=voice_name)


def listen_and_transcribe(recognizer, microphone, phrase_limit=5):
    """Capture audio from microphone and convert to text."""
    try:
        with microphone as source:
            print("🎧 [Mic Active] Speak into your laptop microphone now...")
            audio = recognizer.listen(source, timeout=4, phrase_time_limit=phrase_limit)
        
        print("⚡ Transcribing your voice...")
        text = recognizer.recognize_google(audio)
        return text.strip()
    except sr.WaitTimeoutError:
        print("⏱️  (No speech detected)")
        return None
    except sr.UnknownValueError:
        print("🤔 (Could not understand audio)")
        return None
    except Exception as e:
        print(f"⚠️  Speech error: {e}")
        return None


def grok_start_battle(arduino, osc_client, voice_name, history):
    """
    Called when button on Pin 9 is pressed.
    Grok says hi, welcomes the user to the battle, and drops the opening freestyle rap bars!
    """
    print("\n🚀 [START BUTTON PIN 9 PRESSED!] Initializing rap battle...")
    if arduino and arduino.is_open:
        update_lcd(arduino, "Grok: Entering Stage\nGet ready to rap...")

    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROK_API_KEY}",
        "Content-Type": "application/json"
    }
    system_prompt = (
        "You are an energetic, fast-talking freestyle rap battle host and opponent. "
        "Start the battle right now! Give a quick, hype greeting ('Yo! Welcome to the stage!'), "
        "followed immediately by 3 to 4 punchy, fast rhyming opening rap bars challenging the user to step up. "
        "Talk fast like an actual rapper. Output ONLY the spoken words and rap lyrics without any meta notes."
    )

    intro_reply = None
    try:
        res = requests.post(
            url,
            headers=headers,
            json={
                "model": GROK_MODEL,
                "messages": [{"role": "system", "content": system_prompt}],
                "max_tokens": 120,
                "temperature": 1.0
            },
            timeout=12
        )
        if res.status_code == 200:
            intro_reply = res.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"⚠️  Grok start error: {e}")

    if not intro_reply:
        intro_reply = (
            "Yo! Welcome to the stage, the spotlight is lit! "
            "I'm droppin' heavy venom, every bar is a hit! "
            "Grab the mic, flip the switch, let me hear what you got— "
            "Can you match my tempo or you freezin' on the spot?!"
        )

    history.clear()
    history.append({"role": "assistant", "content": intro_reply})

    print(f"\n🔥 Grok Intro:\n{intro_reply}\n")

    # 1. Update LCD screen (auto-scrolls)
    if arduino and arduino.is_open:
        update_lcd(arduino, f"Grok: {intro_reply}")

    # 2. Broadcast via OSC
    if osc_client:
        osc_client.send_message("/grok/reply", intro_reply)

    # 3. Speak via xAI Grok TTS
    speak_with_grok_tts(intro_reply, voice_id=voice_name)

    if arduino and arduino.is_open:
        update_lcd(arduino, "Your Turn!\nFlip switch to speak")


def main():
    parser = argparse.ArgumentParser(description="Grok AI Voice Rap Battle with Arduino")
    parser.add_argument("--voice", type=str, default=DEFAULT_VOICE, help=f"xAI TTS voice ID (default: {DEFAULT_VOICE}, e.g. eve, rex, ara, leo)")
    parser.add_argument("--port", type=str, default=None, help="Serial port for Arduino LCD")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default: 9600)")
    parser.add_argument("--phrase-limit", type=int, default=5, help="Max voice phrase recording seconds (default: 5s)")
    args = parser.parse_args()

    voice_name = args.voice
    explicit_port = args.port
    baud = args.baud
    phrase_limit = args.phrase_limit

    print("=" * 60)
    print("🔥 GROK RAP BATTLE (VOICE + ARDUINO LCD)")
    print(f"   Model: {GROK_MODEL} | Voice: {voice_name}")
    print("=" * 60)

    # Setup OSC
    osc_client = None
    if HAS_OSC:
        try:
            osc_client = udp_client.SimpleUDPClient(OSC_IP, OSC_PORT_SEND)
            print(f"📡 OSC broadcasting to {OSC_IP}:{OSC_PORT_SEND}")
        except Exception as e:
            print(f"⚠️  OSC error: {e}")

    # Setup Microphone
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True
    microphone = sr.Microphone()

    print("\n🎤 Calibrating microphone for ambient room noise...")
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
    print("✨ Microphone ready.")

    # Setup Arduino
    print("\n🔌 Connecting to Arduino LCD...")
    arduino, port = try_connect_arduino(explicit_port, baud)
    if arduino:
        update_lcd(arduino, "Press Pin 9 Button\nto start battle!")
        send_to_arduino(arduino, "STATUS")
    else:
        print("⚠️  Arduino not found initially. Script will retry in background.")

    history = []
    mic_active = False
    start_requested = False
    is_busy = False

    # Thread to monitor serial messages from Arduino
    def serial_monitor():
        nonlocal arduino, mic_active, start_requested
        while True:
            try:
                if arduino is None or not arduino.is_open:
                    arduino, _ = try_connect_arduino(explicit_port, baud)
                    if arduino:
                        send_to_arduino(arduino, "STATUS")
                    time.sleep(2)
                    continue

                if arduino.in_waiting > 0:
                    line = arduino.readline().decode(errors="ignore").strip()
                    if line == "START_BTN:PRESSED":
                        print("\n🔘 [Start Button Pin 9 Pressed]")
                        start_requested = True
                    elif line in ["MIC:ON", "BTN:ON"]:
                        if not mic_active:
                            mic_active = True
                            print("🟢 [Mic Switch Pin 7: ON]")
                    elif line in ["MIC:OFF", "BTN:OFF"]:
                        if mic_active:
                            mic_active = False
                            print("🔴 [Mic Switch Pin 7: OFF]")
                            play_uhh_sound()
                    elif line.startswith("ACK:"):
                        pass
                    elif line:
                        print(f"   [Arduino] {line}")
                time.sleep(0.03)
            except Exception:
                arduino = None
                time.sleep(1)

    t = threading.Thread(target=serial_monitor, daemon=True)
    t.start()

    print("\n" + "=" * 60)
    print("🎮 INSTRUCTIONS:")
    print("  1. Press the Button on PIN 9 to START the battle (Grok will speak first!).")
    print("  2. Turn Switch on PIN 7 ON to activate mic & speak your verse.")
    print("  3. Turn Switch on PIN 7 OFF when done / muted.")
    print("  (You can also type directly in this terminal anytime)")
    print("=" * 60 + "\n")

    # Main interaction loop
    last_mic_state = False
    battle_started = False

    while True:
        try:
            # Step 1: Start battle via Pin 9 button
            if start_requested and not is_busy:
                start_requested = False
                is_busy = True
                battle_started = True
                grok_start_battle(arduino, osc_client, voice_name, history)
                is_busy = False

            # Step 2: User responds using Pin 7 Mic Switch
            if mic_active and not last_mic_state and not is_busy:
                last_mic_state = True
                is_busy = True
                print("\n🎧 [Mic Active] Listening to laptop microphone...")
                if arduino and arduino.is_open:
                    update_lcd(arduino, "Mic Active\nSpit your verse...")

                user_text = listen_and_transcribe(recognizer, microphone, phrase_limit=phrase_limit)
                if user_text:
                    handle_rap_interaction(user_text, arduino, osc_client, voice_name, history)
                else:
                    if arduino and arduino.is_open:
                        update_lcd(arduino, "No voice detected\nFlip switch to retry")

                is_busy = False
            elif not mic_active and last_mic_state:
                last_mic_state = False
                if not is_busy and battle_started and arduino and arduino.is_open:
                    update_lcd(arduino, "Mic Muted\nFlip switch on Pin 7\nto rap again...")

            time.sleep(0.08)

        except (KeyboardInterrupt, EOFError):
            print("\n👋 Battle finished. Goodbye!")
            if arduino and arduino.is_open:
                send_to_arduino(arduino, "CLEAR")
                send_to_arduino(arduino, "LINE:0:Grok Offline")
                arduino.close()
            break


if __name__ == "__main__":
    main()
