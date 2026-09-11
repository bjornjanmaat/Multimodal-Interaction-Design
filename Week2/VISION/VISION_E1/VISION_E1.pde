import oscP5.*;
import netP5.*;

PImage img;
PImage img2;
PImage imgMask;

OscP5 oscP5;
int lx, ly, rx, ry, cx, cy;
int zeroX, zeroY;
float easedX, easedY;
float easing = 0.06;
float threshold = 5.0;

void setup() {
  size(640, 360);
  oscP5 = new OscP5(this, 9000);
  img = loadImage("BGs.jpg");
  img2 = loadImage("overlays.jpg");
  imgMask = loadImage("BGs.jpg");
  img2.mask(imgMask);
  imageMode(CENTER);

  easedX = width/2;
  easedY = height/2;
 
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
    println("Calibrated at: " + zeroX + ", " + zeroY);
  }
}

void draw() {
  background(0, 102, 153);

  // apply easing
  easedX += (cx - easedX) * easing;
  easedY += (cy - easedY) * easing;

  image(img, width/2, height/2);
  image(img2, easedX, easedY);

  // check if img2 is near dead center
  boolean isCentered = abs(easedX - width/2) < threshold &&
                       abs(easedY - height/2) < threshold;

  // draw status text in top left
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
