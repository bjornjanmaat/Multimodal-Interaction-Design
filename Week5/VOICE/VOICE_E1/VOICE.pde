import oscP5.*;
import netP5.*;

OscP5 oscP5;

PImage bg;
PImage overlay;

boolean maskActive = false;
String lastSpeech = "";

void setup() {
  size(1280, 720);

  // Listen for OSC sent by Python
  oscP5 = new OscP5(this, 9000);

  // Load images from the data folder
  bg = loadImage("BG.jpg");
  overlay = loadImage("Overlay.jpg");

  imageMode(CORNER);
}

void draw() {
  // Base background image
  image(bg, 0, 0, width, height);

  // Draw mask only when activated
  if (maskActive) {
    image(overlay, 0, 0, width, height);
  }

  // Optional: show recognised speech for debugging
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
      println("Mask removed");

    } else if (lastSpeech.equals("activate")) {
      maskActive = true;
      println("Mask active");
    }
  }
}
