# STEP 1: Import the necessary modules.
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import urllib.request
import os
import time
from pythonosc import udp_client

# OSC setup
osc_client = udp_client.SimpleUDPClient("127.0.0.1", 9000)

# Download the model file if you don't have it
model_path = "gesture_recognizer.task"
model_url = (
    "https://storage.googleapis.com/mediapipe-models/"
    "gesture_recognizer/gesture_recognizer/float16/1/"
    "gesture_recognizer.task"
)

if not os.path.exists(model_path):
    print("Downloading gesture model...")
    urllib.request.urlretrieve(model_url, model_path)

# Setup
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.GestureRecognizerOptions(
    base_options=base_options,
    running_mode=vision.RunningMode.VIDEO,
    num_hands=2
)
recognizer = vision.GestureRecognizer.create_from_options(options)

# Open webcam
cap = cv2.VideoCapture(0)

start_time = time.time()

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)  # mirror horizontally

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

    # VIDEO mode needs timestamp in milliseconds
    timestamp_ms = int((time.time() - start_time) * 1000)
    result = recognizer.recognize_for_video(mp_image, timestamp_ms)

    # Process each detected hand
    for hand_index, gestures in enumerate(result.gestures):
        if len(gestures) == 0:
            continue

        gesture = gestures[0]
        gesture_name = gesture.category_name
        confidence = gesture.score

        # Get wrist position for label placement
        wrist = result.hand_landmarks[hand_index][0]
        h, w = frame.shape[:2]
        x = int(wrist.x * w)
        y = int(wrist.y * h)

        label = f"Hand {hand_index + 1}: {gesture_name} ({confidence:.2f})"

        # Draw on frame
        cv2.circle(frame, (x, y), 8, (0, 255, 0), -1)
        cv2.putText(frame, label, (x + 10, y - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # Send OSC
        osc_client.send_message("/gesture/hand",
                                [hand_index + 1, gesture_name, float(confidence)])

        print(label, end=" | ")

    print(" " * 10, end="\r")

    cv2.imshow("Gesture Recognition", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
