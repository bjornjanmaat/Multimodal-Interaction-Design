"""
THUMB_LIFT.py  -  Velex prototype, test 1
Thumbs up  -> drone climbs
Thumbs down -> drone descends
Anything else (or no hand) -> hover (vertical speed 0)

Laptop side only. Sends small JSON packets over UDP (Wi-Fi) to the Android
app, which should turn them into DJI virtual-stick vertical velocity.

Run (Windows):   py -3.10 THUMB_LIFT.py
Install once:    py -3.10 -m pip install mediapipe opencv-python
Keys:            SPACE = emergency stop toggle (locks hover)   Q = quit

Start with DRY_RUN = True: nothing is sent, you just see what WOULD be sent.
"""

import json, os, socket, time, urllib.request
import cv2
import mediapipe as mp

# ---------------- settings ----------------
DRY_RUN       = True             # True = don't send anything, just display
PHONE_IP      = "192.168.1.50"   # IP of the Android phone running your app
PHONE_PORT    = 9100             # port your app listens on (UDP)
CAMERA_INDEX  = 0

CLIMB_SPEED   = 0.5    # m/s, keep small indoors (positive = up)
MIN_SCORE     = 0.70   # how confident MediaPipe must be
HOLD_SECONDS  = 0.30   # gesture must be held this long before it counts
SEND_HZ       = 10     # packets per second (send continuously, even "0")

MODEL_PATH = "gesture_recognizer.task"
MODEL_URL  = ("https://storage.googleapis.com/mediapipe-models/"
              "gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task")

# ---------------- model ----------------
if not os.path.exists(MODEL_PATH):
    print("Downloading gesture model ...")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)

BaseOptions = mp.tasks.BaseOptions
GR          = mp.tasks.vision.GestureRecognizer
GROptions   = mp.tasks.vision.GestureRecognizerOptions
RunMode     = mp.tasks.vision.RunningMode

recognizer = GR.create_from_options(GROptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=RunMode.VIDEO,
    num_hands=1,
))

# ---------------- networking ----------------
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq = 0

def send(vz, label):
    """vz in m/s. Always send - the app should hover if packets stop."""
    global seq
    seq += 1
    msg = {"seq": seq, "t": round(time.time(), 3), "vz": vz, "gesture": label}
    if not DRY_RUN:
        sock.sendto(json.dumps(msg).encode(), (PHONE_IP, PHONE_PORT))
    return msg

# ---------------- main loop ----------------
cap = cv2.VideoCapture(CAMERA_INDEX)
candidate, candidate_since = "None", time.time()
active = "None"
estop = False
last_send = 0.0
t0 = time.perf_counter()

while cap.isOpened():
    ok, frame = cap.read()
    if not ok:
        break
    frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    ts = int((time.perf_counter() - t0) * 1000)
    result = recognizer.recognize_for_video(image, ts)

    # what does MediaPipe see right now?
    label, score = "None", 0.0
    if result.gestures:
        top = result.gestures[0][0]
        label, score = top.category_name, top.score
    if score < MIN_SCORE or label not in ("Thumb_Up", "Thumb_Down"):
        label = "None"

    # debounce: only switch after the gesture is held HOLD_SECONDS
    now = time.time()
    if label != candidate:
        candidate, candidate_since = label, now
    if now - candidate_since >= HOLD_SECONDS:
        active = candidate
    if label == "None":          # releasing is immediate - safety first
        active = "None"

    vz = 0.0
    if not estop:
        if active == "Thumb_Up":
            vz = CLIMB_SPEED
        elif active == "Thumb_Down":
            vz = -CLIMB_SPEED

    if now - last_send >= 1.0 / SEND_HZ:
        send(vz, active)
        last_send = now

    # ---- display ----
    colour = (0, 200, 0) if vz > 0 else (0, 0, 230) if vz < 0 else (200, 200, 200)
    status = "UP" if vz > 0 else "DOWN" if vz < 0 else "HOVER"
    if estop:
        status, colour = "E-STOP (SPACE to release)", (0, 0, 255)
    cv2.putText(frame, status, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, colour, 3)
    cv2.putText(frame, f"seen: {label} {score:.2f}", (20, 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, f"vz = {vz:+.2f} m/s   {'DRY RUN' if DRY_RUN else f'-> {PHONE_IP}:{PHONE_PORT}'}",
                (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
    cv2.imshow("THUMB_LIFT", frame)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == ord(" "):
        estop = not estop

# leave the drone hovering
for _ in range(5):
    send(0.0, "QUIT")
    time.sleep(0.05)
cap.release()
cv2.destroyAllWindows()
