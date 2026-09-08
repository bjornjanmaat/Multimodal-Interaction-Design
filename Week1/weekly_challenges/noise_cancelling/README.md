# Active Noise Cancelling (ANC) Simulation

A multimodal interaction sketch for Processing that simulates real-world Active Noise Cancelling (ANC) driven by physical force touch pressure from the Mac Force Touch trackpad or an Arduino FSR sensor.

---

## 🎧 How It Works

### 1. Trackpad Force Touch Control (0 - 1200g)
- **0 - 80g (Tier 1: Transparency Mode)**:
  - **0% ANC (0 dB attenuation)**
  - Ambient noise passes through 100%. Incoming sound particles penetrate directly to the listener.
  - Residual sound wave is high amplitude.
- **80 - 400g (Tier 2: Adaptive / Mild ANC)**:
  - **15% - 50% ANC (-10 to -20 dB attenuation)**
  - Inverted anti-phase wave begins opposing ambient noise.
  - Low-frequency rumble is muffled and attenuated.
- **400 - 800g (Tier 3: Deep Isolation)**:
  - **50% - 85% ANC (-20 to -35 dB attenuation)**
  - Anti-noise mirrors ambient sound with $180^\circ$ phase inversion.
  - Acoustic shield barrier glows vibrant cyan and reflects particles away.
- **800 - 1200g (Tier 4: Maximum Void Silence)**:
  - **85% - 100% ANC (-35 to -45 dB attenuation)**
  - Complete destructive interference: $y_{noise} + y_{anti} \approx 0$.
  - Residual wave flatlines. Real-time procedural audio drops to near-silence.

---

## 🔒 Sticky ANC Lock & Unlock
- **Hold for 2.0s**: Maintain any pressure tier for 2 seconds to engage **Sticky ANC Lock**. The green circular progress ring will fill up, and the cancellation level stays locked even when you release your finger.
- **Triple-Tap Trackpad** (or press key `U` or `1`): Instantly releases the lock and returns to default Transparency Mode.

---

## 🌍 Soundscape Environments
Tap the trackpad (or press `T` / `Spacebar`) to cycle between 3 realistic acoustic environments:
1. **Jet Cabin Cruising (38,000 ft)**: Low-frequency turbofan engine rumble & airflow.
2. **Metro Subway Transit (Centraal)**: Steel rail screech & electric traction motor hum.
3. **Rainy City Street (Amsterdam)**: Rainfall hiss & distant urban street rumble.

---

## 🚀 How to Run

1. **Start the Trackpad Pressure Bridge** (in project root):
   ```bash
   ./trackpad_pressure
   ```
2. **Open & Run in Processing**:
   - Open `Week1/weekly_challenges/noise_cancelling/noise_cancelling.pde` in Processing 4.
   - Click **Run** (Command + R).
   - The sketch automatically detects the virtual serial port from `/tmp/trackpad_pressure_port.txt`!

---

## ⌨️ Keyboard & Mouse Controls (Fallbacks)
- **UP / DOWN Arrows**: Increment / decrement simulated trackpad force.
- **Keys `1`, `2`, `3`, `4`**: Directly jump to and lock Tiers 1 through 4.
- **Key `U` or `1`**: Unlock sticky ANC and return to Transparency Mode.
- **Key `T` / `Spacebar` / Mouse Click**: Tap trackpad / cycle soundscape environment.
- **Key `M`**: Toggle procedural audio ON / OFF.
