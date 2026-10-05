import numpy as np
import speech_recognition as sr
import whisper
from pythonosc import udp_client

# -----------------------------
# SETTINGS
# -----------------------------
OSC_IP = "127.0.0.1"
OSC_PORT = 9000

MODEL_NAME = "tiny"       # Options: tiny, base, small, medium, large
LANGUAGE = "en"

# -----------------------------
# OSC SETUP
# -----------------------------
osc_client = udp_client.SimpleUDPClient(OSC_IP, OSC_PORT)

# -----------------------------
# WHISPER SETUP
# -----------------------------
print("Loading Whisper model...")
model = whisper.load_model(MODEL_NAME)
print("Whisper model loaded.")

# -----------------------------
# MICROPHONE SETUP
# -----------------------------
recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True

microphone = sr.Microphone()

print("Calibrating microphone noise level...")
with microphone as source:
    recognizer.adjust_for_ambient_noise(source, duration=1)

print("Ready.")
print('Say "activate" to show the overlay.')
print('Say "deactivate" to remove the overlay.')

# -----------------------------
# MAIN LOOP
# -----------------------------
while True:
    try:
        with microphone as source:
            print("\nListening...")

            # Wait up to 5 seconds for speech.
            # Record a maximum phrase length of 3 seconds.
            audio = recognizer.listen(
                source,
                timeout=5,
                phrase_time_limit=3
            )

        # Convert SpeechRecognition's recorded audio to:
        # 16 kHz, 16-bit PCM, mono audio.
        raw_audio = audio.get_raw_data(
            convert_rate=16000,
            convert_width=2
        )

        # Whisper requires a NumPy float32 waveform,
        # rather than WAV bytes.
        audio_array = np.frombuffer(
            raw_audio,
            dtype=np.int16
        ).astype(np.float32)

        # Convert integer audio values to the range -1.0 to 1.0.
        audio_array /= 32768.0

        print("Transcribing...")

        # fp16=False is required/recommended on CPU.
        result = model.transcribe(
            audio_array,
            language=LANGUAGE,
            fp16=False,
            initial_prompt="The possible commands are system on and system off."
        )

        transcript = result["text"].strip().lower()

        if not transcript:
            continue

        print("Heard:", transcript)

        # Send the raw transcription for optional on-screen debugging.
        osc_client.send_message("/speech/raw", transcript)

        # IMPORTANT:
        # Check "system off" before "system on":
        # to avoid partial matches.
        if "system off" in transcript:
            osc_client.send_message("/speech", "deactivate")
            print("→ Sent: deactivate")

        elif "system on" in transcript:
            osc_client.send_message("/speech", "activate")
            print("→ Sent: activate")

        else:
            print("No recognised command.")

    except sr.WaitTimeoutError:
        print("No speech detected.")

    except KeyboardInterrupt:
        print("\nStopped.")
        break

    except Exception as error:
        print("Error:", error)
