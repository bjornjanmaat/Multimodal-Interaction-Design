/**
 * REACH_E1 — object-oriented gaze reach   (v2: OSC diagnostics + mouse fallback)
 * MMIxD Week 3 · Modality 2: Vision
 *
 * You do NOT steer a 3D cursor with your eyes. Gaze has 2 DOF, a reach needs 3,
 * so the DEPTH LIVES IN THE SCENE: you look at an object, the system already
 * knows where it is, the arm plans the reach. That's "object-oriented gaze".
 *
 * ── IF IT ISN'T SEEING YOUR GAZE, READ THIS ────────────────────────────────
 *  1. Quit VISION_E1.pde first. If it's running it owns the UDP port and this
 *     sketch can't bind to it.
 *  2. This version listens on FIVE common ports at once and prints every OSC
 *     message it receives, on screen and in the console. Watch the PACKETS
 *     counter bottom-left — if it stays at 0, nothing is arriving at all and
 *     the problem is the port or the Python side, not this sketch.
 *  3. Press G to drive the cursor with the MOUSE instead, so a broken OSC
 *     link doesn't stop you building and demoing the rest.
 *  4. Press N to cycle coordinate ranges if the dot moves but is squashed or
 *     off-screen. Press C to recentre. Press F to flip X (mirrored webcam).
 *
 * KEYS
 *   G   toggle gaze source: OSC  <->  mouse
 *   N   cycle input range (normalised / 640x480 / 1280x720 / 1920x1080)
 *   F   flip X (webcam mirroring)
 *   C   recentre
 *   SPACE  hold = dead-man's switch (stand-in for the cap sensor)
 *   M   swap enable model: dead-man <-> parking zone
 *   R   release, reset the arm
 *   L   show/hide the OSC log
 */

import oscP5.*;
import netP5.*;

// ─────────────────────────────────────────── config
int[] PORTS = { 9000, 12000, 8000, 7000, 5005 };   // VISION.py sends to 9000
float SMOOTH     = 0.25;
float HIT_RADIUS = 95;
int   DWELL_MS   = 700;
int   REACH_MS   = 1100;

// ─────────────────────────────────────────── gaze
float gazeX, gazeY;
float rawX, rawY;                 // last numbers actually received
float offX = 0, offY = 0;
boolean haveGaze = false;
boolean useMouse = false;
boolean flipX = false;
int rangeMode = 0;                // 0 normalised, 1 640, 2 1280, 3 1920
String[] rangeName = { "normalised 0–1", "640 x 480", "1280 x 720", "1920 x 1080" };

// ─────────────────────────────────────────── OSC diagnostics
ArrayList<OscP5> receivers = new ArrayList<OscP5>();
ArrayList<String> boundPorts = new ArrayList<String>();
int packets = 0;
String[] logLines = new String[8];
int logIdx = 0;
boolean showLog = true;

// VISION.py sends three messages per frame:
//   /iris/left [x,y]   /iris/right [x,y]   /iris/center [x,y]
// We keep left and right separately as well as the centre, because the gap
// between them IS the vergence signal the brief throws away by averaging.
float lx, ly, rx, ry, cx, cy;
boolean haveL = false, haveR = false, haveC = false;
boolean useCentre = true;         // S toggles: centre message vs our own L/R average
float disparity = 0;              // |left - right| in input units
HashMap<String, Boolean> seenAddr = new HashMap<String, Boolean>();

// split-message support: some senders emit /eye/x and /eye/y separately
boolean gotX = false, gotY = false;
float pendX, pendY;

// ─────────────────────────────────────────── the scene
String[] names = { "CUP · upper shelf", "SAMPLE · table", "TOOL · floor" };
float[][] targets = {
  { -250, -180, -400 },
  {   30, 30, -110 },
  {  250, 200, 140 }
};
color[] tint = { #E8A95C, #61DA92, #4FC3E8 };
float[] sx = new float[3];
float[] sy = new float[3];

// ─────────────────────────────────────────── state machine
final int SEARCHING = 0, DWELLING = 1, REACHING = 2, HELD = 3;
int state = SEARCHING;
int candidate = -1, locked = -1;
int dwellStart = 0, reachStart = 0;

// ─────────────────────────────────────────── the arm
float[] base = { -400, 250, 200 };
float[] tip  = { -400, 250, 200 };

// ─────────────────────────────────────────── enable model
boolean deadman = true;
boolean spaceHeld = false;
boolean enabled = false;
float PARK_Y;


void setup() {
  size(1280, 720, P3D);
  PARK_Y = height - 90;
  gazeX = width * 0.5;
  gazeY = height * 0.5;
  textFont(createFont("Menlo", 12));

  for (int p : PORTS) {
    try {
      receivers.add(new OscP5(this, p));
      boundPorts.add(str(p));
      println("listening on " + p);
    }
    catch (Exception e) {
      println("could NOT bind port " + p + " — probably in use by another sketch");
    }
  }
  if (boundPorts.size() == 0) {
    println("!! no ports bound at all. Quit any other running Processing sketch.");
  }
  log("waiting for OSC on " + join(boundPorts.toArray(new String[0]), ", "));
}


// ─────────────────────────────────────────── OSC in
void oscEvent(OscMessage m) {
  packets++;
  String tt = m.typetag();
  String addr = m.addrPattern();

  // collect every numeric argument, whatever the type
  FloatList nums = new FloatList();
  for (int i = 0; i < tt.length(); i++) {
    char t = tt.charAt(i);
    if (t == 'i') nums.append(m.get(i).intValue());
    else if (t == 'f') nums.append(m.get(i).floatValue());
    else if (t == 'd') nums.append((float) m.get(i).doubleValue());
  }

  // log each distinct address ONCE — three messages a frame would drown the console
  if (!seenAddr.containsKey(addr)) {
    seenAddr.put(addr, true);
    String dump = addr + "  [" + tt + "] ";
    for (int i = 0; i < nums.size(); i++) dump += nf(nums.get(i), 0, 3) + " ";
    log(dump);
  }

  // ── the addresses VISION.py actually uses ──────────────────────────────
  if (addr.equals("/iris/left") && nums.size() >= 2) {
    lx = nums.get(0);
    ly = nums.get(1);
    haveL = true;
    updateFromIris();
    return;
  }
  if (addr.equals("/iris/right") && nums.size() >= 2) {
    rx = nums.get(0);
    ry = nums.get(1);
    haveR = true;
    updateFromIris();
    return;
  }
  if (addr.equals("/iris/center") && nums.size() >= 2) {
    cx = nums.get(0);
    cy = nums.get(1);
    haveC = true;
    updateFromIris();
    return;
  }

  // ── generic fallback for any other sender ──────────────────────────────
  if (nums.size() >= 4) {
    setGaze((nums.get(0) + nums.get(2)) * 0.5, (nums.get(1) + nums.get(3)) * 0.5);
  } else if (nums.size() >= 2) {
    setGaze(nums.get(0), nums.get(1));
  } else if (nums.size() == 1) {
    // split messages — decide by address
    String a = addr.toLowerCase();
    if (a.endsWith("x") || a.contains("/x")) {
      pendX = nums.get(0);
      gotX = true;
    } else if (a.endsWith("y") || a.contains("/y")) {
      pendY = nums.get(0);
      gotY = true;
    }
    if (gotX && gotY) {
      setGaze(pendX, pendY);
      gotX = gotY = false;
    }
  }
}

/** Drive the cursor from whichever iris source is selected, and keep the
 *  left/right gap around — that's the vergence signal, free, already in
 *  the stream, and discarded the moment you only listen to /iris/center. */
void updateFromIris() {
  if (haveL && haveR) disparity = dist(lx, ly, rx, ry);

  if (useCentre && haveC)      setGaze(cx, cy);
  else if (haveL && haveR)     setGaze((lx + rx) * 0.5, (ly + ry) * 0.5);
  else if (haveC)              setGaze(cx, cy);
}

void setGaze(float x, float y) {
  rawX = x;
  rawY = y;
  float px, py;
  switch (rangeMode) {
  case 1:
    px = map(x, 0, 640, 0, width);
    py = map(y, 0, 480, 0, height);
    break;
  case 2:
    px = map(x, 0, 1280, 0, width);
    py = map(y, 0, 720, 0, height);
    break;
  case 3:
    px = map(x, 0, 1920, 0, width);
    py = map(y, 0, 1080, 0, height);
    break;
  default:
    px = x * width;
    py = y * height;
    break;
  }
  if (flipX) px = width - px;
  gazeX = lerp(gazeX, px, SMOOTH);
  gazeY = lerp(gazeY, py, SMOOTH);
  haveGaze = true;
}

void log(String s) {
  logLines[logIdx % logLines.length] = s;
  logIdx++;
  println(s);
}


void draw() {
  background(14, 18, 21);

  if (useMouse) {
    gazeX = mouseX;
    gazeY = mouseY;
  }
  float gx = gazeX + offX;
  float gy = gazeY + offY;

  boolean live = useMouse || haveGaze;
  enabled = (deadman ? spaceHeld : (gy < PARK_Y)) && live;

  // ── 3D pass
  camera(0, -70, 780, 0, 0, 0, 0, 1, 0);
  lights();
  drawRoom();
  for (int i = 0; i < 3; i++) {
    sx[i] = screenX(targets[i][0], targets[i][1], targets[i][2]);
    sy[i] = screenY(targets[i][0], targets[i][1], targets[i][2]);
    drawTarget(i);
  }
  drawArm();

  update(gx, gy);

  // ── 2D overlay
  hint(DISABLE_DEPTH_TEST);
  camera();
  noLights();
  hud(gx, gy);
  hint(ENABLE_DEPTH_TEST);
}


void update(float gx, float gy) {
  if (state == REACHING) {
    float t = constrain((millis() - reachStart) / float(REACH_MS), 0, 1);
    float e = t * t * (3 - 2 * t);
    for (int k = 0; k < 3; k++) tip[k] = lerp(base[k], targets[locked][k], e);
    if (t >= 1) state = HELD;
    return;
  }
  if (state == HELD) return;

  if (!enabled) {
    state = SEARCHING;
    candidate = -1;
    return;
  }

  int best = -1;
  float bestD = HIT_RADIUS;
  for (int i = 0; i < 3; i++) {
    float d = dist(gx, gy, sx[i], sy[i]);
    if (d < bestD) {
      bestD = d;
      best = i;
    }
  }
  if (best != candidate) {
    candidate = best;
    dwellStart = millis();
  }

  if (candidate == -1) {
    state = SEARCHING;
  } else {
    state = DWELLING;
    if (millis() - dwellStart >= DWELL_MS) {
      locked = candidate;
      state = REACHING;
      reachStart = millis();
    }
  }
}


// ─────────────────────────────────────────── drawing
void drawRoom() {
  stroke(40, 46, 50);
  strokeWeight(1);
  noFill();
  for (int z = -500; z <= 200; z += 100) line(-500, 300, z, 500, 300, z);
  line(-500, 300, -500, -500, 300, 200);
  line( 500, 300, -500, 500, 300, 200);

  pushMatrix();
  translate(-250, -140, -400);
  fill(30, 35, 39);
  noStroke();
  box(260, 10, 160);
  popMatrix();
  pushMatrix();
  translate(  30, 70, -110);
  fill(30, 35, 39);
  noStroke();
  box(300, 10, 200);
  popMatrix();
}

void drawTarget(int i) {
  boolean hot = (i == candidate && state == DWELLING)
    || (i == locked && (state == REACHING || state == HELD));
  pushMatrix();
  translate(targets[i][0], targets[i][1], targets[i][2]);
  noStroke();
  fill(hot ? tint[i] : color(70, 78, 84));
  sphere(34);
  popMatrix();
}

void drawArm() {
  stroke(120, 130, 138);
  strokeWeight(6);
  line(base[0], base[1], base[2], tip[0], tip[1], tip[2]);
  pushMatrix();
  translate(tip[0], tip[1], tip[2]);
  noStroke();
  fill(state == HELD ? color(97, 218, 146) : color(160, 170, 178));
  sphere(16);
  popMatrix();
}

void hud(float gx, float gy) {
  if (!deadman) {
    noStroke();
    fill(enabled ? color(28, 32, 36) : color(52, 40, 30));
    rect(0, PARK_Y, width, height - PARK_Y);
    fill(enabled ? color(110, 118, 124) : color(232, 169, 92));
    textAlign(CENTER, CENTER);
    text(enabled ? "LOOK DOWN HERE TO PARK" : "PARKED — GAZE IS INERT",
      width / 2, PARK_Y + (height - PARK_Y) / 2);
  }

  noFill();
  stroke(enabled ? color(232, 169, 92) : color(70, 78, 84));
  strokeWeight(2);
  ellipse(gx, gy, 26, 26);
  point(gx, gy);

  if (state == DWELLING && candidate >= 0) {
    float p = (millis() - dwellStart) / float(DWELL_MS);
    stroke(tint[candidate]);
    strokeWeight(4);
    noFill();
    arc(sx[candidate], sy[candidate], 92, 92, -HALF_PI, -HALF_PI + p * TWO_PI);
  }

  int lbl = (state == SEARCHING || state == DWELLING) ? candidate : locked;
  if (lbl >= 0) {
    fill(tint[lbl]);
    textAlign(CENTER, BOTTOM);
    text(names[lbl], sx[lbl], sy[lbl] - 56);
  }

  // status
  String[] label = { "SEARCHING", "DWELLING", "REACHING", "HOLDING" };
  fill(140, 148, 154);
  textAlign(LEFT, TOP);
  text(label[state]
    + "    source: " + (useMouse ? "MOUSE [G]" : "OSC [G]")
    + "    enable: " + (deadman ? "DEAD-MAN (hold SPACE)" : "PARKING ZONE") + " [M]"
    + "    range: " + rangeName[rangeMode] + " [N]"
    + (flipX ? "  flipX [F]" : ""),
    20, 20);

  // the diagnostic that matters
  textAlign(LEFT, BOTTOM);
  fill(packets > 0 ? color(97, 218, 146) : color(232, 169, 92));
  text("OSC PACKETS: " + packets
    + "    ports: " + join(boundPorts.toArray(new String[0]), ",")
    + "    raw: " + nf(rawX, 0, 3) + ", " + nf(rawY, 0, 3)
    + "    source: " + (useCentre ? "/iris/center" : "L+R avg") + " [S]"
    + "    disparity: " + nf(disparity, 0, 4),
    20, height - 20);

  if (showLog) {
    fill(110, 118, 124);
    textAlign(RIGHT, TOP);
    for (int i = 0; i < logLines.length; i++) {
      int k = (logIdx - 1 - i + logLines.length * 4) % logLines.length;
      if (logLines[k] != null) text(logLines[k], width - 20, 20 + i * 16);
    }
  }
}


// ─────────────────────────────────────────── input
void keyPressed() {
  if (key == ' ') spaceHeld = true;
  if (key == 'g' || key == 'G') useMouse = !useMouse;
  if (key == 's' || key == 'S') useCentre = !useCentre;
  if (key == 'm' || key == 'M') deadman = !deadman;
  if (key == 'n' || key == 'N') rangeMode = (rangeMode + 1) % 4;
  if (key == 'f' || key == 'F') flipX = !flipX;
  if (key == 'l' || key == 'L') showLog = !showLog;
  if (key == 'r' || key == 'R') {
    state = SEARCHING;
    locked = -1;
    candidate = -1;
    tip[0] = base[0];
    tip[1] = base[1];
    tip[2] = base[2];
  }
  if (key == 'c' || key == 'C') {
    offX = width * 0.5 - gazeX;
    offY = height * 0.5 - gazeY;
  }
}

void keyReleased() {
  if (key == ' ') spaceHeld = false;
}
