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
int fsrMin = 0;    // Adjust: value when FSR is untouched
int fsrMax = 1200;   // Adjust: value at maximum pressure

void setup() {
  size(1280, 720);

  printArray(Serial.list());

  String portToUse = "/dev/cu.usbmodem1101";
  File autoPortFile = new File("/tmp/trackpad_pressure_port.txt");
  if (autoPortFile.exists()) {
    String[] lines = loadStrings(autoPortFile);
    if (lines != null && lines.length > 0 && lines[0].trim().length() > 0) {
      portToUse = lines[0].trim();
      println("📡 Auto-detected trackpad_pressure port: " + portToUse);
    }
  }

  try {
    arduino = new Serial(this, portToUse, 9600);
    arduino.bufferUntil('\n');
    delay(200);
    arduino.clear();
  } catch (Exception e) {
    println("Serial port warning: " + e.getMessage());
  }

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
  while (port.available() > 0) {
    String message = port.readStringUntil('\n');
    if (message == null) break;
    message = trim(message);
    if (message.length() == 0) continue;

    // Capacitive touch: load a new random image.
    if (message.equals("TOUCH")) {
      println("⚡ Touch detected — loading new image.");
      loadRandomImage();
      continue;
    }

    // Ignore the startup confirmation message.
    if (message.equals("READY")) continue;

    // FSR
    try {
      fsrRaw = int(message);
      targetZoom = map(fsrRaw, fsrMin, fsrMax, minZoom, maxZoom);
      targetZoom = constrain(targetZoom, minZoom, maxZoom);
    } catch (Exception e) {
      // ignore
    }
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
