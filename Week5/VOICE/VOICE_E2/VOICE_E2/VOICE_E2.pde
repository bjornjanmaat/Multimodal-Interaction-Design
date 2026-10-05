import oscP5.*;
import netP5.*;
import processing.serial.*;

OscP5 oscP5;
Serial arduino;

PImage bg;
PImage overlay;

boolean maskActive = false;
String lastSpeech = "";

void setup() {
  size(1280, 720);

  // --- OSC ---
  oscP5 = new OscP5(this, 9000);

  // --- Serial ---
  printArray(Serial.list());

  // Replace with your Arduino port.
  // Mac example:     "/dev/cu.usbmodem1101"
  // Windows example: "COM3"
  arduino = new Serial(this, "/dev/cu.usbmodem2101", 9600);
  arduino.bufferUntil('\n');

  delay(2000);
  arduino.clear();

  // --- Images ---
  bg      = loadImage("BG.jpg");
  overlay = loadImage("Overlay.jpg");

  imageMode(CORNER);
}

void draw() {
  // Base background image.
  image(bg, 0, 0, width, height);

  // Draw overlay only when activated.
  if (maskActive) {
    image(overlay, 0, 0, width, height);
  }

  // Show recognised speech for debugging.
  fill(255);
  textSize(18);
  text("Heard: " + lastSpeech, 20, height - 25);
}

void oscEvent(OscMessage msg) {
  if (msg.checkAddrPattern("/speech")) {

    lastSpeech = msg.get(0).stringValue().toLowerCase().trim();
    println("Heard: " + lastSpeech);

    // Check "deactivate" first:
    // it contains the word "activate".
    if (lastSpeech.equals("deactivate")) {
      maskActive = false;
      sendArduinoMessage("OFF");
      println("Mask removed");
    } else if (lastSpeech.equals("activate")) {
      maskActive = true;
      sendArduinoMessage("ON");
      println("Mask active");
    }
  }
}

void sendArduinoMessage(String message) {
  if (arduino != null) {
    arduino.write(message + "\n");
    println("Sent to Arduino: " + message);
  }
}
