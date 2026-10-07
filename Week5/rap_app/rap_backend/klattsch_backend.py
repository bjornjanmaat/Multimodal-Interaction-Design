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
import random
try:
    import termios
    import tty
    HAS_TERMIOS = True
except ImportError:
    HAS_TERMIOS = False
import requests
import speech_recognition as sr
try:
    import pyaudio
except ImportError:
    pyaudio = None
try:
    import pyttsx3
    HAS_PYTTSX3 = True
except ImportError:
    HAS_PYTTSX3 = False
import numpy as np
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False
from dotenv import load_dotenv

# Load .env (looking for GROK_API_KEY and Supabase credentials)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "vote_app", ".env"))
load_dotenv()

try:
    from google import genai
    from google.genai import types as genai_types
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

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
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROK_API_KEY = os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROK_MODEL = os.getenv("GROK_MODEL", "grok-3-mini")
GROQ_TIMEOUT = int(os.getenv("GROQ_TIMEOUT", "10"))
GROK_TIMEOUT = int(os.getenv("GROK_TIMEOUT", "20"))
DEFAULT_VOICE = "eve"          # Legacy voice ID
DEFAULT_WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
DEFAULT_WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")
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

# Supabase Vote Configuration (for 6-LED Vote Partition)
SUPABASE_URL = (os.getenv("VITE_SUPABASE_URL") or os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.getenv("VITE_SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY")

# -----------------------------
# AUDIO VOLUME CONFIGURATION (0.0 to 1.0+)
# -----------------------------
BEAT_VOLUME = float(os.getenv("BEAT_VOLUME", "0.35"))   # Rap beat backing track volume
GROK_VOLUME = float(os.getenv("GROK_VOLUME", "1.0"))    # Grok battle bars voice volume
UHH_VOLUME = float(os.getenv("UHH_VOLUME", "0.6"))      # 'Uhh' ad-lib sound effect volume

# Render the Klattsch clips with these exact filenames.
HOST_WAV_FILES = {
    "ready": "../assets/01_ready_to_battle.wav",
    "your_turn": "../assets/02_your_turn_contestant.wav",
    "finish_line": "../assets/03_finished_line_flip_switch.wav",
    "round_end": "../assets/04_round_was_fire_votes.wav",
}


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


KLATTSCH_SCRIPT = os.path.join(os.path.dirname(__file__), "klattsch_tts.js")
KLATTSCH_WAV_FILE = "/tmp/klattsch_tts_verse.wav"


def speak_with_klattsch_tts(text, voice_id=None, volume=None):
    """
    Synthesize speech using Klattsch retro formant speech synthesizer.
    Produces the iconic robotic, retro Klatt voice used by the Klattsch host.
    Falls back to local Python TTS (pyttsx3 / macOS say) if Node or Klattsch fails.
    """
    if not text:
        return
    if volume is None:
        volume = GROK_VOLUME

    clean = text.replace("*", "").replace("#", "").replace('"', '').strip()

    # 1. Primary: Klattsch Formant Synthesizer
    if os.path.exists(KLATTSCH_SCRIPT):
        try:
            print(f"🗣️  Speaking with Klattsch TTS (vol: {volume})...")
            res = subprocess.run(
                ["node", KLATTSCH_SCRIPT, clean, KLATTSCH_WAV_FILE],
                capture_output=True,
                text=True,
                timeout=12
            )
            if res.returncode == 0 and os.path.exists(KLATTSCH_WAV_FILE) and os.path.getsize(KLATTSCH_WAV_FILE) > 100:
                if sys.platform == "darwin":
                    subprocess.run(["afplay", "-v", str(volume), KLATTSCH_WAV_FILE], check=False)
                else:
                    subprocess.run(["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", KLATTSCH_WAV_FILE], check=False)
                return
            else:
                print(f"⚠️  Klattsch synthesis notice: {res.stderr.strip() or res.stdout.strip()}")
        except Exception as e:
            print(f"⚠️  Klattsch error: {e}, falling back to Python TTS...")

    # 2. Fallback: pyttsx3 (simple, fast Python TTS)
    if HAS_PYTTSX3:
        try:
            print(f"🔊 Fallback speaking with pyttsx3 (vol: {volume})...")
            engine = pyttsx3.init()
            engine.setProperty("rate", 185)  # Punchy hip-hop cadence
            engine.setProperty("volume", min(1.0, max(0.0, volume)))
            engine.say(clean)
            engine.runAndWait()
            return
        except Exception as e:
            print(f"⚠️  pyttsx3 error: {e}, falling back to system TTS...")

    # 3. Fallback: local system TTS (instantaneous on macOS)
    try:
        print(f"🔊 Fallback speaking with system TTS: \"{clean}\"")
        if sys.platform == "darwin":
            subprocess.run(["say", "-r", "185", clean], check=False)
        else:
            subprocess.run(["espeak", clean], check=False)
    except Exception as e:
        print(f"⚠️  TTS error: {e}")


# Aliases so existing calls continue to work seamlessly
speak_with_python_tts = speak_with_klattsch_tts
speak_with_grok_tts = speak_with_klattsch_tts

def play_host_wav(cue_name):
    """Play one pre-rendered Klattsch host line, blocking until it ends."""
    filename = HOST_WAV_FILES.get(cue_name)
    if not filename:
        print(f"⚠️  Unknown Klattsch cue: {cue_name}")
        return False

    path = os.path.abspath(os.path.join(os.path.dirname(__file__), filename))
    if not os.path.isfile(path):
        print(f"🔇 Klattsch cue '{cue_name}' not found yet: {path}")
        return False

    try:
        print(f"🗣️  Klattsch host: {filename}")
        subprocess.run(["afplay", path], check=False)
        return True
    except Exception as error:
        print(f"⚠️  Could not play Klattsch WAV '{filename}': {error}")
        return False


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


# -----------------------------
# SUPABASE VOTE & LED MONITOR (PINS 4,5,6 & 10,11,12)
# -----------------------------
voting_thread = None
voting_stop_event = threading.Event()


def fetch_supabase_votes(url=None, key=None):
    """Fetch all rows from Supabase public.ratings and return vote counts."""
    target_url = (url or SUPABASE_URL or "").rstrip("/")
    target_key = key or SUPABASE_KEY
    if not target_url or not target_key:
        return None, 0, 0, 0.0

    endpoint = f"{target_url}/rest/v1/ratings?select=winner"
    headers = {
        "apikey": target_key,
        "Authorization": f"Bearer {target_key}"
    }

    try:
        response = requests.get(endpoint, headers=headers, timeout=4)
        if response.status_code == 200:
            data = response.json()
            total = len(data)
            machine_count = sum(1 for item in data if (item.get("winner") or "").strip().lower() in ("machine", "bot"))
            man_count = sum(1 for item in data if (item.get("winner") or "").strip().lower() in ("man", "person"))
            machine_ratio = (machine_count / total) if total > 0 else 0.0
            return total, machine_count, man_count, machine_ratio
        else:
            print(f"⚠️  Supabase ratings endpoint returned {response.status_code}")
    except requests.RequestException as e:
        print(f"⚠️  Supabase fetch error: {e}")

    return None, 0, 0, 0.0


def compute_partition_leds(man_votes, machine_votes):
    """
    Calculate 0-3 LED partition for Man (pins 4, 5, 6) and Machine (pins 10, 11, 12).
    - If a party has 0 votes, 0 LEDs.
    - If 100% of votes, 3 LEDs.
    - If both have votes, proportional partition rounded to 0-3 with at least 1 LED.
    """
    total = man_votes + machine_votes
    if total <= 0:
        return 0, 0
    if machine_votes == 0:
        return 3, 0
    if man_votes == 0:
        return 0, 3

    man_share = man_votes / total
    machine_share = machine_votes / total

    man_leds = round(man_share * 3.0)
    machine_leds = round(machine_share * 3.0)

    if man_votes > 0 and man_leds < 1:
        man_leds = 1
    if machine_votes > 0 and machine_leds < 1:
        machine_leds = 1

    return max(0, min(3, int(man_leds))), max(0, min(3, int(machine_leds)))


def trigger_round_vote_leds(arduino, osc_client=None):
    """
    Fetch votes from Supabase, display formatted results,
    light up the LEDs on Arduino pins 4,5,6 and 10,11,12,
    and broadcast over OSC.
    """
    total, machine_count, man_count, _ = fetch_supabase_votes()
    if total is None:
        total, machine_count, man_count = 0, 0, 0

    man_leds, machine_leds = compute_partition_leds(man_count, machine_count)

    print("\n" + "═" * 58)
    print("🗳️  SUPABASE VOTE RESULTS & LED PARTITION")
    print(f"   Total Votes: {total}")
    man_pins = [f"Pin {p}" for p in [4, 5, 6][:man_leds]] or ["All OFF"]
    machine_pins = [f"Pin {p}" for p in [10, 11, 12][:machine_leds]] or ["All OFF"]
    print(f"   🧑 Man:     {man_count} votes → {man_leds}/3 LEDs ({', '.join(man_pins)})")
    print(f"   🤖 Machine: {machine_count} votes → {machine_leds}/3 LEDs ({', '.join(machine_pins)})")
    print("═" * 58 + "\n")

    if arduino and arduino.is_open:
        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")

    if osc_client:
        try:
            osc_client.send_message("/battle/votes", f"{man_count},{machine_count},{man_leds},{machine_leds}")
        except Exception:
            pass

    return total, man_count, machine_count, man_leds, machine_leds


def start_vote_polling(arduino, osc_client=None, poll_interval=1.5):
    """Start background thread to dynamically poll Supabase votes and update LEDs."""
    global voting_thread, voting_stop_event
    stop_vote_polling()
    voting_stop_event.clear()

    def _poll_loop():
        last_total = None
        last_man_leds = None
        last_machine_leds = None

        while not voting_stop_event.is_set():
            total, machine_count, man_count, _ = fetch_supabase_votes()
            if total is not None:
                man_leds, machine_leds = compute_partition_leds(man_count, machine_count)
                if last_total is None:
                    last_total = total
                    last_man_leds = man_leds
                    last_machine_leds = machine_leds
                    if arduino and arduino.is_open:
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")
                elif total > last_total:
                    diff = total - last_total
                    print(f"\n🗳️  [NEW VOTE] +{diff} new vote(s)! Total: {total} (Man: {man_count}, Machine: {machine_count})")
                    if arduino and arduino.is_open:
                        send_to_arduino(arduino, f"NEW_VOTE:{diff}")
                        time.sleep(diff * 0.15)
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")
                    if osc_client:
                        try:
                            osc_client.send_message("/battle/votes", f"{man_count},{machine_count},{man_leds},{machine_leds}")
                        except Exception:
                            pass
                    last_total = total
                    last_man_leds = man_leds
                    last_machine_leds = machine_leds
                elif man_leds != last_man_leds or machine_leds != last_machine_leds:
                    print(f"📊 [PARTITION SHIFT] Man: {last_man_leds}→{man_leds}/3 | Machine: {last_machine_leds}→{machine_leds}/3")
                    if arduino and arduino.is_open:
                        send_to_arduino(arduino, f"VOTES:{man_count},{machine_count}")
                    last_man_leds = man_leds
                    last_machine_leds = machine_leds

            # Non-blocking sleep responsive to stop_event
            for _ in range(int(poll_interval * 10)):
                if voting_stop_event.is_set():
                    break
                time.sleep(0.1)

    voting_thread = threading.Thread(target=_poll_loop, daemon=True)
    voting_thread.start()


def stop_vote_polling():
    """Stop the background Supabase vote polling thread."""
    global voting_thread, voting_stop_event
    voting_stop_event.set()
    if voting_thread and voting_thread.is_alive():
        voting_thread.join(timeout=0.6)
        voting_thread = None


atexit.register(stop_vote_polling)


gemini_client = None

def get_gemini_client():
    """Lazy-initialize Google GenAI client."""
    global gemini_client
    if gemini_client is None and HAS_GEMINI and GEMINI_API_KEY:
        try:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            print(f"⚠️  Gemini Client init error: {e}")
    return gemini_client


def ask_gemini(user_input, history=None):
    """Call Google Gemini Flash API to generate ultra-fast rhyming rap bars."""
    system_prompt = (
        "You are an energetic, witty freestyle rap battle MC. "
        "You are rapping over a 4/4 hip-hop beat at 96 BPM (1 bar = 4 beats). "
        "Respond directly to what the user said with exactly 2 rhyming bars (couplet).\n"
        "RHYTHM AND METER RULES:\n"
        "- Exactly 2 rhyming lines that rhyme with each other (AA scheme).\n"
        "- Each line MUST have exactly 8 to 10 syllables (around 6 to 8 words per line) so it fills one 4-beat bar.\n"
        "- Use commas to mark natural rhythmic pauses on the beat.\n"
        "- Total word count must be between 12 and 18 words total.\n"
        "- Keep it punchy, rhythmic, and clever.\n"
        "- Output ONLY the spoken rap lyrics without quotes, titles, emojis, or intro notes."
    )

    # 1. Primary: Gemini Flash (Google GenAI)
    client = get_gemini_client()
    if client:
        candidate_models = [
            GEMINI_MODEL,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest"
        ]
        candidate_models = list(dict.fromkeys(candidate_models))

        contents = []
        if history:
            for msg in history[-4:]:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(genai_types.Content(
                    role=role,
                    parts=[genai_types.Part.from_text(text=msg["content"])]
                ))
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=user_input)]
        ))

        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.85,
            max_output_tokens=100
        )

        for model in candidate_models:
            try:
                res = client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )
                if res and res.text:
                    reply = res.text.strip()
                    if reply:
                        return reply
            except Exception as e:
                print(f"⚠️  Gemini ({model}) error: {e}")

    # 2. Fallback: Groq LPU API
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])
    messages.append({"role": "user", "content": user_input})

    if GROQ_API_KEY:
        groq_url = "https://api.groq.com/openai/v1/chat/completions"
        groq_headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        for model in [GROQ_MODEL, "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]:
            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": 80,
                    "temperature": 0.85
                }
                res = requests.post(groq_url, headers=groq_headers, json=payload, timeout=GROQ_TIMEOUT)
                if res.status_code == 200:
                    reply = res.json()["choices"][0]["message"]["content"].strip()
                    if reply:
                        return reply
            except Exception as e:
                print(f"⚠️  Groq ({model}) fallback error: {e}")

    # 3. Fallback: xAI Grok
    if GROK_API_KEY:
        try:
            grok_url = "https://api.x.ai/v1/chat/completions"
            grok_headers = {
                "Authorization": f"Bearer {GROK_API_KEY}",
                "Content-Type": "application/json"
            }
            res = requests.post(
                grok_url,
                headers=grok_headers,
                json={
                    "model": GROK_MODEL,
                    "messages": messages,
                    "max_tokens": 80,
                    "temperature": 1.0
                },
                timeout=GROK_TIMEOUT
            )
            if res.status_code == 200:
                reply = res.json()["choices"][0]["message"]["content"].strip()
                if reply:
                    return reply
        except Exception as e:
            print(f"⚠️  xAI Grok fallback error: {e}")

    # 4. Emergency fallback rhyme so the battle NEVER hangs
    print("⚡ Using emergency battle comeback bar...")
    emergency_fallbacks = [
        "You spitting fire or is my network slow?\nEither way I'm the king of this whole rap show!",
        "WiFi glitched but you still can't match my beat,\nStep back contestant, you just faced defeat!",
        "Servers lagging but my bars are always tight,\nFlip the switch again, let's keep up the fight!",
        "I had to pause to let you catch your breath,\nStep up to the mic, I'm spitting lyrical death!"
    ]
    return random.choice(emergency_fallbacks)


ask_groq = ask_gemini
ask_grok = ask_gemini


def handle_rap_interaction(prompt, arduino, osc_client, voice_name, history):
    """Send user input to Gemini Flash, display on LCD, and speak with Python TTS."""
    print(f"\n🎤 Heard: \"{prompt}\"")
    prompt_clean = " ".join(prompt.strip().split())
    if len(prompt_clean) > 36:
        prompt_display = prompt_clean[:33] + "..."
    else:
        prompt_display = prompt_clean

    print("\n🤖 Machine (Gemini Flash) is writing bars in response...")
    update_lcd(arduino, f"You: {prompt_display}\nMachine thinking...")

    reply = ask_gemini(prompt, history)
    if reply:
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": reply})
        print(f"\n🔥 Machine (Gemini Flash):\n{reply}\n")

        # 1. Update LCD screen (auto-scrolls if long)
        if arduino and arduino.is_open:
            update_lcd(arduino, f"Machine: {reply}")

        # 2. Broadcast via OSC
        if osc_client:
            osc_client.send_message("/grok/reply", reply)

        # 3. Speak via local Python TTS
        speak_with_python_tts(reply, voice_id=voice_name)


class ContinuousRecorder:
    """
    Continuously records microphone audio frames into memory while mic is ON.
    Stops and returns SpeechRecognition AudioData immediately when mic is switched OFF.
    Eliminates premature silence cutoffs and phrase timeouts while rapping.
    """
    def __init__(self, sample_rate=16000, chunk_size=1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.p = None
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.thread = None
        self.lock = threading.Lock()
        self.start_time = 0

    def start(self):
        with self.lock:
            if self.is_recording:
                return
            if pyaudio is None:
                print("❌ Error: PyAudio is not installed. Run 'pip install pyaudio'.")
                return

            self.frames = []
            self.is_recording = True
            self.start_time = time.time()
            try:
                if self.p is None:
                    self.p = pyaudio.PyAudio()
                self.stream = self.p.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=self.chunk_size
                )
            except Exception as e:
                print(f"⚠️  Error opening microphone stream: {e}")
                self.is_recording = False
                return

            def _record_loop():
                while self.is_recording:
                    try:
                        data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                        if data:
                            self.frames.append(data)
                    except Exception:
                        pass
                    if time.time() - self.start_time > 60:
                        print("\n⏱️  [Safety Limit] Maximum 60s recording reached.")
                        break

            self.thread = threading.Thread(target=_record_loop, daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            if not self.is_recording:
                return None
            self.is_recording = False
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=0.6)
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            if not self.frames:
                return None
            raw_bytes = b"".join(self.frames)
            return sr.AudioData(raw_bytes, self.sample_rate, 2)

    def close(self):
        self.stop()
        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None


def transcribe_audio(audio_data, whisper_model=None, language=DEFAULT_WHISPER_LANGUAGE, recognizer=None):
    """
    Convert recorded AudioData to text using OpenAI Whisper (offline, robust for rap & music).
    Falls back to Google Speech Recognition if Whisper is unavailable.
    """
    if not audio_data:
        return None

    # 1. Primary: OpenAI Whisper
    if whisper_model is not None:
        try:
            print("⚡ Transcribing with OpenAI Whisper...")
            raw_audio = audio_data.get_raw_data(convert_rate=16000, convert_width=2)
            audio_array = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0

            transcribe_kwargs = {
                "audio": audio_array,
                "fp16": False,
            }
            if language and language.lower() != "auto":
                transcribe_kwargs["language"] = language

            result = whisper_model.transcribe(**transcribe_kwargs)
            text = (result.get("text") or "").strip()
            if text:
                return text
            else:
                print("🤔 (Whisper detected silence or empty audio)")
                return None
        except Exception as e:
            print(f"⚠️  Whisper error: {e}, falling back to Google Speech...")

    # 2. Fallback: Google Speech Recognition
    if recognizer is not None:
        try:
            print("⚡ Transcribing with Google Speech Recognition...")
            text = recognizer.recognize_google(audio_data)
            return text.strip()
        except sr.UnknownValueError:
            print("🤔 (Could not understand audio or no speech detected)")
            return None
        except Exception as e:
            print(f"⚠️  Speech error: {e}")
            return None

    return None


def gemini_start_battle(arduino, osc_client, voice_name, history):
    """
    Called when button on Pin 9 is pressed.
    Gemini says hi, welcomes the user to the battle, and drops the opening freestyle rap bars!
    """
    print("\n🚀 [START BUTTON PIN 9 PRESSED!] Initializing Gemini rap battle...")
    if arduino and arduino.is_open:
        update_lcd(arduino, "Machine Entering Stage\nGet ready to rap...")

    system_prompt = (
        "You are an energetic freestyle rap battle host and opponent MC. "
        "You are dropping the opening bars over a 4/4 boom-bap beat at 96 BPM. "
        "Start the battle right now! Challenge the user to step up to the mic.\n"
        "RHYTHM AND METER RULES:\n"
        "- Exactly 2 rhyming bars (couplet).\n"
        "- Each line MUST have 8 to 10 syllables (around 6 to 8 words per line) to fit a 4-beat musical measure.\n"
        "- Tight internal bounce, punchy delivery, and hard end rhymes.\n"
        "- Use commas for rhythmic pauses.\n"
        "- Total length must be under 18 words.\n"
        "- Output ONLY the spoken rap bars without quotes, titles, emojis, or stage notes."
    )

    intro_reply = None

    # 1. Primary: Gemini Flash
    client = get_gemini_client()
    if client:
        candidate_models = [
            GEMINI_MODEL,
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-flash-latest"
        ]
        candidate_models = list(dict.fromkeys(candidate_models))
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.85,
            max_output_tokens=100
        )
        for model in candidate_models:
            try:
                res = client.models.generate_content(
                    model=model,
                    contents="Start the rap battle now with 2 fire opening bars!",
                    config=config
                )
                if res and res.text:
                    intro_reply = res.text.strip()
                    if intro_reply:
                        break
            except Exception as e:
                print(f"⚠️  Gemini start error ({model}): {e}")

    # 2. Fallback: Groq LPU API
    if not intro_reply and GROQ_API_KEY:
        try:
            groq_url = "https://api.groq.com/openai/v1/chat/completions"
            groq_headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            res = requests.post(
                groq_url,
                headers=groq_headers,
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "system", "content": system_prompt}],
                    "max_tokens": 80,
                    "temperature": 0.85
                },
                timeout=GROQ_TIMEOUT
            )
            if res.status_code == 200:
                intro_reply = res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"⚠️  Groq start error: {e}")

    # 3. Fallback: xAI Grok
    if not intro_reply and GROK_API_KEY:
        try:
            res = requests.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": GROK_MODEL,
                    "messages": [{"role": "system", "content": system_prompt}],
                    "max_tokens": 80,
                    "temperature": 1.0
                },
                timeout=GROK_TIMEOUT
            )
            if res.status_code == 200:
                intro_reply = res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"⚠️  xAI Grok start error: {e}")

    if not intro_reply:
        intro_reply = (
            "Your turn, contestant!\n"
            "Finished a line? Flip the switch!"
        )

    history.clear()
    history.append({"role": "assistant", "content": intro_reply})

    print(f"\n🔥 Machine (Gemini Flash) Intro:\n{intro_reply}\n")

    # 1. Update LCD screen (auto-scrolls)
    if arduino and arduino.is_open:
        update_lcd(arduino, f"Machine: {intro_reply}")

    # 2. Broadcast via OSC
    if osc_client:
        osc_client.send_message("/grok/reply", intro_reply)

    # 3. Speak via Python TTS
    speak_with_python_tts(intro_reply, voice_id=voice_name)

    if arduino and arduino.is_open:
        update_lcd(arduino, "Your Turn Contestant! Finished a line? Flip the switch!")
        play_host_wav("your_turn")
        play_host_wav("finish_line")


groq_start_battle = gemini_start_battle
grok_start_battle = gemini_start_battle



def main():
    global BEAT_VOLUME, GROK_VOLUME, UHH_VOLUME, GROK_MODEL, GROQ_MODEL, GEMINI_MODEL

    parser = argparse.ArgumentParser(description="Gemini Flash AI Rap Battle with Arduino & Whisper STT")
    parser.add_argument("--gemini-model", type=str, default=GEMINI_MODEL, help=f"Gemini LLM model (default: {GEMINI_MODEL}, e.g. gemini-2.5-flash, gemini-2.0-flash)")
    parser.add_argument("--groq-model", type=str, default=GROQ_MODEL, help=f"Groq LLM model (default: {GROQ_MODEL}, e.g. openai/gpt-oss-120b)")
    parser.add_argument("--model", type=str, default=GROK_MODEL, help=f"Fallback xAI Grok model (default: {GROK_MODEL}, e.g. grok-3-mini, grok-3)")
    parser.add_argument("--voice", type=str, default=DEFAULT_VOICE, help=f"Voice identifier (default: {DEFAULT_VOICE})")
    parser.add_argument("--port", type=str, default=None, help="Serial port for Arduino LCD")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="Baud rate (default: 9600)")
    parser.add_argument("--phrase-limit", type=int, default=5, help="Max voice phrase recording seconds (default: 5s)")
    parser.add_argument("--beat-volume", type=float, default=BEAT_VOLUME, help=f"Beat audio volume from 0.0 to 1.0+ (default: {BEAT_VOLUME})")
    parser.add_argument("--grok-volume", type=float, default=GROK_VOLUME, help=f"Voice volume from 0.0 to 1.0+ (default: {GROK_VOLUME})")
    parser.add_argument("--uhh-volume", type=float, default=UHH_VOLUME, help=f"Uhh sound FX volume from 0.0 to 1.0+ (default: {UHH_VOLUME})")
    parser.add_argument("--whisper-model", type=str, default=DEFAULT_WHISPER_MODEL, help=f"Whisper model (default: {DEFAULT_WHISPER_MODEL}, e.g. tiny, base, small)")
    parser.add_argument("--whisper-lang", type=str, default=DEFAULT_WHISPER_LANGUAGE, help=f"Whisper language (default: {DEFAULT_WHISPER_LANGUAGE}, e.g. en, nl)")
    args = parser.parse_args()

    BEAT_VOLUME = args.beat_volume
    GROK_VOLUME = args.grok_volume
    UHH_VOLUME = args.uhh_volume
    GEMINI_MODEL = args.gemini_model
    GROQ_MODEL = args.groq_model
    GROK_MODEL = args.model

    voice_name = args.voice
    explicit_port = args.port
    baud = args.baud
    phrase_limit = args.phrase_limit
    whisper_model_name = args.whisper_model
    whisper_lang = args.whisper_lang

    print("=" * 60)
    print("🔥 GEMINI FLASH AI RAP BATTLE (GOOGLE GENAI + ARDUINO LCD)")
    print(f"   LLM: Gemini ({GEMINI_MODEL}) [Fallbacks: Groq {GROQ_MODEL} / xAI {GROK_MODEL}]")
    print(f"   STT: Whisper ({whisper_model_name}, lang: {whisper_lang}) | Audio: Klattsch Formant TTS")
    print(f"   Volumes: Beat={BEAT_VOLUME} | Voice={GROK_VOLUME} | FX={UHH_VOLUME}")
    print("=" * 60)

    # Setup OSC
    osc_client = None
    if HAS_OSC:
        try:
            osc_client = udp_client.SimpleUDPClient(OSC_IP, OSC_PORT_SEND)
            print(f"📡 OSC broadcasting to {OSC_IP}:{OSC_PORT_SEND}")
        except Exception as e:
            print(f"⚠️  OSC error: {e}")

    # Setup Microphone & Continuous Audio Recorder
    recognizer = sr.Recognizer()
    recorder = ContinuousRecorder()
    atexit.register(recorder.close)
    print("✨ Continuous microphone recorder ready.")

    # Setup OpenAI Whisper Model
    whisper_model = None
    if HAS_WHISPER:
        try:
            print(f"🤖 Loading OpenAI Whisper model ('{whisper_model_name}')...")
            whisper_model = whisper.load_model(whisper_model_name)
            print("✨ Whisper model loaded successfully.")
        except Exception as e:
            print(f"⚠️  Could not load Whisper model: {e}")

    # Setup Arduino
    print("\n🔌 Connecting to Arduino LCD...")
    arduino, port = try_connect_arduino(explicit_port, baud)
    if arduino:
        update_lcd(arduino, "Are you ready to battle!?")
        play_host_wav("ready")
        send_to_arduino(arduino, "STATUS")
    else:
        print("⚠️  Arduino not found. Running in KEYBOARD TEST mode (will auto-connect if plugged in).")
        update_lcd(None, "Are you ready to battle!?")
        play_host_wav("ready")

    history = []
    mic_active = False
    is_recording = False
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
                    elif ch in ['v', 'V']:
                        print("\n🗳️  [Keyboard: Check Supabase Votes & Refresh LEDs]")
                        trigger_round_vote_leds(arduino, osc_client)
                    elif ch in ['q', 'Q']:
                        print("\n👋 Quit requested via keyboard.")
                        restore_terminal()
                        stop_vote_polling()
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
                    elif cmd in ['v', 'votes', 'vote']:
                        print("\n🗳️  [Keyboard: Check Supabase Votes & Refresh LEDs]")
                        trigger_round_vote_leds(arduino, osc_client)
                    elif cmd in ['b', 'beat']:
                        if beat_stop_event.is_set() or beat_thread is None or not beat_thread.is_alive():
                            start_beat_loop()
                        else:
                            stop_beat_loop()
                    elif cmd in ['u', 'uhh']:
                        play_uhh_sound()
                    elif cmd in ['q', 'quit', 'exit']:
                        stop_vote_polling()
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
    print("  [V]             : Check Supabase votes & refresh LEDs (Pins 4,5,6 & 10,11,12)")
    print("  [B]             : Toggle Beat backing track ON / OFF")
    print("  [U]             : Play 'uhh.mpeg' test")
    print("  [Q] or [Ctrl+C] : Quit")
    print("=" * 60 + "\n")

    # Main interaction loop
    battle_started = False

    while True:
        try:
            # Step 1: Handle Pin 9 button or Keyboard [S]/[SPACE] (Toggle Start/Stop)
            if pin9_requested and not is_busy:
                pin9_requested = False
                if not battle_started:
                    print("\n🚀 [START BATTLE] Initializing rap battle round...")
                    stop_vote_polling()
                    if arduino and arduino.is_open:
                        send_to_arduino(arduino, "ALL_OFF")
                    is_busy = True
                    battle_started = True
                    start_beat_loop()
                    grok_start_battle(arduino, osc_client, voice_name, history)
                    is_busy = False
                else:
                    print("\n🏁 [STOP BATTLE] Ending rap battle round!")
                    if is_recording:
                        recorder.stop()
                        is_recording = False
                    battle_started = False
                    mic_active = False
                    stop_beat_loop()
                    play_host_wav("round_end")
                    end_round_msg = "Wow, that round was fire!\nNow let's see the votes."
                    update_lcd(arduino, end_round_msg)
                    if osc_client:
                        try:
                            osc_client.send_message("/battle/round_ended", end_round_msg)
                        except Exception:
                            pass

                    # Display Supabase votes on LEDs (Pins 4,5,6 and Pins 10,11,12)
                    time.sleep(1.0)
                    trigger_round_vote_leds(arduino, osc_client)
                    start_vote_polling(arduino, osc_client)

            # Step 2: Mic switched ON -> Begin continuous recording
            if mic_active and not is_recording and not is_busy:
                is_recording = True
                battle_started = True
                print("\n🎙️  [Mic Active] Recording your verse... (Flip switch OFF when finished)")
                update_lcd(arduino, "Mic Active\nSpit your verse...")
                recorder.start()

            # Step 3: Mic switched OFF -> Stop recording and send verse to Gemini Flash
            elif not mic_active and is_recording:
                is_recording = False
                is_busy = True
                print("\n🛑 [Mic Switch OFF] Finishing recording, transcribing...")
                audio_data = recorder.stop()

                min_samples = int(16000 * 2 * 0.3)
                if audio_data and len(audio_data.get_raw_data()) >= min_samples:
                    update_lcd(arduino, "Heard your bars!\nTranscribing...")
                    user_text = transcribe_audio(
                        audio_data,
                        whisper_model=whisper_model,
                        language=whisper_lang,
                        recognizer=recognizer
                    )
                    if user_text:
                        handle_rap_interaction(user_text, arduino, osc_client, voice_name, history)
                        print("\n👉 [Your Turn] Flip mic switch ON (Pin 7 or press 'm') to rap again!")
                    else:
                        update_lcd(arduino, "Could not hear you!\nFlip switch to retry")
                else:
                    print("⚠️  Audio recording was empty or too brief (<0.3s).")
                    update_lcd(arduino, "Too short!\nFlip switch to rap")

                is_busy = False

            # Step 4: User responded by typing a custom verse [T]
            if pending_typed_verse and not is_busy:
                if is_recording:
                    recorder.stop()
                    is_recording = False
                verse = pending_typed_verse
                pending_typed_verse = None
                is_busy = True
                battle_started = True
                handle_rap_interaction(verse, arduino, osc_client, voice_name, history)
                print("\n👉 [Your Turn] Flip mic switch ON (Pin 7 or press 'm') to rap again!")
                is_busy = False

            time.sleep(0.04)

        except (KeyboardInterrupt, EOFError):
            print("\n👋 Battle finished. Goodbye!")
            restore_terminal()
            if is_recording:
                recorder.stop()
            recorder.close()
            stop_vote_polling()
            stop_beat_loop()
            if arduino and arduino.is_open:
                send_to_arduino(arduino, "ALL_OFF")
                send_to_arduino(arduino, "CLEAR")
                send_to_arduino(arduino, "LINE:0:Gemini Offline")
                arduino.close()
            break


if __name__ == "__main__":
    main()
