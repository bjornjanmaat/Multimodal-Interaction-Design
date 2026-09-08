#!/usr/bin/env python3
"""
Arduino & FSR/Touch Simulator for Bike Navigation
Simulates Arduino serial communication (TOUCH and FSR pressure readings)
using Mac Force Touch trackpad hardware pressure, mouse/trackpad drag, scroll,
and a virtual serial port (pty).
"""

import os
import pty
import sys
import time
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

HELPER_C_SOURCE = r"""
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <CoreFoundation/CoreFoundation.h>

typedef struct { float x; float y; } MTPoint;
typedef struct { MTPoint position; MTPoint velocity; } MTVector;

typedef struct {
    int frame;
    double timestamp;
    int identifier;
    int state;
    int finger_id;
    int hand_id;
    MTVector normalized_pos;
    float size;
    float pressure;
    float angle;
    float major_axis;
    float minor_axis;
    MTVector absolute_pos;
    int unknown1;
    int unknown2;
    float density;
} MTTouch;

typedef void* MTDeviceRef;
typedef int (*MTContactCallbackFunction)(MTDeviceRef, MTTouch*, int, double, int);

MTDeviceRef MTDeviceCreateDefault(void);
void MTRegisterContactFrameCallback(MTDeviceRef, MTContactCallbackFunction);
void MTDeviceStart(MTDeviceRef, int);
void MTDeviceStop(MTDeviceRef, int);

int touchCallback(MTDeviceRef device, MTTouch *touches, int numTouches, double timestamp, int frame) {
    if (numTouches > 0 && touches != NULL) {
        float maxPressure = 0.0f;
        float maxSize = 0.0f;
        for (int i = 0; i < numTouches; i++) {
            if (touches[i].pressure > maxPressure) {
                maxPressure = touches[i].pressure;
            }
            if (touches[i].size > maxSize) {
                maxSize = touches[i].size;
            }
        }
        printf("TOUCH num=%d pressure=%.4f size=%.4f\n", numTouches, maxPressure, maxSize);
        fflush(stdout);
    } else {
        printf("TOUCH num=0 pressure=0.0000 size=0.0000\n");
        fflush(stdout);
    }
    return 0;
}

int main(int argc, char **argv) {
    MTDeviceRef dev = MTDeviceCreateDefault();
    if (!dev) {
        fprintf(stderr, "No multitouch device\n");
        return 1;
    }
    MTRegisterContactFrameCallback(dev, touchCallback);
    MTDeviceStart(dev, 0);
    printf("READY\n");
    fflush(stdout);
    CFRunLoopRun();
    return 0;
}
"""


class ArduinoSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino FSR & Touch Simulator")
        self.root.geometry("540x670")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e1e24")

        # Serial pty setup
        self.master_fd, self.slave_fd = pty.openpty()
        self.port_name = os.ttyname(self.slave_fd)
        try:
            with open("/tmp/trackpad_pressure_port.txt", "w") as f:
                f.write(self.port_name)
        except Exception:
            pass
        
        # State variables
        self.fsr_value = 0
        self.touch_triggered = False
        self.auto_release = tk.BooleanVar(value=True)
        self.is_dragging = False
        self.drag_start_y = 0
        self.drag_start_val = 0
        self.had_touches = False
        self.trackpad_process = None
        self.trackpad_active = False

        # Background sender thread
        self.running = True
        self.send_thread = threading.Thread(target=self._serial_loop, daemon=True)
        
        self._build_ui()
        self._start_mac_trackpad_helper()
        self.send_thread.start()

        # Initial ready handshake
        self._send_raw("READY\n")

    def _start_mac_trackpad_helper(self):
        """Build and launch native macOS Multitouch helper subprocess."""
        if sys.platform != "darwin":
            return

        helper_bin = "/tmp/mac_trackpad_pressure_helper"
        try:
            if not os.path.exists(helper_bin) or os.path.getsize(helper_bin) == 0:
                compile_cmd = [
                    "clang", "-x", "c", "-",
                    "-framework", "Foundation",
                    "-F/System/Library/PrivateFrameworks",
                    "-framework", "MultitouchSupport",
                    "-O2",
                    "-o", helper_bin
                ]
                proc = subprocess.run(
                    compile_cmd,
                    input=HELPER_C_SOURCE,
                    text=True,
                    capture_output=True
                )
                if proc.returncode != 0:
                    print(f"Notice: Trackpad helper compilation failed: {proc.stderr}")
                    return

            self.trackpad_process = subprocess.Popen(
                [helper_bin],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )

            listener_thread = threading.Thread(target=self._trackpad_listener_loop, daemon=True)
            listener_thread.start()
            self.trackpad_active = True
            if hasattr(self, "badge_lbl"):
                self.badge_lbl.config(text="🍏 Mac Trackpad Force: ACTIVE", fg="#56d364")

        except Exception as e:
            print(f"Notice: Could not start native trackpad listener: {e}")

    def _trackpad_listener_loop(self):
        """Read real-time pressure & touch data from native helper process."""
        try:
            for line in self.trackpad_process.stdout:
                line = line.strip()
                if line.startswith("TOUCH"):
                    # Format: TOUCH num=1 pressure=0.8500 size=3.2000
                    parts = line.split()
                    data = {}
                    for p in parts[1:]:
                        if "=" in p:
                            k, v = p.split("=", 1)
                            data[k] = float(v)

                    num = int(data.get("num", 0))
                    pressure = data.get("pressure", 0.0)
                    size = data.get("size", 0.0)

                    if num > 0:
                        # Touch down
                        if not self.had_touches:
                            self.had_touches = True
                            self.root.after_idle(self.trigger_touch)

                        # Effective force calculation (continuous 0.0 to 1200.0)
                        effective_force = max(pressure, min(1200.0, (size - 1.2) * 240.0) if size > 1.2 else 0.0)
                        fsr_target = int(min(1200, max(0, effective_force)))

                        self.root.after_idle(lambda v=fsr_target: self._set_fsr(v))
                    else:
                        # Fingers lifted
                        self.had_touches = False
                        if self.auto_release.get():
                            self.root.after_idle(self._animate_release)

        except Exception:
            pass

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("default")

        # Header Frame
        header = tk.Frame(self.root, bg="#2b2b36", padx=16, pady=12)
        header.pack(fill="x")

        title = tk.Label(
            header,
            text="🚴 Bike Navigation Arduino Simulator",
            font=("Helvetica", 16, "bold"),
            fg="#ffffff",
            bg="#2b2b36",
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            header,
            text="Simulating FSR Pressure (A1) & Capacitive Touch (A0)",
            font=("Helvetica", 11),
            fg="#a0a0b0",
            bg="#2b2b36",
        )
        subtitle.pack(anchor="w", pady=(2, 0))

        # Port Connection Info Frame
        port_frame = tk.Frame(self.root, bg="#252530", padx=14, pady=10, relief="groove", bd=1)
        port_frame.pack(fill="x", padx=16, pady=12)

        port_lbl = tk.Label(
            port_frame,
            text="Virtual Serial Port:",
            font=("Helvetica", 11, "bold"),
            fg="#79c0ff",
            bg="#252530",
        )
        port_lbl.pack(anchor="w")

        port_entry_frame = tk.Frame(port_frame, bg="#252530")
        port_entry_frame.pack(fill="x", pady=4)

        self.port_entry = tk.Entry(
            port_entry_frame,
            font=("Menlo", 12, "bold"),
            fg="#58a6ff",
            bg="#161b22",
            insertbackground="white",
            relief="flat",
        )
        self.port_entry.insert(0, self.port_name)
        self.port_entry.configure(state="readonly")
        self.port_entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))

        copy_btn = tk.Button(
            port_entry_frame,
            text="Copy Port",
            command=self._copy_port,
            bg="#238636",
            fg="white",
            activebackground="#2ea043",
            font=("Helvetica", 10, "bold"),
            padx=10,
            relief="flat",
            cursor="pointinghand",
        )
        copy_btn.pack(side="right")

        hint_lbl = tk.Label(
            port_frame,
            text=f'In FSR_TOUCH.pde, set:\narduino = new Serial(this, "{self.port_name}", 9600);',
            font=("Menlo", 9),
            fg="#8b949e",
            bg="#252530",
            justify="left",
        )
        hint_lbl.pack(anchor="w", pady=(4, 0))

        # Trackpad Interactive Touch & Pressure Pad
        pad_container = tk.Frame(self.root, bg="#1e1e24", padx=16)
        pad_container.pack(fill="both", expand=True)

        pad_header_frame = tk.Frame(pad_container, bg="#1e1e24")
        pad_header_frame.pack(fill="x", pady=(0, 6))

        pad_lbl = tk.Label(
            pad_header_frame,
            text="Trackpad Pressure Pad:",
            font=("Helvetica", 11, "bold"),
            fg="#e6edf3",
            bg="#1e1e24",
        )
        pad_lbl.pack(side="left")

        self.badge_lbl = tk.Label(
            pad_header_frame,
            text="🍏 Mac Trackpad Force: ACTIVE",
            font=("Helvetica", 9, "bold"),
            fg="#56d364",
            bg="#1e1e24",
        )
        self.badge_lbl.pack(side="right")

        self.canvas_pad = tk.Canvas(
            pad_container,
            bg="#161b22",
            height=160,
            highlightthickness=2,
            highlightbackground="#30363d",
            cursor="hand2",
        )
        self.canvas_pad.pack(fill="x", pady=(0, 10))

        # Pad instructions text inside canvas
        pad_instructions = (
            "🖐️ Press down on Trackpad with Finger (Force Touch Pressure)\n"
            "↕️ Or Click & Drag Up / Scroll / Use Slider\n"
            "Release finger to Spring Return"
        )
        self.pad_text = self.canvas_pad.create_text(
            250, 80,
            text=pad_instructions,
            font=("Helvetica", 12),
            fill="#8b949e",
            justify="center",
        )

        # Bindings for canvas (fallback / complementary gestures)
        self.canvas_pad.bind("<Button-1>", self._on_pad_click)
        self.canvas_pad.bind("<B1-Motion>", self._on_pad_drag)
        self.canvas_pad.bind("<ButtonRelease-1>", self._on_pad_release)
        self.canvas_pad.bind("<MouseWheel>", self._on_pad_scroll)

        # Gauge & Value Display
        gauge_frame = tk.Frame(pad_container, bg="#1e1e24")
        gauge_frame.pack(fill="x", pady=4)

        self.val_label = tk.Label(
            gauge_frame,
            text="FSR Value: 0 / 1200",
            font=("Helvetica", 13, "bold"),
            fg="#58a6ff",
            bg="#1e1e24",
        )
        self.val_label.pack(side="left")

        self.touch_indicator = tk.Label(
            gauge_frame,
            text="● TOUCH IDLE",
            font=("Helvetica", 11, "bold"),
            fg="#6e7681",
            bg="#1e1e24",
        )
        self.touch_indicator.pack(side="right")

        # Pressure Progress Bar / Slider
        self.scale_var = tk.DoubleVar(value=0)
        self.slider = tk.Scale(
            pad_container,
            from_=0,
            to=1200,
            orient="horizontal",
            variable=self.scale_var,
            command=self._on_slider_change,
            bg="#21262d",
            fg="#e6edf3",
            troughcolor="#0d1117",
            activebackground="#58a6ff",
            highlightthickness=0,
            font=("Menlo", 9),
        )
        self.slider.pack(fill="x", pady=(2, 10))

        # Control buttons & options
        controls_frame = tk.Frame(pad_container, bg="#1e1e24")
        controls_frame.pack(fill="x", pady=4)

        self.touch_btn = tk.Button(
            controls_frame,
            text="⚡ Trigger Capacitive Touch (Spacebar)",
            command=self.trigger_touch,
            bg="#8957e5",
            fg="white",
            activebackground="#a371f7",
            font=("Helvetica", 11, "bold"),
            pady=8,
            relief="flat",
            cursor="pointinghand",
        )
        self.touch_btn.pack(fill="x", pady=(0, 8))

        opt_frame = tk.Frame(controls_frame, bg="#1e1e24")
        opt_frame.pack(fill="x")

        auto_rel_cb = tk.Checkbutton(
            opt_frame,
            text="Auto-release pressure when letting go of trackpad",
            variable=self.auto_release,
            bg="#1e1e24",
            fg="#c9d1d9",
            selectcolor="#161b22",
            activebackground="#1e1e24",
            activeforeground="#58a6ff",
            font=("Helvetica", 10),
        )
        auto_rel_cb.pack(side="left")

        zero_btn = tk.Button(
            opt_frame,
            text="Reset 0",
            command=self._reset_pressure,
            bg="#30363d",
            fg="#c9d1d9",
            font=("Helvetica", 9),
            padx=8,
            relief="flat",
            cursor="pointinghand",
        )
        zero_btn.pack(side="right")

        # Global Spacebar binding for touch
        self.root.bind("<space>", lambda e: self.trigger_touch())

    def _copy_port(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.port_name)
        self.root.update()

    def _on_pad_click(self, event):
        self.is_dragging = True
        self.drag_start_y = event.y
        self.drag_start_val = self.fsr_value
        self.trigger_touch()

    def _on_pad_drag(self, event):
        # Fallback drag gesture
        if not self.had_touches:
            dy = self.drag_start_y - event.y  # Dragging up increases pressure
            new_val = int(self.drag_start_val + dy * 7.5)
            new_val = max(0, min(1023, new_val))
            self._set_fsr(new_val)

    def _on_pad_release(self, event):
        self.is_dragging = False
        if self.auto_release.get() and not self.had_touches:
            self._animate_release()

    def _on_pad_scroll(self, event):
        # macOS trackpad two-finger scroll
        delta = event.delta
        new_val = int(self.fsr_value + delta * 15)
        new_val = max(0, min(1023, new_val))
        self._set_fsr(new_val)

    def _animate_release(self):
        if self.is_dragging or not self.auto_release.get() or self.had_touches:
            return
        if self.fsr_value > 0:
            new_val = int(self.fsr_value * 0.75)
            if new_val < 5:
                new_val = 0
            self._set_fsr(new_val)
            self.root.after(20, self._animate_release)

    def _on_slider_change(self, val):
        self._set_fsr(int(float(val)))

    def _set_fsr(self, val):
        self.fsr_value = val
        self.scale_var.set(val)
        self.val_label.config(text=f"FSR Value: {val} / 1200")

        # Dynamic visual coloring in canvas
        intensity = min(255, int((val / 1200.0) * 255))
        bg_color = f"#{intensity:02x}{int(intensity * 0.3):02x}{int(intensity * 0.4):02x}" if intensity > 30 else "#161b22"
        self.canvas_pad.configure(bg=bg_color)

    def _reset_pressure(self):
        self._set_fsr(0)

    def trigger_touch(self):
        self.touch_triggered = True
        self.touch_indicator.config(text="● TOUCH TRIGGERED!", fg="#f78166")
        self.root.after(300, lambda: self.touch_indicator.config(text="● TOUCH IDLE", fg="#6e7681"))

    def _send_raw(self, msg: str):
        try:
            os.write(self.master_fd, msg.encode("utf-8"))
        except OSError:
            pass

    def _serial_loop(self):
        while self.running:
            # Handle Touch trigger
            if self.touch_triggered:
                self._send_raw("TOUCH\n")
                self.touch_triggered = False

            # Send FSR pressure reading
            self._send_raw(f"{self.fsr_value}\n")

            time.sleep(0.02)  # 20ms period (matches Arduino delay(20))

    def on_close(self):
        self.running = False
        if self.trackpad_process:
            try:
                self.trackpad_process.terminate()
            except Exception:
                pass
        try:
            os.close(self.master_fd)
            os.close(self.slave_fd)
        except Exception:
            pass
        try:
            if os.path.exists("/tmp/trackpad_pressure_port.txt"):
                os.remove("/tmp/trackpad_pressure_port.txt")
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = ArduinoSimulator(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    print("=" * 60)
    print("🚀 Arduino Simulator Running")
    print(f"📡 Virtual Serial Port: {app.port_name}")
    print(f"🍏 Mac Trackpad Force Support: {'Active' if app.trackpad_active else 'Fallback Mode'}")
    print("📋 Copy this port into FSR_TOUCH.pde:")
    print(f'   arduino = new Serial(this, "{app.port_name}", 9600);')
    print("=" * 60)
    root.mainloop()


if __name__ == "__main__":
    main()
