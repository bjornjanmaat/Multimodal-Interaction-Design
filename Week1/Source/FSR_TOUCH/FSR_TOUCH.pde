import processing.serial.*;

Serial arduino;

String[] imageFiles;
PImage currentBg;

float zoom = 1.0;
float targetZoom = 1.0;
float zoomSmoothing = 0.08;  // Smoothing: lower = smoother but slower

float minZoom = 1.0;
float maxZoom = 2.5;

int fsrRaw = 0;
int fsrMin = 50;    // Adjust: value when FSR is untouched
int fsrMax = 900;   // Adjust: value at maximum pressure

void setup() {
  size(1280, 720);

  printArray(Serial.list());

  // Replace with your Arduino port.
  arduino = new Serial(this, "/dev/cu.usbmodem1101", 9600);
  arduino.bufferUntil('\n');

  // Wait for Arduino to calibrate.
  delay(2000);
  arduino.clear();

  loadImageList();
  loadRandomImage();

  imageMode(CORNER);
}

void draw() {
  background(0);

  // Smoothly zoom toward the target amount.
  zoom = lerp(zoom, targetZoom, zoomSmoothing);

  if (currentBg != null) {
    // Calculate zoomed dimensions.
    float zoomedW = width * zoom;
    float zoomedH = height * zoom;

    // Keep image centred while zooming.
    float offsetX = (width - zoomedW) / 2.0;
    float offsetY = (height - zoomedH) / 2.0;

    image(currentBg, offsetX, offsetY, zoomedW, zoomedH);
  }

  // Debug overlay
  fill(255);
  noStroke();
  textSize(16);
  text("FSR raw: " + fsrRaw, 20, 30);
  text("Zoom: " + nf(zoom, 1, 2) + "x", 20, 55);
  text("Touch: new random image", 20, 80);
}

void serialEvent(Serial port) {
  String message = port.readStringUntil('\n');

  if (message == null) return;

  message = trim(message);

  if (message.length() == 0) return;

  // Capacitive touch: load a new random image.
  if (message.equals("TOUCH")) {
    println("Touch detected — loading new image.");
    loadRandomImage();
    return;
  }

  // Ignore the startup confirmation message.
  if (message.equals("READY")) return;

  // FSR
  try {
    fsrRaw = int(message);

    targetZoom = map(fsrRaw, fsrMin, fsrMax, minZoom, maxZoom);
    targetZoom = constrain(targetZoom, minZoom, maxZoom);

  } catch (Exception e) {
    println("Parse error: " + e.getMessage());
  }
}

void loadImageList() {
  File folder = new File(dataPath("backgrounds"));

  if (!folder.exists()) {
    println("Folder not found: " + folder.getAbsolutePath());
    imageFiles = new String[0];
    return;
  }

  File[] files = folder.listFiles();

  if (files == null) {
    println("Cannot read image folder.");
    imageFiles = new String[0];
    return;
  }

  ArrayList<String> names = new ArrayList<String>();

  for (File file : files) {
    String name = file.getName().toLowerCase();
    if (name.endsWith(".jpg") ||
        name.endsWith(".jpeg") ||
        name.endsWith(".png")) {
      names.add(file.getName());
      println("Found: " + file.getName());
    }
  }

  imageFiles = names.toArray(new String[0]);
  println("Total images: " + imageFiles.length);
}

void loadRandomImage() {
  if (imageFiles == null || imageFiles.length == 0) {
    println("No images found in data/backgrounds/");
    return;
  }

  int index = int(random(imageFiles.length));
  String path = "backgrounds/" + imageFiles[index];

  currentBg = loadImage(path);

  // Reset zoom when a new image loads.
  zoom = 1.0;
  targetZoom = 1.0;

  println("Loaded: " + path);
}
