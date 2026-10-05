import oscP5.*;
import netP5.*;

PImage img;
PImage img2;

OscP5 oscP5;
float objY = 180;  // object Y position

void setup() {
  size(1280, 720);
  oscP5 = new OscP5(this, 9000);
  img = loadImage("bg.jpg");
  img2 = loadImage("ProbeSM.png");
  img.format = ARGB;  // preserve alpha channel
  imageMode(CENTER);
}

void oscEvent(OscMessage msg) {
  if (msg.checkAddrPattern("/gesture/hand")) {
    int handNumber = msg.get(0).intValue();
    String gesture = msg.get(1).stringValue();
    float confidence = msg.get(2).floatValue();

    // If Thumb_Up with >60% confidence, raise object
    if (gesture.equals("Thumb_Up") && confidence > 0.6) {
      objY -= 5;  // move up by 5 pixels per frame
    }
    
        // If Thumb_Down with >60% confidence, lower object
    if (gesture.equals("Thumb_Down") && confidence > 0.6) {
      objY -= -5;  // move down by 5 pixels per frame
    }
    
  }
}

void draw() {
  background(0, 102, 153);
  
  image(img, width/2, height/2);
  
  // Draw object
  fill(255, 255, 255);
  image(img2, width/2, objY);
  
  // Constrain to screen
  objY = constrain(objY, 25, height - 25);
}
