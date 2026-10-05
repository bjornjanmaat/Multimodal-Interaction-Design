import processing.serial.*;

PImage img;
PImage img2;

Serial arduino;

float probeScale = 1.0;
float targetScale = 1.0;
float easing = 0.08;

float currentDistance = 0;

// Distance range from your sensor in cm.
// Adjust after testing your physical setup.
float minDistance = 5;
float maxDistance = 80;

void setup() {
  size(1280, 720);

  img  = loadImage("bg.jpg");
  img2 = loadImage("ProbeSM.png");

  img.format = ARGB;

  imageMode(CENTER);

  // --- Serial ---
  printArray(Serial.list());

  // Replace with your Arduino port.
  // Mac example:     "/dev/cu.usbmodem1101"
  // Windows example: "COM3"
  arduino = new Serial(this, "/dev/cu.usbmodem101", 9600);
  arduino.bufferUntil('\n');

  delay(2000);
  arduino.clear();
}

void draw() {
  background(0, 102, 153);

  image(img, width/2, height/2);

  // Smoothly move current scale toward target.
  probeScale = lerp(probeScale, targetScale, easing);

  // Draw probe at fixed centre position, scaled by distance.
  float probeW = img2.width  * probeScale;
  float probeH = img2.height * probeScale;

  image(img2, width/2, height/2, probeW, probeH);
}

void serialEvent(Serial port) {
  String data = port.readStringUntil('\n');

  if (data == null) return;

  data = trim(data);

  try {
    currentDistance = float(data);

    // Ignore zero readings (no echo received) and out-of-range values.
    if (currentDistance > 0 &&
      currentDistance >= minDistance &&
      currentDistance <= maxDistance) {

      // Near = large probe; far = small probe.
      targetScale = map(
        currentDistance,
        minDistance,
        maxDistance,
        2.5, // scale when hand is close
        0.25   // scale when hand is far
        );
    }
  }
  catch (Exception e) {
    println("Could not read distance: " + data);
  }
}
