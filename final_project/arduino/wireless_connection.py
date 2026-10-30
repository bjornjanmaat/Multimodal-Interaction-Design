import socket
import sys
import termios
import time
import tty

# Arduino Wi-Fi configuration
ARDUINO_IP = "10.114.198.176"
PORT = 5005

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def set_vibration(level: int, motor: int | None = None):
    """
    Sets motor vibration intensity from 0 (off) to 255 (maximum).
    
    Args:
        level: Vibration intensity (0-255).
        motor: Target motor number (1, 2, 3, 4) or None to set all motors.
    """
    level = max(0, min(255, int(level)))
    if motor is None:
        # Backward-compatible command: sets all motors
        payload = str(level)
    elif motor in (1, 2, 3, 4):
        payload = f"M{motor}:{level}"
    else:
        raise ValueError(f"Motor must be 1, 2, 3, 4, or None. Got {motor}")

    sock.sendto(payload.encode(), (ARDUINO_IP, PORT))


def set_motors(m1: int = 0, m2: int = 0, m3: int = 0, m4: int = 0):
    """
    Sets independent vibration intensities (0-255) for all 4 motors simultaneously.
    """
    m1 = max(0, min(255, int(m1)))
    m2 = max(0, min(255, int(m2)))
    m3 = max(0, min(255, int(m3)))
    m4 = max(0, min(255, int(m4)))
    payload = f"{m1},{m2},{m3},{m4}"
    sock.sendto(payload.encode(), (ARDUINO_IP, PORT))


def stop_all():
    """Immediately turns off all 4 motors."""
    set_vibration(0)


def buzz(duration: float = 0.25, intensity: int = 255, motor: int | None = None):
    """Triggers a short pulse on all motors (or a specific motor if specified)."""
    set_vibration(intensity, motor=motor)
    time.sleep(duration)
    set_vibration(0, motor=motor)


def buzz_sequence(duration: float = 0.15, pause: float = 0.05, intensity: int = 255):
    """Fires motors sequentially in a wave: M1 -> M2 -> M3 -> M4."""
    for m in (1, 2, 3, 4):
        buzz(duration=duration, intensity=intensity, motor=m)
        if pause > 0:
            time.sleep(pause)


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
    print("=" * 55)
    print("  Wireless 4-Motor Vibration Controller (M1 - M4)")
    print(f"  Target: {ARDUINO_IP}:{PORT}")
    print("=" * 55)
    print("Controls:")
    print("  [SPACE] -> Pulse ALL motors (0.25s @ Full)")
    print("  [1]     -> Pulse Motor M1")
    print("  [2]     -> Pulse Motor M2")
    print("  [3]     -> Pulse Motor M3")
    print("  [4]     -> Pulse Motor M4")
    print("  [s]     -> Sequential Wave (M1 -> M2 -> M3 -> M4)")
    print("  [a]     -> Gentle Buzz ALL (Intensity 100)")
    print("  [m]     -> Medium Buzz ALL (Intensity 180)")
    print("  [h]     -> High Buzz ALL   (Intensity 255)")
    print("  [0]     -> Stop all motors")
    print("  [q]     -> Quit")
    print("-" * 55)

    try:
        while True:
            key = get_single_keypress()

            if key == " ":
                print("\rTrigger: [SPACE] Pulse ALL Motors              ", end="", flush=True)
                buzz(duration=0.25, intensity=255)
            elif key == "1":
                print("\rTrigger: [1] Pulse Motor M1                    ", end="", flush=True)
                buzz(duration=0.25, intensity=255, motor=1)
            elif key == "2":
                print("\rTrigger: [2] Pulse Motor M2                    ", end="", flush=True)
                buzz(duration=0.25, intensity=255, motor=2)
            elif key == "3":
                print("\rTrigger: [3] Pulse Motor M3                    ", end="", flush=True)
                buzz(duration=0.25, intensity=255, motor=3)
            elif key == "4":
                print("\rTrigger: [4] Pulse Motor M4                    ", end="", flush=True)
                buzz(duration=0.25, intensity=255, motor=4)
            elif key in ("s", "S"):
                print("\rTrigger: [s] Wave Sequence (M1->M2->M3->M4)     ", end="", flush=True)
                buzz_sequence(duration=0.15, pause=0.04, intensity=255)
            elif key in ("a", "A"):
                print("\rTrigger: [a] Gentle Buzz ALL (100)             ", end="", flush=True)
                buzz(duration=0.30, intensity=100)
            elif key in ("m", "M"):
                print("\rTrigger: [m] Medium Buzz ALL (180)             ", end="", flush=True)
                buzz(duration=0.30, intensity=180)
            elif key in ("h", "H"):
                print("\rTrigger: [h] High Buzz ALL (255)               ", end="", flush=True)
                buzz(duration=0.30, intensity=255)
            elif key == "0":
                print("\rTrigger: [0] Stop ALL Motors                   ", end="", flush=True)
                stop_all()
            elif key in ("q", "Q", "\x03"):  # 'q' or Ctrl+C
                print("\nExiting...")
                break

    finally:
        # Safety: always turn off all motors on exit
        stop_all()
        sock.close()
