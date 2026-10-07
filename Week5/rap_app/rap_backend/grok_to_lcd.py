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
import atexit
import select
try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False
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
BEAT_AUDIO_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "beat.mpeg")
)

# -----------------------------
# AUDIO VOLUME CONFIGURATION (0.0 to 1.0+)
# -----------------------------
BEAT_VOLUME = float(os.getenv("BEAT_VOLUME", "0.35"))   # Rap beat backing track volume
GROK_VOLUME = float(os.getenv("GROK_VOLUME", "1.0"))    # Grok battle bars voice volume
UHH_VOLUME = float(os.getenv("UHH_VOLUME", "0.6"))      # 'Uhh' ad-lib sound effect volume


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
    """Wrap text into clean lines of up to 20 characters, respecting newlines and removing blank lines."""
    raw_lines = text.strip().split("\n")
    wrapped = []
    for rl in raw_lines:
        rl_clean = " ".join(rl.strip().split())
        if not rl_clean:
            continue
        w = textwrap.wrap(rl_clean, width=max_cols)
        wrapped.extend(w)
    if not wrapped:
        wrapped = [""]
    return wrapped


def update_lcd(arduino, text):
    """Format and send full text to Arduino LCD (triggers auto-scrolling if > 4 lines)."""
    lines = format_text_for_lcd(text)
    print("┌" + "─" * LCD_COLS + "┐")
    for r in range(LCD_ROWS):
        line_content = lines[r] if r < len(lines) else ""
        padded = line_content[:LCD_COLS]
        print(f"│{padded.ljust(LCD_COLS)}│")
    print("└" + "─" * LCD_COLS + "┘")
    clean_message = "|".join(lines)
    send_to_arduino(arduino, f"TEXT:{clean_message}")


def speak_with_grok_tts(text, voice_id=DEFAULT_VOICE, volume=None):
    """Synthesize speech using official xAI Grok TTS and play via afplay."""
    if not text:
        return
    if volume is None:
        volume = GROK_VOLUME

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
                print(f"🔊 Playing Grok voice ({len(res.content):,} bytes, vol: {volume})...")
                subprocess.run(["afplay", "-v", str(volume), TTS_AUDIO_FILE], check=False)
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


def play_uhh_sound(volume=None):
    """Play the assets/uhh.mpeg sound effect when the mic is switched off."""
    if volume is None:
        volume = UHH_VOLUME
    target_file = UHH_AUDIO_FILE
    if not os.path.exists(target_file):
        alt = os.path.abspath(os.path.join(os.getcwd(), "assets", "uhh.mpeg"))
        if os.path.exists(alt):
            target_file = alt
        else:
            print(f"⚠️  Audio file not found: {target_file}")
            return

    try:
        print(f"🔊 [Sound FX] Playing {os.path.basename(target_file)} (vol: {volume})...")
        if sys.platform == "darwin":
            subprocess.Popen(["afplay", "-v", str(volume), target_file])
        else:
            subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", target_file])
    except Exception as e:
        print(f"⚠️  Error playing sound effect: {e}")


beat_thread = None
beat_process = None
beat_stop_event = threading.Event()


def _beat_loop_worker():
    global beat_process
    target_file = BEAT_AUDIO_FILE
    if not os.path.exists(target_file):
        alt = os.path.abspath(os.path.join("assets", "beat.mpeg"))
        if os.path.exists(alt):
            target_file = alt
        else:
            print(f"⚠️  Beat audio file not found: {target_file}")
            return

    print(f"🎵 [Beat Loop] Started looping {os.path.basename(target_file)} (vol: {BEAT_VOLUME})...")
    while not beat_stop_event.is_set():
        try:
            if sys.platform == "darwin":
                beat_process = subprocess.Popen(["afplay", "-v", str(BEAT_VOLUME), target_file])
            else:
                beat_process = subprocess.Popen(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", target_file])

            while beat_process.poll() is None:
                if beat_stop_event.is_set():
                    beat_process.terminate()
                    try:
                        beat_process.wait(timeout=0.5)
                    except Exception:
                        beat_process.kill()
                    return
                time.sleep(0.05)
        except Exception as e:
            print(f"⚠️  Beat loop error: {e}")
            break


def start_beat_loop():
    """Start playing assets/beat.mpeg in a loop in the background."""
    global beat_thread, beat_stop_event
    if beat_thread and beat_thread.is_alive():
        return
    beat_stop_event.clear()
    beat_thread = threading.Thread(target=_beat_loop_worker, daemon=True)
    beat_thread.start()


def stop_beat_loop():
    """Stop the beat loop and terminate any active player process."""
    global beat_stop_event, beat_process
    beat_stop_event.set()
    if beat_process and beat_process.poll() is None:
        try:
            beat_process.terminate()
            beat_process.wait(timeout=0.5)
        except Exception:
            try:
                beat_process.kill()
            except Exception:
                pass


atexit.register(stop_beat_loop)


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
        "You are an energetic, witty freestyle rap battle MC. "
        "You are rapping over a 4/4 hip-hop beat at 96 BPM (1 bar = 4 beats). "
        "Respond directly to what the user said with exactly 2 rhyming bars (couplet). "
        "RHYTHM AND METER RULES:\n"
        "- Exactly 2 rhyming lines that rhyme with each other (AA scheme).\n"
        "- Each line MUST have exactly 8 to 10 syllables (around 6 to 8 words per line) so it fills one 4-beat bar.\n"
        "- Use commas to mark natural rhythmic pauses on the beat.\n"
        "- Total word count must be between 12 and 18 words total.\n"
        "- Keep it punchy, rhythmic, and clever.\n"
        "- Output ONLY the spoken rap lyrics without quotes, titles, emojis, or intro notes."
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
    prompt_clean = " ".join(prompt.strip().split())
    if len(prompt_clean) > 36:
        prompt_display = prompt_clean[:33] + "..."
    else:
        prompt_display = prompt_clean

    print("\n🤖 Grok is writing bars in response...")
    update_lcd(arduino, f"You: {prompt_display}\nGrok thinking...")

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
        "You are an energetic freestyle rap battle host and opponent MC. "
        "You are dropping the opening bars over a 4/4 boom-bap beat at 96 BPM. "
        "Start the battle right now! Challenge the user to step up to the mic. "
        "RHYTHM AND METER RULES:\n"
        "- Exactly 2 rhyming bars (couplet).\n"
        "- Each line MUST have 8 to 10 syllables (around 6 to 8 words per line) to fit a 4-beat musical measure.\n"
        "- Tight internal bounce, punchy delivery, and hard end rhymes.\n"
        "- Use commas for rhythmic pauses.\n"
        "- Total length must be under 18 words.\n"
        "- Output ONLY the spoken rap bars without quotes, titles, emojis, or stage notes."
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
            "Your turn, contestant!"
            "Finished a line? Flip the switch!"
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
    global BEAT_VOLUME, GROK_VOLUME, UHH_VOLUME

    parser = argparse.ArgumentParser(description="Grok AI Voice Rap Battle with Arduino")
    parser.add_argument("--voice", type=str, default=DEFAULT_VOICE, help=f"xAI TTS voice ID (default: {DEFAULT_VOICE}, e.g. eve, rex, ara, leo)")
    parser.add_argument("--port", type=str, default=None, help="Serial port for Arduino LCD")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default: 9600)")
    parser.add_argument("--phrase-limit", type=int, default=5, help="Max voice phrase recording seconds (default: 5s)")
    parser.add_argument("--beat-volume", type=float, default=BEAT_VOLUME, help=f"Beat audio volume from 0.0 to 1.0+ (default: {BEAT_VOLUME})")
    parser.add_argument("--grok-volume", type=float, default=GROK_VOLUME, help=f"Grok voice volume from 0.0 to 1.0+ (default: {GROK_VOLUME})")
    parser.add_argument("--uhh-volume", type=float, default=UHH_VOLUME, help=f"Uhh sound FX volume from 0.0 to 1.0+ (default: {UHH_VOLUME})")
    args = parser.parse_args()

    BEAT_VOLUME = args.beat_volume
    GROK_VOLUME = args.grok_volume
    UHH_VOLUME = args.uhh_volume

    voice_name = args.voice
    explicit_port = args.port
    baud = args.baud
    phrase_limit = args.phrase_limit

    print("=" * 60)
    print("🔥 GROK RAP BATTLE (VOICE + ARDUINO LCD)")
    print(f"   Model: {GROK_MODEL} | Voice: {voice_name}")
    print(f"   Volumes: Beat={BEAT_VOLUME} | Grok={GROK_VOLUME} | FX={UHH_VOLUME}")
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
        update_lcd(arduino, "Are you ready to battle!?")
        send_to_arduino(arduino, "STATUS")
    else:
        print("⚠️  Arduino not found. Running in KEYBOARD TEST mode (will auto-connect if plugged in).")
        update_lcd(None, "Are you ready to battle!?")

    history = []
    mic_active = False
    pin9_requested = False
    is_busy = False
    pending_typed_verse = None

    # Thread to monitor serial messages from Arduino
    def serial_monitor():
        nonlocal arduino, mic_active, pin9_requested
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
                        print("\n🔘 [Start/Stop Button Pin 9 Pressed]")
                        pin9_requested = True
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

    t_serial = threading.Thread(target=serial_monitor, daemon=True)
    t_serial.start()

    # Terminal state management for keyboard monitoring
    kbd_fd = None
    kbd_old_settings = None
    is_tty = False

    if HAS_TERMIOS and sys.stdin.isatty():
        try:
            kbd_fd = sys.stdin.fileno()
            kbd_old_settings = termios.tcgetattr(kbd_fd)
            tty.setcbreak(kbd_fd)
            is_tty = True
        except Exception:
            is_tty = False

    def restore_terminal():
        nonlocal is_tty, kbd_fd, kbd_old_settings
        if is_tty and kbd_fd is not None and kbd_old_settings is not None:
            try:
                termios.tcsetattr(kbd_fd, termios.TCSADRAIN, kbd_old_settings)
            except Exception:
                pass

    atexit.register(restore_terminal)

    # Thread to monitor keyboard input for testing without Arduino
    def keyboard_monitor():
        nonlocal mic_active, pin9_requested, pending_typed_verse, is_busy, is_tty, kbd_fd, battle_started

        while True:
            try:
                if is_tty:
                    r, _, _ = select.select([sys.stdin], [], [], 0.08)
                    if not r:
                        continue
                    ch = sys.stdin.read(1)
                    if not ch:
                        continue

                    if ch in ['s', 'S', ' ']:
                        if not battle_started:
                            print("\n🔘 [Keyboard: Pin 9 (Start Battle)]")
                        else:
                            print("\n🔘 [Keyboard: Pin 9 (Stop Battle)]")
                        pin9_requested = True
                    elif ch in ['m', 'M']:
                        if not mic_active:
                            mic_active = True
                            print("\n🟢 [Keyboard: Mic ON (Pin 7) - Speak now! Press 'm' again to finish]")
                        else:
                            mic_active = False
                            print("\n🔴 [Keyboard: Mic OFF (Pin 7)]")
                            play_uhh_sound()
                    elif ch in ['b', 'B']:
                        if beat_stop_event.is_set() or beat_thread is None or not beat_thread.is_alive():
                            print("\n🎵 [Keyboard: Beat Loop ON]")
                            start_beat_loop()
                        else:
                            print("\n⏹️  [Keyboard: Beat Loop OFF]")
                            stop_beat_loop()
                    elif ch in ['u', 'U']:
                        print("\n🔊 [Keyboard: Play 'uhh.mpeg' FX]")
                        play_uhh_sound()
                    elif ch in ['t', 'T']:
                        # Temporarily restore canonical mode so user can type line
                        restore_terminal()
                        try:
                            print("\n" + "─" * 40)
                            verse = input("✍️  Type your rap verse: ").strip()
                            print("─" * 40)
                            if verse:
                                play_uhh_sound()
                                pending_typed_verse = verse
                        finally:
                            if HAS_TERMIOS and kbd_fd is not None:
                                try:
                                    tty.setcbreak(kbd_fd)
                                except Exception:
                                    pass
                    elif ch in ['q', 'Q']:
                        print("\n👋 Quit requested via keyboard.")
                        restore_terminal()
                        stop_beat_loop()
                        os._exit(0)
                else:
                    # Non-TTY fallback (line-based)
                    line = sys.stdin.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
                    cmd = line.strip().lower()
                    if cmd in ['s', 'start', 'stop', 'space']:
                        if not battle_started:
                            print("\n🔘 [Keyboard: Pin 9 (Start Battle)]")
                        else:
                            print("\n🔘 [Keyboard: Pin 9 (Stop Battle)]")
                        pin9_requested = True
                    elif cmd in ['m', 'mic']:
                        if not mic_active:
                            mic_active = True
                            print("\n🟢 [Keyboard: Mic ON (Pin 7)]")
                        else:
                            mic_active = False
                            print("\n🔴 [Keyboard: Mic OFF (Pin 7)]")
                            play_uhh_sound()
                    elif cmd in ['b', 'beat']:
                        if beat_stop_event.is_set() or beat_thread is None or not beat_thread.is_alive():
                            start_beat_loop()
                        else:
                            stop_beat_loop()
                    elif cmd in ['u', 'uhh']:
                        play_uhh_sound()
                    elif cmd in ['q', 'quit', 'exit']:
                        stop_beat_loop()
                        os._exit(0)
                    elif cmd:
                        play_uhh_sound()
                        pending_typed_verse = line.strip()
            except Exception:
                time.sleep(0.08)

    t_kbd = threading.Thread(target=keyboard_monitor, daemon=True)
    t_kbd.start()

    print("\n" + "=" * 60)
    print("🎮 CONTROLS (ARDUINO & KEYBOARD):")
    print("  [S] or [SPACE]  : Start / Stop Battle Round (Pin 9 button)")
    print("  [M]             : Toggle Mic ON / OFF (simulates Pin 7 switch)")
    print("  [T]             : Type a rap verse directly in terminal")
    print("  [B]             : Toggle Beat backing track ON / OFF")
    print("  [U]             : Play 'uhh.mpeg' test")
    print("  [Q] or [Ctrl+C] : Quit")
    print("=" * 60 + "\n")

    # Main interaction loop
    last_mic_state = False
    battle_started = False

    while True:
        try:
            # Step 1: Handle Pin 9 button or Keyboard [S]/[SPACE] (Toggle Start/Stop)
            if pin9_requested and not is_busy:
                pin9_requested = False
                if not battle_started:
                    print("\n🚀 [START BATTLE] Initializing rap battle round...")
                    is_busy = True
                    battle_started = True
                    start_beat_loop()
                    grok_start_battle(arduino, osc_client, voice_name, history)
                    is_busy = False
                else:
                    print("\n🏁 [STOP BATTLE] Ending rap battle round!")
                    battle_started = False
                    mic_active = False
                    last_mic_state = False
                    stop_beat_loop()
                    end_round_msg = "Wow, that round was fire!\nNow let's see the votes."
                    update_lcd(arduino, end_round_msg)
                    if osc_client:
                        try:
                            osc_client.send_message("/battle/round_ended", end_round_msg)
                        except Exception:
                            pass

            # Step 2: User responds using Pin 7 Mic Switch or Keyboard [M]
            if mic_active and not last_mic_state and not is_busy:
                last_mic_state = True
                is_busy = True
                print("\n🎧 [Mic Active] Listening to laptop microphone...")
                update_lcd(arduino, "Mic Active\nSpit your verse...")

                user_text = listen_and_transcribe(recognizer, microphone, phrase_limit=phrase_limit)
                if user_text:
                    handle_rap_interaction(user_text, arduino, osc_client, voice_name, history)
                else:
                    update_lcd(arduino, "No voice detected\nFlip switch / press 'm'")

                is_busy = False
            elif not mic_active and last_mic_state:
                last_mic_state = False
                if not is_busy and battle_started:
                    update_lcd(arduino, "Mic Muted\nFlip switch / press 'm'\nto rap again...")

            # Step 3: User responded by typing a custom verse [T]
            if pending_typed_verse and not is_busy:
                verse = pending_typed_verse
                pending_typed_verse = None
                is_busy = True
                battle_started = True
                handle_rap_interaction(verse, arduino, osc_client, voice_name, history)
                is_busy = False

            time.sleep(0.08)

        except (KeyboardInterrupt, EOFError):
            print("\n👋 Battle finished. Goodbye!")
            restore_terminal()
            stop_beat_loop()
            if arduino and arduino.is_open:
                send_to_arduino(arduino, "CLEAR")
                send_to_arduino(arduino, "LINE:0:Grok Offline")
                arduino.close()
            break


if __name__ == "__main__":
    main()
