import processing.serial.*;

Serial arduino;

String[] imageFiles;
PImage currentBg;

void setup() {
  size(1280, 720);

  // Print all available serial ports in the Processing console.
  printArray(Serial.list());

  // Replace this with your Arduino port.
  // Mac example: "/dev/cu.usbmodem1101"
  // Windows example: "COM3"
  arduino = new Serial(this, "/dev/cu.usbmodem3101", 9600);

  // Tell Processing that each message ends with a new line.
  arduino.bufferUntil('\n');

  loadImageList();
  loadRandomImage();

  imageMode(CORNER);
}

void draw() {
  background(0);

  if (currentBg != null) {
    // Display image full-screen.
    image(currentBg, 0, 0, width, height);
  }
}

void serialEvent(Serial port) {
  String message = port.readStringUntil('\n');

  if (message == null) {
    return;
  }

  message = trim(message);

  println("Arduino says: " + message);

  // Arduino sends this once for each new touch.
  if (message.equals("TOUCH")) {
    loadRandomImage();
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
      println("Found image: " + file.getName());
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
  String imagePath = "backgrounds/" + imageFiles[index];

  currentBg = loadImage(imagePath);

  println("Loaded: " + imagePath);
}
