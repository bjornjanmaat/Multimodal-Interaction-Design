import oscP5.*;
import netP5.*;
import processing.serial.*;

PImage img;
PImage img2;
PImage imgMask;

OscP5 oscP5;
Serial arduino;

int lx, ly, rx, ry, cx, cy;
int zeroX, zeroY;
float easedX, easedY;
float easing = 0.06;
float threshold = 5.0;

boolean matched = false;

void setup() {
  size(640, 360);

  // --- OSC ---
  oscP5 = new OscP5(this, 9000);

  // --- Serial ---
  printArray(Serial.list());

  // Replace with your Arduino port.
  arduino = new Serial(this, "/dev/cu.usbmodem2101", 9600);
  arduino.bufferUntil('\n');

  delay(2000);
  arduino.clear();

  // --- Images ---
  img = loadImage("BGs.jpg");
  img2 = loadImage("overlays.jpg");
  imgMask = loadImage("BGs.jpg");
  img2.mask(imgMask);
  imageMode(CENTER);

  easedX = width/2;
  easedY = height/2;

  // Tell Arduino we are searching on startup.
  sendArduinoMessage("SEARCHING");
}

void oscEvent(OscMessage msg) {
  if (msg.checkAddrPattern("/iris/left")) {
    lx = msg.get(0).intValue();
    ly = msg.get(1).intValue();
  }
  if (msg.checkAddrPattern("/iris/right")) {
    rx = msg.get(0).intValue();
    ry = msg.get(1).intValue();
  }
  if (msg.checkAddrPattern("/iris/center")) {
    cx = constrain(msg.get(0).intValue() - zeroX, 0, 640);
    cy = constrain(msg.get(1).intValue() - zeroY, 0, 360);
  }
}

void keyPressed() {
  if (key == 'c' || key == 'C') {
    zeroX = cx;
    zeroY = cy;

    // Reset to searching when recalibrating.
    matched = false;
    sendArduinoMessage("SEARCHING");

    println("Calibrated at: " + zeroX + ", " + zeroY);
  }
}

void draw() {
  background(0, 102, 153);

  // Apply easing.
  easedX += (cx - easedX) * easing;
  easedY += (cy - easedY) * easing;

  image(img, width/2, height/2);
  image(img2, easedX, easedY);

  // Check if img2 is near dead centre.
  boolean isCentered = abs(easedX - width/2) < threshold &&
    abs(easedY - height/2) < threshold;

  // Only send to Arduino when the state changes.
  if (isCentered && !matched) {
    matched = true;
    sendArduinoMessage("MATCH");
  } else if (!isCentered && matched) {
    matched = false;
    sendArduinoMessage("SEARCHING");
  }

  // Draw status text in top left.
  textSize(16);
  textAlign(LEFT, TOP);
  if (isCentered) {
    fill(163, 212, 255);
    text("Sample Match!", 20, 20);
  } else {
    fill(255, 255, 255);
    text("Searching...", 20, 20);
  }

  textSize(16);
  textAlign(LEFT, BOTTOM);
  fill(255, 255, 255);
  text("Press C to Calibrate", 20, 340);
}

void sendArduinoMessage(String message) {
  if (arduino != null) {
    arduino.write(message + "\n");
    println("Sent to Arduino: " + message);
  }
}
