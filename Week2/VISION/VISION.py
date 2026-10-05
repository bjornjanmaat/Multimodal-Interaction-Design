import os
import urllib.request
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from pythonosc import udp_client

# OSC setup
osc_client = udp_client.SimpleUDPClient("127.0.0.1", 9000)

# Path to the model file (relative to this script file)
script_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(script_dir, "face_landmarker.task")
if not os.path.exists(model_path):
    urllib.request.urlretrieve(
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
        model_path,
    )

# Setup with explicit CPU delegate
base_options = python.BaseOptions(
    model_asset_path=model_path,
    delegate=python.BaseOptions.Delegate.CPU,  # Force CPU execution
)
options = vision.FaceLandmarkerOptions(
    base_options=base_options,
    output_face_blendshapes=False,
    output_facial_transformation_matrixes=False,
    num_faces=1,
)
detector = vision.FaceLandmarker.create_from_options(options)

cap = cv2.VideoCapture(0)

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)  # mirror horizontally

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    results = detector.detect(mp_image)

    if results.face_landmarks:
        lm = results.face_landmarks[0]
        h, w = frame.shape[:2]

        # Iris centers
        lx = int(lm[468].x * w)
        ly = int(lm[468].y * h)
        rx = int(lm[473].x * w)
        ry = int(lm[473].y * h)

        # Average iris position
        cx = (lx + rx) // 2
        cy = (ly + ry) // 2

        # Draw left iris
        cv2.circle(frame, (lx, ly), 5, (255, 255, 255), -1)
        cv2.putText(
            frame,
            f"L: ({lx}, {ly})",
            (lx + 10, ly),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )

        # Draw right iris
        cv2.circle(frame, (rx, ry), 5, (255, 255, 255), -1)
        cv2.putText(
            frame,
            f"R: ({rx}, {ry})",
            (rx + 10, ry),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )

        # Draw center average
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.putText(
            frame,
            f"C: ({cx}, {cy})",
            (cx + 10, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
        )

        # Send OSC messages
        osc_client.send_message("/iris/left", [lx, ly])
        osc_client.send_message("/iris/right", [rx, ry])
        osc_client.send_message("/iris/center", [cx, cy])

        # Print to terminal
        print(
            f"Left: ({lx}, {ly})  Right: ({rx}, {ry})  Center: ({cx}, {cy})",
            end="\r",
        )

    cv2.imshow("Iris Tracking", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()
