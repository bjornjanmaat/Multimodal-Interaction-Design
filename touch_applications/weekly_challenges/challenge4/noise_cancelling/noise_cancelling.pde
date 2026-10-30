// =============================================================================
// NOISE CANCELLING (ANC) MULTIMODAL SIMULATION
// Multimodal Interaction Design - Week 1 Challenge
// =============================================================================
// Simulates an Active Noise Cancelling (ANC) system using physical force touch
// pressure from the Mac Force Touch Trackpad (via ./trackpad_pressure) or Arduino FSR.
//
// HOW IT WORKS:
// - Physical Pressure (0 - 1200g) controls the intensity of Noise Cancellation.
// - As pressure increases:
//     1. Glowing acoustic shield expands, strengthens, and deflects incoming sound particles.
//     2. Real-time procedural audio attenuates ambient rumble & noise down to silence.
//     3. Noise reduction increases smoothly from 0 dB to -45 dB SPL.
// - Spacebar (or 'T'): Cycles between 3 realistic soundscapes:
//     * Airplane Cabin (Twin-turbofan low rumble + air hiss)
//     * Metro / Subway Train (Steel rails + motor drone)
//     * Rainy City Street (Rainfall hiss + distant traffic)
// - Sticky ANC Lock: Hold any pressure level steadily for 2.0s to lock that level.
// - Triple-Tap Trackpad (or key 'U' / '1'): Releases sticky lock back to Transparency.
// =============================================================================

import processing.serial.*;
import java.io.File;
import javax.sound.sampled.*;
import java.util.ArrayList;

// -------------------------------------------------------------
// Serial Connection & Hardware State
// -------------------------------------------------------------
Serial arduino;
String activePort = "None";
boolean isSerialConnected = false;
int lastSerialReceiveTime = 0;
int lastReconnectAttempt = 0;

int fsrRaw = 0;
float smoothedFsr = 0.0f;
final int FSR_MAX = 1200;

// -------------------------------------------------------------
// Noise Cancellation (ANC) State
// -------------------------------------------------------------
// Current normalized ANC factor: 0.0 (Off / Transparency) to 1.0 (Maximum Isolation)
float currentAnc = 0.0f;
float targetAnc = 0.0f;
float smoothing = 0.09f;

// 4 Discrete ANC Performance Tiers:
// Level 1: Transparency Mode (0 - 80g) -> 0% ANC (0 dB reduction)
// Level 2: Adaptive / Mild ANC (80 - 400g) -> 15% - 50% ANC (-10 dB to -20 dB)
// Level 3: Deep Isolation (400 - 800g) -> 50% - 85% ANC (-20 dB to -35 dB)
// Level 4: Zero-Noise Void (800 - 1200g) -> 85% - 100% ANC (-35 dB to -45 dB)
int currentTier = 1;

// Decibel SPL (Sound Pressure Level)
float currentDb = 82.0f; // Ambient noise starting at ~82 dB SPL
float targetDb = 82.0f;

// -------------------------------------------------------------
// Sticky ANC Lock / Hold State Machine
// -------------------------------------------------------------
boolean isAncLocked = false;
int lockedTier = 1;
float lockedAnc = 0.0f;

int holdTier = 1;
int holdStartTime = 0;
float holdProgress = 0.0f; // 0.0 to 1.0 (towards 2.0s hold)

int lockNotificationTimer = 0;
String lockNotificationText = "";
int lockNotificationColor;

// Triple-Tap Unlock State Machine
int tapCount = 0;
int lastTapTime = 0;
final int TAP_MAX_INTERVAL_MS = 800;

// Pressure impulse detection for quick physical taps
boolean fsrWasPressed = false;
int fsrPressStartTime = 0;

// -------------------------------------------------------------
// Soundscape Environments
// -------------------------------------------------------------
class Soundscape {
  String name;
  String subtitle;
  String description;
  float baseDb;
  int accentColor;

  Soundscape(String n, String sub, String desc, float db, int col) {
    name = n;
    subtitle = sub;
    description = desc;
    baseDb = db;
    accentColor = col;
  }
}

Soundscape[] soundscapes;
int currentSoundscapeIdx = 0;
int lastSoundscapeSwitchTime = 0;

// -------------------------------------------------------------
// Acoustic Particle Shield Simulation
// -------------------------------------------------------------
class AcousticParticle {
  float x, y;
  float vx, vy;
  float size;
  boolean deflected = false;

  AcousticParticle() {
    respawn();
    float angle = random(TWO_PI);
    float dist = random(160.0f, 600.0f);
    x = width * 0.5f + cos(angle) * dist;
    y = height * 0.5f + sin(angle) * dist;
  }

  void respawn() {
    // Spawn from outer perimeter inwards towards central listener
    float angle = random(TWO_PI);
    float dist = random(320.0f, 650.0f);
    float cx = width * 0.5f;
    float cy = height * 0.5f;

    x = cx + cos(angle) * dist;
    y = cy + sin(angle) * dist;

    // Directed inwards towards center with gentle turbulence
    float speed = random(1.2f, 3.2f);
    vx = -cos(angle) * speed + random(-0.3f, 0.3f);
    vy = -sin(angle) * speed + random(-0.3f, 0.3f);

    size = random(2.5f, 5.5f);
    deflected = false;
  }

  void update(float anc, float cx, float cy, float shieldRadius) {
    float dx = x - cx;
    float dy = y - cy;
    float d = sqrt(dx * dx + dy * dy);

    // If ANC is active and particle hits the shield boundary, deflect it!
    if (anc > 0.08f && d <= shieldRadius + 15.0f) {
      deflected = true;
      // Normal vector outwards
      float nx = dx / max(1.0f, d);
      float ny = dy / max(1.0f, d);

      // Bounce velocity away from shield
      float bounceSpeed = 1.8f + anc * 3.0f;
      vx = nx * bounceSpeed + random(-0.6f, 0.6f);
      vy = ny * bounceSpeed + random(-0.6f, 0.6f);
    }

    x += vx;
    y += vy;

    // Reset if too far or too close to listener center
    if (d < 30.0f || d > 750.0f || x < -50.0f || x > width + 50.0f || y < -50.0f || y > height + 50.0f) {
      respawn();
    }
  }

  void draw(float anc, int envColor) {
    noStroke();
    if (deflected) {
      // Glow cyan/white when deflected by ANC shield
      fill(0, 230, 255, 190.0f * (1.0f - anc * 0.25f));
      ellipse(x, y, size * 1.3f, size * 1.3f);
    } else {
      // Ambient noise color fading as ANC increases
      float alpha = 200.0f * (1.0f - anc * 0.85f);
      fill(red(envColor), green(envColor), blue(envColor), alpha);
      ellipse(x, y, size, size);
    }
  }
}

ArrayList<AcousticParticle> particles;
final int NUM_PARTICLES = 240;

// -------------------------------------------------------------
// Real-time Procedural Audio Engine (javax.sound.sampled)
// -------------------------------------------------------------
boolean audioEnabled = true;
SourceDataLine audioLine = null;
Thread audioThread = null;
volatile boolean audioRunning = true;
volatile float audioGain = 1.0f;
volatile float audioAnc = 0.0f;
volatile int audioSoundscape = 0;

// -------------------------------------------------------------
// Animation Variables
// -------------------------------------------------------------
float wavePhase = 0.0f;

// =============================================================
// SETUP
// =============================================================
void setup() {
  size(1280, 720);
  frameRate(60);
  smooth(4);

  lockNotificationColor = color(0, 230, 160);

  initSoundscapes();
  initParticles();
  initAudioEngine();
  connectSerial();
}

// -------------------------------------------------------------
// Initialize Environments
// -------------------------------------------------------------
void initSoundscapes() {
  soundscapes = new Soundscape[] {
    new Soundscape(
      "Jet Cabin Cruising",
      "Boeing 787 • 38,000 FT",
      "Deep low-frequency twin-turbofan engine drone with continuous airframe vibration.",
      84.0f, color(255, 105, 65)
    ),
    new Soundscape(
      "Metro Subway Transit",
      "Amsterdam Metro 52 • Centraal",
      "Steel rail screech, electric traction motor hum, and ambient passenger murmurs.",
      80.0f, color(255, 175, 45)
    ),
    new Soundscape(
      "Rainy City Street",
      "Leidsestraat • Wet Asphalt",
      "Steady rainfall hiss, passing electric trams, and distant urban street rumble.",
      74.0f, color(65, 180, 255)
    )
  };
}

void initParticles() {
  particles = new ArrayList<AcousticParticle>();
  for (int i = 0; i < NUM_PARTICLES; i++) {
    particles.add(new AcousticParticle());
  }
}

// -------------------------------------------------------------
// Real-Time Synthesized Ambient Noise & Anti-Noise Audio Engine
// -------------------------------------------------------------
void initAudioEngine() {
  try {
    AudioFormat format = new AudioFormat(44100.0f, 16, 1, true, false);
    DataLine.Info info = new DataLine.Info(SourceDataLine.class, format);
    if (AudioSystem.isLineSupported(info)) {
      audioLine = (SourceDataLine) AudioSystem.getLine(info);
      audioLine.open(format, 4096);
      audioLine.start();

      audioThread = new Thread(new Runnable() {
        public void run() {
          final int BUFFER_SIZE = 512;
          byte[] buffer = new byte[BUFFER_SIZE * 2];
          float brownNoise = 0.0f;
          float phase1 = 0.0f;
          float phase2 = 0.0f;
          float timeStep = 1.0f / 44100.0f;

          while (audioRunning) {
            if (!audioEnabled || audioLine == null) {
              try { Thread.sleep(25); } catch (Exception ignored) {}
              continue;
            }

            float currentGain = audioGain;
            float ancFactor = audioAnc;
            int mode = audioSoundscape;

            // Frequency and sound characteristics per soundscape
            float f1 = (mode == 0) ? 92.0f : (mode == 1 ? 145.0f : 180.0f);
            float f2 = (mode == 0) ? 184.0f : (mode == 1 ? 290.0f : 420.0f);

            // ANC acoustic attenuation: non-linear decibel drop
            float attenuation = pow(1.0f - ancFactor, 2.2f);
            if (ancFactor > 0.96f) attenuation = 0.002f;

            for (int i = 0; i < BUFFER_SIZE; i++) {
              // 1. Synthesize ambient noise (low drone + pink/brown noise filter)
              float white = (float) (Math.random() * 2.0 - 1.0);
              brownNoise = (brownNoise + (0.05f * white)) / 1.05f;

              phase1 += 2.0f * (float) Math.PI * f1 * timeStep;
              phase2 += 2.0f * (float) Math.PI * f2 * timeStep;
              if (phase1 > 2.0f * (float) Math.PI) phase1 -= 2.0f * (float) Math.PI;
              if (phase2 > 2.0f * (float) Math.PI) phase2 -= 2.0f * (float) Math.PI;

              float tonalDrone = (float) (Math.sin(phase1) * 0.45f + Math.sin(phase2) * 0.25f);
              float rawAmbient = (brownNoise * 0.55f + tonalDrone * 0.45f);

              // 2. Cancellation in headphones
              float cancelledSample = rawAmbient * attenuation * currentGain * 0.65f;

              if (cancelledSample > 0.95f) cancelledSample = 0.95f;
              if (cancelledSample < -0.95f) cancelledSample = -0.95f;

              short sample16 = (short) (cancelledSample * 32767.0f);
              buffer[i * 2] = (byte) (sample16 & 0xFF);
              buffer[i * 2 + 1] = (byte) ((sample16 >> 8) & 0xFF);
            }

            audioLine.write(buffer, 0, buffer.length);
          }
        }
      });
      audioThread.setPriority(Thread.MAX_PRIORITY);
      audioThread.setDaemon(true);
      audioThread.start();
      println("🔊 Procedural 44.1kHz Audio Engine initialized successfully.");
    }
  } catch (Exception e) {
    println("⚠️ Audio warning: Procedural audio unavailable (" + e.getMessage() + "). Running in visual mode.");
    audioEnabled = false;
  }
}

// -------------------------------------------------------------
// Auto-detect & Connect to trackpad_pressure Virtual Serial Bridge
// -------------------------------------------------------------
void connectSerial() {
  try {
    String portToUse = "";

    // 1. Auto-discover active trackpad_pressure port from /tmp
    File autoPortFile = new File("/tmp/trackpad_pressure_port.txt");
    if (autoPortFile.exists()) {
      String[] lines = loadStrings(autoPortFile);
      if (lines != null && lines.length > 0 && lines[0].trim().length() > 0) {
        portToUse = lines[0].trim();
        println("📡 Auto-detected trackpad_pressure port from /tmp: " + portToUse);
      }
    }

    // 2. Fallback to physical Arduino USB modem if simulator not running
    if (portToUse.length() == 0) {
      String[] ports = Serial.list();
      for (String p : ports) {
        if (p.contains("tty.usbmodem") || p.contains("cu.usbmodem")) {
          portToUse = p;
          break;
        }
      }
    }

    // 3. Fallback default
    if (portToUse.length() == 0) {
      portToUse = "/dev/ttys031";
    }

    println("🔌 Connecting to serial port: " + portToUse);
    activePort = portToUse;
    arduino = new Serial(this, portToUse, 9600);
    arduino.bufferUntil('\n');
    delay(150);
    arduino.clear();
    isSerialConnected = true;
    lastSerialReceiveTime = millis();
    println("✅ Connected to Trackpad Pressure Bridge!");
  } catch (Exception e) {
    println("ℹ️ Serial notice: Waiting for './trackpad_pressure' bridge to start (" + e.getMessage() + ")");
  }
}

// =============================================================
// DRAW LOOP (60 FPS)
// =============================================================
void draw() {
  // 1. Connection Watchdog & Auto-reconnect
  checkSerialWatchdog();

  // 2. Easing & Numerical Updates
  smoothedFsr = lerp(smoothedFsr, (float) fsrRaw, 0.15f);
  currentAnc = lerp(currentAnc, targetAnc, smoothing);
  currentDb = lerp(currentDb, targetDb, smoothing);
  wavePhase += 0.09f + (1.0f - currentAnc) * 0.05f;

  // Sync to Audio Thread
  audioAnc = currentAnc;
  audioSoundscape = currentSoundscapeIdx;

  // 3. Render Background & Canvas
  drawDarkAestheticBackground();

  // 4. Render Center Stage: Listener Avatar & Fullscreen Acoustic Shield Particle Field
  drawAcousticIsolationStage(width * 0.5f, height * 0.5f);

  // 5. Render Top Navigation Bar & Soundscape Status
  drawTopNavigationBar();

  // 6. Render Glassmorphic Trackpad Force HUD (Top Right)
  drawTrackpadForceHUD();

  // 7. Render Sticky Hold Progress Ring & Notifications
  drawStickyHoldIndicator();
  drawNotificationBanner();

  // 8. Bottom Shortcut & Instructions Bar
  drawBottomHelpBar();
}

// -------------------------------------------------------------
// Connection Watchdog
// -------------------------------------------------------------
void checkSerialWatchdog() {
  if (!isSerialConnected || (millis() - lastSerialReceiveTime > 3500)) {
    if (millis() - lastReconnectAttempt > 2000) {
      lastReconnectAttempt = millis();
      File f = new File("/tmp/trackpad_pressure_port.txt");
      if (f.exists()) {
        try {
          String[] lines = loadStrings(f);
          if (lines != null && lines.length > 0) {
            String p = lines[0].trim();
            if (!p.equals(activePort) || !isSerialConnected) {
              println("🔄 Re-attaching to bridge on port " + p);
              if (arduino != null) {
                try { arduino.stop(); } catch (Exception ignored) {}
              }
              activePort = p;
              arduino = new Serial(this, activePort, 9600);
              arduino.bufferUntil('\n');
              isSerialConnected = true;
              lastSerialReceiveTime = millis();
            }
          }
        } catch (Exception ignored) {}
      }
    }
  }
}

// -------------------------------------------------------------
// Background Aesthetics
// -------------------------------------------------------------
void drawDarkAestheticBackground() {
  background(11, 14, 20);

  // Subtle radial gradient centered on stage
  noFill();
  float cx = width * 0.5f;
  float cy = height * 0.5f;
  for (int r = 580; r >= 100; r -= 40) {
    stroke(20, 27, 40, map((float)r, 100.0f, 580.0f, 45.0f, 0.0f));
    strokeWeight(40.0f);
    ellipse(cx, cy, (float)(r * 2), (float)(r * 2));
  }

  // Tech grid lines
  stroke(22, 29, 42, 50);
  strokeWeight(1.0f);
  for (int x = 0; x < width; x += 64) line((float)x, 0.0f, (float)x, (float)height);
  for (int y = 0; y < height; y += 64) line(0.0f, (float)y, (float)width, (float)y);
}

// -------------------------------------------------------------
// Center Stage: Listener Avatar & Fullscreen Acoustic Shield
// -------------------------------------------------------------
void drawAcousticIsolationStage(float cx, float cy) {
  pushMatrix();
  translate(cx, cy);

  Soundscape sc = soundscapes[currentSoundscapeIdx];
  float shieldRadius = 140.0f + currentAnc * 35.0f;

  // 1. Draw Outer Acoustic Wave Boundary Rings
  noFill();
  for (int i = 1; i <= 4; i++) {
    float ringR = shieldRadius + (float)i * 75.0f + sin(wavePhase + (float)i) * 8.0f;
    stroke(red(sc.accentColor), green(sc.accentColor), blue(sc.accentColor), (1.0f - currentAnc * 0.8f) * (45.0f / (float)i));
    strokeWeight(1.5f);
    ellipse(0.0f, 0.0f, ringR * 2.0f, ringR * 2.0f);
  }

  // 2. Update & Draw Acoustic Particles across the canvas
  for (AcousticParticle p : particles) {
    p.update(currentAnc, cx, cy, shieldRadius);
    p.draw(currentAnc, sc.accentColor);
  }

  // 3. Draw Active ANC Acoustic Forcefield Shield Dome
  if (currentAnc > 0.03f) {
    // Outer Glow Aura
    for (int r = 24; r >= 4; r -= 4) {
      noFill();
      stroke(0, 230, 255, map((float)r, 4.0f, 24.0f, 90.0f * currentAnc, 0.0f));
      strokeWeight((float)r);
      ellipse(0.0f, 0.0f, (shieldRadius + 4.0f) * 2.0f, (shieldRadius + 4.0f) * 2.0f);
    }

    // High-energy Shield Membrane
    fill(0, 210, 255, 25.0f * currentAnc);
    stroke(0, 240, 255, 140.0f + 115.0f * currentAnc);
    strokeWeight(2.5f + currentAnc * 2.0f);
    ellipse(0.0f, 0.0f, shieldRadius * 2.0f, shieldRadius * 2.0f);

    // Dynamic rotating phase nodes along the shield perimeter
    int numNodes = 16;
    for (int i = 0; i < numNodes; i++) {
      float a = (TWO_PI / (float)numNodes) * (float)i + (wavePhase * 0.35f);
      float nx = cos(a) * shieldRadius;
      float ny = sin(a) * shieldRadius;
      fill(255);
      noStroke();
      float nodeSize = 4.0f + sin(wavePhase * 2.5f + (float)i) * 2.0f;
      ellipse(nx, ny, nodeSize, nodeSize);
    }
  }

  // 4. Center Listener Avatar with Over-Ear ANC Headphones
  noFill();
  stroke(currentAnc > 0.5f ? color(0, 230, 200) : color(50, 70, 95));
  strokeWeight(2.0f);
  ellipse(0.0f, 0.0f, 130.0f, 130.0f);

  // Headphone Headband
  noFill();
  stroke(220, 235, 255);
  strokeWeight(5.0f);
  arc(0.0f, -8.0f, 86.0f, 86.0f, PI, TWO_PI);

  // Left & Right Earcups
  fill(30, 42, 60);
  stroke(currentAnc > 0.5f ? color(0, 240, 255) : color(90, 120, 160));
  strokeWeight(2.5f);
  rect(-50.0f, -22.0f, 18.0f, 44.0f, 8.0f);
  rect(32.0f, -22.0f, 18.0f, 44.0f, 8.0f);

  // Listener Head silhouette
  fill(55, 72, 98);
  noStroke();
  ellipse(0.0f, 2.0f, 52.0f, 58.0f);

  // 5. Clean ANC Status Pill below listener
  float pillW = 320.0f;
  float pillH = 38.0f;
  float pillY = shieldRadius + 26.0f;

  fill(14, 20, 32, 235);
  stroke(currentAnc > 0.05f ? (isAncLocked ? color(0, 230, 160) : color(0, 230, 255)) : color(50, 68, 90));
  strokeWeight(1.5f);
  rect(-pillW * 0.5f, pillY, pillW, pillH, 19.0f);

  fill(currentAnc > 0.05f ? (isAncLocked ? color(0, 230, 160) : color(0, 240, 255)) : color(140, 165, 190));
  textAlign(CENTER, CENTER);
  textSize(12);

  String statusText;
  if (currentAnc < 0.05f) {
    statusText = "TRANSPARENCY MODE • 0 dB REDUCTION";
  } else {
    String tierLabel = getTierName(currentTier).toUpperCase();
    statusText = String.format("%s • -%.1f dB SPL (%.0f%%)", tierLabel, currentAnc * 45.0f, currentAnc * 100.0f);
  }
  text(statusText, 0.0f, pillY + pillH * 0.5f);

  popMatrix();
}

// -------------------------------------------------------------
// Top Navigation & Soundscape Bar
// -------------------------------------------------------------
void drawTopNavigationBar() {
  Soundscape sc = soundscapes[currentSoundscapeIdx];

  // Environment Selector Pill (Top Left)
  pushMatrix();
  translate(40.0f, 24.0f);

  fill(16, 22, 32, 240);
  stroke(36, 48, 68);
  strokeWeight(1.2f);
  rect(0.0f, 0.0f, 390.0f, 52.0f, 12.0f);

  // Environment icon / color circle
  fill(sc.accentColor);
  noStroke();
  ellipse(26.0f, 26.0f, 14.0f, 14.0f);

  // Environment details
  fill(255);
  textAlign(LEFT, TOP);
  textSize(14);
  text(sc.name, 44.0f, 10.0f);

  fill(130, 155, 185);
  textSize(11);
  text(sc.subtitle + " • Press Space to switch", 44.0f, 29.0f);

  popMatrix();

  // Audio Engine Toggle Pill (Center Top)
  pushMatrix();
  translate(width * 0.5f - 80.0f, 24.0f);

  fill(16, 22, 32, 240);
  stroke(audioEnabled ? color(0, 230, 160) : color(60, 75, 95));
  strokeWeight(1.2f);
  rect(0.0f, 0.0f, 160.0f, 40.0f, 20.0f);

  fill(audioEnabled ? color(0, 230, 160) : color(140, 155, 175));
  textAlign(CENTER, CENTER);
  textSize(11);
  text(audioEnabled ? "🔊 SOUND ON ('M')" : "🔇 MUTED ('M')", 80.0f, 20.0f);

  popMatrix();
}

// -------------------------------------------------------------
// Top-Right Glassmorphic Trackpad Force HUD
// -------------------------------------------------------------
void drawTrackpadForceHUD() {
  pushMatrix();
  float hudW = 350.0f;
  float hudH = 114.0f;
  float hudX = width - hudW - 40.0f;
  float hudY = 24.0f;
  translate(hudX, hudY);

  // Glassmorphic Card Body
  fill(16, 22, 34, 235);
  stroke(isAncLocked ? color(0, 230, 160) : color(40, 60, 85));
  strokeWeight(isAncLocked ? 2.0f : 1.5f);
  rect(0.0f, 0.0f, hudW, hudH, 14.0f);

  // Connection indicator dot
  boolean connected = isSerialConnected && (millis() - lastSerialReceiveTime < 3500);
  fill(connected ? color(0, 230, 160) : color(255, 170, 0));
  noStroke();
  ellipse(20.0f, 22.0f, 10.0f, 10.0f);

  // Title
  fill(255);
  textAlign(LEFT, CENTER);
  textSize(13);
  text(connected ? "TRACKPAD FORCE SENSOR" : "WAITING FOR BRIDGE...", 34.0f, 22.0f);

  // Port name
  fill(130, 160, 190);
  textAlign(RIGHT, CENTER);
  textSize(10);
  text(activePort, hudW - 16.0f, 22.0f);

  // Pressure readout in grams
  fill(255);
  textAlign(LEFT, CENTER);
  textSize(22);
  text((int) smoothedFsr + "g", 20.0f, 58.0f);

  fill(130, 160, 190);
  textSize(12);
  text("/ 1200g Force", 88.0f, 60.0f);

  // Active ANC Percentage
  fill(isAncLocked ? color(0, 230, 160) : color(0, 230, 255));
  textAlign(RIGHT, CENTER);
  textSize(15);
  text(String.format("ANC: %.0f%%", currentAnc * 100.0f), hudW - 16.0f, 58.0f);

  // Pressure Progress Bar
  float barX = 20.0f;
  float barY = 82.0f;
  float barW = hudW - 40.0f;
  float barH = 12.0f;

  fill(28, 38, 54);
  noStroke();
  rect(barX, barY, barW, barH, 6.0f);

  float filledW = map(constrain(smoothedFsr, 0.0f, (float) FSR_MAX), 0.0f, (float) FSR_MAX, 0.0f, barW);
  if (filledW > 0.0f) {
    int barFill = isAncLocked ? color(0, 230, 160) : lerpColor(color(0, 210, 255), color(255, 90, 80), smoothedFsr / (float) FSR_MAX);
    fill(barFill);
    rect(barX, barY, filledW, barH, 6.0f);
  }

  // Tier ticks on the bar (80g, 400g, 800g)
  stroke(16, 22, 34);
  strokeWeight(2.0f);
  line(barX + (80.0f / (float)FSR_MAX) * barW, barY, barX + (80.0f / (float)FSR_MAX) * barW, barY + barH);
  line(barX + (400.0f / (float)FSR_MAX) * barW, barY, barX + (400.0f / (float)FSR_MAX) * barW, barY + barH);
  line(barX + (800.0f / (float)FSR_MAX) * barW, barY, barX + (800.0f / (float)FSR_MAX) * barW, barY + barH);

  popMatrix();
}

// -------------------------------------------------------------
// Sticky Hold Progress Indicator
// -------------------------------------------------------------
void drawStickyHoldIndicator() {
  if (holdProgress > 0.05f && holdProgress < 1.0f) {
    float cx = width * 0.5f;
    float cy = height * 0.5f;

    noFill();
    stroke(255, 255, 255, 100);
    strokeWeight(6.0f);
    ellipse(cx, cy, 220.0f, 220.0f);

    stroke(0, 230, 160);
    strokeWeight(6.0f);
    strokeCap(ROUND);
    arc(cx, cy, 220.0f, 220.0f, -HALF_PI, -HALF_PI + holdProgress * TWO_PI);

    fill(255);
    textAlign(CENTER, CENTER);
    textSize(11);
    text("HOLD 2S TO LOCK", cx, cy + 118.0f);
  }
}

// -------------------------------------------------------------
// Notification Banner
// -------------------------------------------------------------
void drawNotificationBanner() {
  if (lockNotificationTimer > 0) {
    float alpha = constrain((float)(lockNotificationTimer * 4), 0.0f, 255.0f);
    float nw = 480.0f;
    float nh = 46.0f;
    float nx = (width - nw) * 0.5f;
    float ny = 100.0f;

    fill(14, 20, 32, alpha * 0.95f);
    stroke(lockNotificationColor, alpha);
    strokeWeight(1.5f);
    rect(nx, ny, nw, nh, 12.0f);

    fill(lockNotificationColor, alpha);
    textAlign(CENTER, CENTER);
    textSize(13);
    text(lockNotificationText, nx + nw * 0.5f, ny + nh * 0.5f);

    lockNotificationTimer--;
  }
}

// -------------------------------------------------------------
// Bottom Help Bar
// -------------------------------------------------------------
void drawBottomHelpBar() {
  fill(12, 16, 24, 220);
  noStroke();
  rect(0.0f, height - 38.0f, (float)width, 38.0f);

  stroke(26, 36, 50);
  line(0.0f, height - 38.0f, (float)width, height - 38.0f);

  fill(130, 155, 185);
  textAlign(LEFT, CENTER);
  textSize(11);
  text("💡 CONTROLS: Press harder on Force Touch Trackpad to cancel noise • Hold 2s for Sticky Lock • Triple-tap trackpad to unlock", 40.0f, height - 19.0f);

  textAlign(RIGHT, CENTER);
  text("Keys: [UP/DOWN] Simulate Force • [1-4] Jump Tier • [U] Unlock • [Space] Soundscape • [M] Mute", (float)width - 40.0f, height - 19.0f);
}

// =============================================================
// SERIAL COMMUNICATION (trackpad_pressure Bridge)
// =============================================================
void serialEvent(Serial port) {
  while (port.available() > 0) {
    String message = port.readStringUntil('\n');
    if (message == null) break;
    message = trim(message);
    if (message.length() == 0) continue;

    lastSerialReceiveTime = millis();
    isSerialConnected = true;

    // Capacitive touch or tap event
    if (message.equals("TOUCH") || message.equals("TAP")) {
      registerTap();
      continue;
    }

    if (message.equals("READY")) continue;

    // FSR continuous pressure reading (0 - 1200)
    try {
      int parsedVal = parseInt(message);
      updateANCFromFSR(parsedVal);
    } catch (Exception ignored) {}
  }
}

// -------------------------------------------------------------
// Core ANC & Force Touch Pressure Mapping Engine
// -------------------------------------------------------------
void updateANCFromFSR(int val) {
  fsrRaw = constrain(val, 0, FSR_MAX);

  // Pressure impulse detection for quick physical tap (<380ms)
  if (fsrRaw >= 50 && !fsrWasPressed) {
    fsrWasPressed = true;
    fsrPressStartTime = millis();
  } else if (fsrRaw < 25 && fsrWasPressed) {
    fsrWasPressed = false;
    int pressDuration = millis() - fsrPressStartTime;
    if (pressDuration < 380) {
      registerTap();
    }
  }

  // Auto-reset tapCount if paused
  if (isAncLocked && tapCount > 0 && (millis() - lastTapTime > TAP_MAX_INTERVAL_MS)) {
    tapCount = 0;
  }

  // 1. Calculate instantaneous target ANC & Tier from physical pressure
  int instantTier = 1;
  float instantAnc = 0.0f;
  Soundscape sc = soundscapes[currentSoundscapeIdx];
  float baseDb = sc.baseDb;

  if (fsrRaw < 80) {
    // Tier 1: Transparency / Ambient Mode (0 - 80g)
    instantTier = 1;
    instantAnc = 0.0f;
  } else if (fsrRaw < 400) {
    // Tier 2: Adaptive / Mild ANC (80 - 400g)
    instantTier = 2;
    instantAnc = map((float)fsrRaw, 80.0f, 400.0f, 0.15f, 0.50f);
  } else if (fsrRaw < 800) {
    // Tier 3: Deep Isolation (400 - 800g)
    instantTier = 3;
    instantAnc = map((float)fsrRaw, 400.0f, 800.0f, 0.50f, 0.85f);
  } else {
    // Tier 4: Zero-Noise Void (800 - 1200g)
    instantTier = 4;
    instantAnc = map((float)fsrRaw, 800.0f, 1200.0f, 0.85f, 1.0f);
  }

  // 2. Sticky Hold State Machine (holding pressure level for 2.0s)
  if (instantTier >= 2) {
    if (instantTier == holdTier) {
      int elapsed = millis() - holdStartTime;
      holdProgress = constrain((float)elapsed / 2000.0f, 0.0f, 1.0f);

      if (elapsed >= 2000 && (!isAncLocked || lockedTier != instantTier)) {
        // Sticky Lock Engaged!
        isAncLocked = true;
        lockedTier = instantTier;
        lockedAnc = instantAnc;
        holdProgress = 0.0f;
        tapCount = 0;

        lockNotificationText = String.format("🔒 Held 2s: Sticky ANC Locked at Tier %d (-%.0f dB)!", lockedTier, lockedAnc * 45.0f);
        lockNotificationColor = color(0, 230, 160);
        lockNotificationTimer = 130;
        println("🔒 Tier " + lockedTier + " sticky ANC locked!");
      }
    } else {
      holdTier = instantTier;
      holdStartTime = millis();
      holdProgress = 0.0f;
    }
  } else {
    // Finger resting or lifted: reset hold progress
    holdTier = 1;
    holdStartTime = millis();
    holdProgress = 0.0f;
  }

  // 3. Apply target values (if locked and finger released, maintain locked state)
  if (isAncLocked && fsrRaw < 80) {
    currentTier = lockedTier;
    targetAnc = lockedAnc;
  } else {
    currentTier = instantTier;
    targetAnc = instantAnc;
  }

  // Calculate target decibels: base ambient drops by up to 55 dB
  targetDb = baseDb - (targetAnc * 55.0f);
  if (targetDb < 22.0f) targetDb = 22.0f;
}

// -------------------------------------------------------------
// Soundscape Switching
// -------------------------------------------------------------
void nextSoundscape() {
  int now = millis();
  if (now - lastSoundscapeSwitchTime >= 250) {
    lastSoundscapeSwitchTime = now;
    currentSoundscapeIdx = (currentSoundscapeIdx + 1) % soundscapes.length;
    Soundscape sc = soundscapes[currentSoundscapeIdx];
    lockNotificationText = "🎧 Soundscape Changed: " + sc.name;
    lockNotificationColor = sc.accentColor;
    lockNotificationTimer = 90;
    println("🎧 Switched to soundscape: " + sc.name);
  }
}

// -------------------------------------------------------------
// Tap Registration & Multimodal Switching
// -------------------------------------------------------------
void registerTap() {
  int now = millis();

  // Handle Triple-Tap to Unlock Sticky ANC
  if (isAncLocked) {
    if (now - lastTapTime <= TAP_MAX_INTERVAL_MS) {
      tapCount++;
    } else {
      tapCount = 1;
    }
    lastTapTime = now;

    if (tapCount >= 3) {
      isAncLocked = false;
      tapCount = 0;
      updateANCFromFSR(0);
      lockNotificationText = "🔓 Triple-Tap: Unlocked to Transparency Mode (0 dB)";
      lockNotificationColor = color(0, 170, 255);
      lockNotificationTimer = 110;
      println("🔓 Triple tap detected: Unlocked sticky ANC!");
      return;
    }
  }
}

// -------------------------------------------------------------
// Interactive Keyboard & Mouse Fallback Controls
// -------------------------------------------------------------
void keyPressed() {
  if (key == ' ') {
    nextSoundscape();
  } else if (key == 't' || key == 'T') {
    nextSoundscape();
  } else if (key == 'm' || key == 'M') {
    audioEnabled = !audioEnabled;
    println("🔊 Audio Output: " + (audioEnabled ? "ON" : "MUTED"));
  } else if (key == 'u' || key == 'U' || key == '1') {
    isAncLocked = false;
    tapCount = 0;
    updateANCFromFSR(0);
    lockNotificationText = "🔓 Unlocked: Returned to Transparency Mode";
    lockNotificationColor = color(0, 170, 255);
    lockNotificationTimer = 90;
    println("⌨️ Unlocked to Transparency Mode");
  } else if (key == '2') {
    isAncLocked = true;
    lockedTier = 2;
    updateANCFromFSR(240);
    lockNotificationText = "🔒 Simulated Tier 2: Mild ANC Locked";
    lockNotificationColor = color(0, 230, 160);
    lockNotificationTimer = 90;
  } else if (key == '3') {
    isAncLocked = true;
    lockedTier = 3;
    updateANCFromFSR(600);
    lockNotificationText = "🔒 Simulated Tier 3: Deep ANC Locked";
    lockNotificationColor = color(0, 230, 160);
    lockNotificationTimer = 90;
  } else if (key == '4') {
    isAncLocked = true;
    lockedTier = 4;
    updateANCFromFSR(1000);
    lockNotificationText = "🔒 Simulated Tier 4: Maximum Silence Locked";
    lockNotificationColor = color(255, 100, 130);
    lockNotificationTimer = 90;
  } else if (keyCode == UP) {
    updateANCFromFSR(min(FSR_MAX, fsrRaw + 60));
    println("⌨️ Simulated Force: " + fsrRaw + "g");
  } else if (keyCode == DOWN) {
    updateANCFromFSR(max(0, fsrRaw - 60));
    println("⌨️ Simulated Force: " + fsrRaw + "g");
  }
}

void mousePressed() {
  registerTap();
}

// -------------------------------------------------------------
// Tier Metadata Helper Methods
// -------------------------------------------------------------
int getTierColor(int tier) {
  switch(tier) {
    case 1: return color(140, 160, 185); // Slate / Transparency
    case 2: return color(0, 210, 255);   // Cyan / Adaptive
    case 3: return color(0, 230, 160);   // Emerald / Deep
    case 4: return color(255, 90, 120);  // Neon Coral / Void
    default: return color(255);
  }
}

String getTierName(int tier) {
  switch(tier) {
    case 1: return "Transparency Mode";
    case 2: return "Adaptive ANC";
    case 3: return "Deep Isolation";
    case 4: return "Maximum Void Silence";
    default: return "Unknown";
  }
}

String getTierDesc(int tier) {
  switch(tier) {
    case 1: return "Full ambient passthrough (0 dB reduction)";
    case 2: return "Muffled low-frequencies (-18 dB reduction)";
    case 3: return "Near total cancellation (-32 dB reduction)";
    case 4: return "Destructive zero-noise zone (-45 dB reduction)";
    default: return "";
  }
}
