import socket
import sys
import termios
import time
import tty

# Arduino Wi-Fi configuration
ARDUINO_IP = "10.114.198.176"
PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def set_vibration(level: int):
  """Sets motor speed from 0 (off) to 255 (maximum)."""
  level = max(0, min(255, level))
  sock.sendto(str(level).encode(), (ARDUINO_IP, PORT))


def buzz(duration=0.25, intensity=255):
  """Triggers a short pulse."""
  set_vibration(intensity)
  time.sleep(duration)
  set_vibration(0)


def get_single_keypress():
  """Reads a single keypress without waiting for the Enter key."""
  fd = sys.stdin.fileno()
  old_settings = termios.tcgetattr(fd)
  try:
    tty.setraw(fd)
    char = sys.stdin.read(1)
  finally:
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
  return char


if __name__ == "__main__":
  print("=" * 45)
  print("  Wireless Vibration Motor Controller")
  print("=" * 45)
  print("Controls:")
  print("  [SPACE] -> Short Buzz (0.25s)")
  print("  [1]     -> Low Buzz   (Intensity 100)")
  print("  [2]     -> Medium Buzz(Intensity 180)")
  print("  [3]     -> Strong Buzz(Intensity 255)")
  print("  [q]     -> Quit")
  print("-" * 45)

  try:
    while True:
      key = get_single_keypress()

      if key == " ":
        print("\rTrigger: Space (Short Buzz)    ", end="", flush=True)
        buzz(duration=0.25, intensity=255)
      elif key == "1":
        print("\rTrigger: 1 (Gentle Buzz)       ", end="", flush=True)
        buzz(duration=0.3, intensity=100)
      elif key == "2":
        print("\rTrigger: 2 (Medium Buzz)       ", end="", flush=True)
        buzz(duration=0.3, intensity=180)
      elif key == "3":
        print("\rTrigger: 3 (Full Buzz)         ", end="", flush=True)
        buzz(duration=0.3, intensity=255)
      elif key in ("q", "Q", "\x03"):  # 'q' or Ctrl+C
        print("\nExiting...")
        break

  finally:
    # Safety: always turn off motor on exit
    set_vibration(0)
    sock.close()
