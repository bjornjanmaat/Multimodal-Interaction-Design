import processing.serial.*;
import java.io.File;
import java.io.InputStream;
import java.io.FileOutputStream;
import java.net.URL;
import java.net.URLConnection;
import java.util.HashMap;
import java.util.HashSet;
import java.util.concurrent.ConcurrentLinkedQueue;

Serial arduino;

// Mapbox Tile Engine Configuration
HashMap<String, PImage> tileCache = new HashMap<String, PImage>();
HashSet<String> requestedTiles = new HashSet<String>();
ConcurrentLinkedQueue<String> downloadQueue = new ConcurrentLinkedQueue<String>();
boolean tileDownloaderRunning = true;

String mapboxToken = "";
String mapboxStyle = "navigation-night-v1"; // Options: navigation-night-v1, navigation-day-v1, dark-v11, outdoors-v12, streets-v12

// -------------------------------------------------------------
// 3 Scale Levels Configuration:
// Level 1 (Low pressure / untouched): Panned 3D perspective, z16.8, NO navigation line, directions active.
// Level 2 (Medium pressure): Flat 2D top-down, z15.0, WITH navigation line.
// Level 3 (High pressure): Flat 2D top-down, z13.0, WITH navigation line (City Overview).
// -------------------------------------------------------------
int currentLevel = 1;

float currentZoom = 17.8;
float targetZoom = 17.8;

float currentPitch = 64.0;   // 3D tilt pitch angle in degrees (64 deg for deep panned perspective, 0 deg for flat)
float targetPitch = 64.0;

float routeLineAlpha = 0.0;  // 0.0 in Level 1 (hidden), 1.0 in Level 2 & 3 (visible)
float targetRouteLineAlpha = 0.0;

float smoothing = 0.08;

int fsrRaw = 0;
int fsrMin = 0;
int fsrMax = 1200;

String activePort = "None";
boolean isSerialConnected = false;
int lastSerialReceiveTime = 0;
int lastTouchSwitchTime = 0;
int lastReconnectAttempt = 0;

// GPS Coordinates (Latitude, Longitude)
class LatLon {
  double lat, lon;
  LatLon(double lt, double ln) {
    lat = lt;
    lon = ln;
  }
}

class RouteData {
  String name;
  String destination;
  String nextTurn;
  String nextStreet;
  int turnDistanceM;
  float totalKm;
  int etaMin;
  float speedKmH;
  LatLon currentPos;
  LatLon destPos;
  LatLon[] waypoints;

  RouteData(String n, String dest, String turn, String street, int distM, float km, int eta, float spd,
    LatLon cur, LatLon dst, LatLon[] wps) {
    name = n;
    destination = dest;
    nextTurn = turn;
    nextStreet = street;
    turnDistanceM = distM;
    totalKm = km;
    etaMin = eta;
    speedKmH = spd;
    currentPos = cur;
    destPos = dst;
    waypoints = wps;
  }
}

RouteData[] routes;
int currentRouteIdx = 0;
float pulseAngle = 0;
int touchNotificationTimer = 0;

void setup() {
  size(1280, 720, P3D);
  smooth(4);

  // Load Mapbox access token from .env
  loadEnv();

  printArray(Serial.list());

  // Connect to Serial (Arduino or trackpad_pressure)
  try {
    String[] ports = Serial.list();
    String portToUse = "/dev/ttys031";

    // 1. Auto-discover active trackpad_pressure simulator port
    File autoPortFile = new File("/tmp/trackpad_pressure_port.txt");
    if (autoPortFile.exists()) {
      String[] lines = loadStrings(autoPortFile);
      if (lines != null && lines.length > 0 && lines[0].trim().length() > 0) {
        portToUse = lines[0].trim();
        println("📡 Auto-detected trackpad_pressure port from /tmp: " + portToUse);
      }
    }

    // 2. If no simulator file, auto-detect physical Arduino USB modem
    if (portToUse.length() == 0) {
      for (String p : ports) {
        if (p.contains("tty.usbmodem") || p.contains("cu.usbmodem")) {
          portToUse = p;
          break;
        }
      }
    }

    // 3. Fallback default
    if (portToUse.length() == 0) {
      portToUse = "/dev/ttys031";
    }

    println("Connecting to serial port: " + portToUse);
    activePort = portToUse;
    arduino = new Serial(this, portToUse, 9600);
    arduino.bufferUntil('\n');
    delay(200);
    arduino.clear();
    isSerialConnected = true;
  }
  catch (Exception e) {
    println("Serial warning (run './trackpad_pressure'): " + e.getMessage());
  }

  // Start background tile download worker for Mapbox
  thread("tileDownloadWorker");

  // Initialize Real Amsterdam Bike Routes
  initRoutes();
}

// Read Mapbox token from .env file
void loadEnv() {
  File envFile = new File(sketchPath(".env"));
  if (!envFile.exists()) {
    envFile = new File(dataPath("../.env"));
  }
  if (!envFile.exists()) {
    envFile = new File(".env");
  }

  if (envFile.exists()) {
    String[] lines = loadStrings(envFile);
    if (lines != null) {
      for (String line : lines) {
        line = trim(line);
        if (line.contains("MAPBOX_ACCESS_TOKEN=") ||
          line.contains("MAPBOX_TOKEN=") ||
          line.contains("MAPBOX_API_KEY=")) {
          int eqIdx = line.indexOf('=');
          mapboxToken = line.substring(eqIdx + 1).trim();
          if (mapboxToken.startsWith("\"") && mapboxToken.endsWith("\"")) {
            mapboxToken = mapboxToken.substring(1, mapboxToken.length() - 1);
          }
          if (mapboxToken.startsWith("'") && mapboxToken.endsWith("'")) {
            mapboxToken = mapboxToken.substring(1, mapboxToken.length() - 1);
          }
          println("✅ Successfully loaded MAPBOX_ACCESS_TOKEN from .env");
        }
      }
    }
  }

  if (mapboxToken.length() == 0) {
    println("ℹ️ Note: Set EXPO_PUBLIC_MAPBOX_ACCESS_TOKEN or MAPBOX_ACCESS_TOKEN in .env to stream live Mapbox tiles.");
  }
}

void initRoutes() {
  routes = new RouteData[] {
    // Route 1: Damrak to Amsterdam Centraal
    new RouteData(
    "Centrum Route", "Amsterdam Centraal Station", "RIGHT", "Damrak", 110, 1.4, 5, 17.5,
    new LatLon(52.3731, 4.8926), // Dam Square
    new LatLon(52.3791, 4.9003), // Centraal
    new LatLon[] {
      new LatLon(52.3731, 4.8926),
      new LatLon(52.3745, 4.8938),
      new LatLon(52.3762, 4.8960),
      new LatLon(52.3775, 4.8982),
      new LatLon(52.3791, 4.9003)
    }
    ),
    // Route 2: Roeterseiland to UvA Science Park
    new RouteData(
    "Science Park Commute", "UvA Science Park Campus", "LEFT", "Linnaeusstraat", 240, 3.8, 12, 19.8,
    new LatLon(52.3629, 4.9126), // UvA Roeterseiland
    new LatLon(52.3550, 4.9550), // Science Park
    new LatLon[] {
      new LatLon(52.3629, 4.9126),
      new LatLon(52.3615, 4.9205),
      new LatLon(52.3590, 4.9280),
      new LatLon(52.3565, 4.9400),
      new LatLon(52.3550, 4.9550)
    }
    ),
    // Route 3: Vondelpark to Rijksmuseum & De Pijp
    new RouteData(
    "Museum & De Pijp Route", "Sarphatipark / De Pijp", "STRAIGHT", "Stadhouderskade", 75, 2.1, 7, 16.2,
    new LatLon(52.3580, 4.8680), // Vondelpark
    new LatLon(52.3540, 4.8965), // Sarphatipark
    new LatLon[] {
      new LatLon(52.3580, 4.8680),
      new LatLon(52.3600, 4.8770),
      new LatLon(52.3599, 4.8852),
      new LatLon(52.3570, 4.8910),
      new LatLon(52.3540, 4.8965)
    }
    )
  };
}

void draw() {
  background(18, 22, 30);

  // Auto-connect / auto-reconnect to trackpad sensor if port changed
  checkSerialConnection();

  // Smoothly interpolate Zoom, Pitch (Tilt), and Route Line visibility
  currentZoom = lerp(currentZoom, targetZoom, smoothing);
  currentPitch = lerp(currentPitch, targetPitch, smoothing);
  routeLineAlpha = lerp(routeLineAlpha, targetRouteLineAlpha, smoothing);
  pulseAngle += 0.05;

  RouteData currentRoute = routes[currentRouteIdx];

  // -------------------------------------------------------------
  // 1. Render Map in 3D Perspective Space
  // -------------------------------------------------------------
  pushMatrix();

  // Focal center for biker perspective (lower third for forward perspective vista)
  float focalX = width * 0.5;
  float focalY = height * 0.72;

  translate(focalX, focalY, 0);
  rotateX(radians(currentPitch)); // 64 deg in Level 1, 0 deg in Level 2 & 3
  translate(-focalX, -focalY, 0);

  // A. Render Mapbox Tiles
  renderMapboxMap(currentRoute.currentPos.lat, currentRoute.currentPos.lon, currentZoom, focalX, focalY);

  // B. Render GPS Navigation Route Line if visible (Level 2 & 3)
  if (routeLineAlpha > 0.02) {
    renderRoutePath(currentRoute, currentRoute.currentPos.lat, currentRoute.currentPos.lon, currentZoom, focalX, focalY, routeLineAlpha);
  }

  // C. Render Biker GPS Beacon
  drawBikerLocation(focalX, focalY);

  popMatrix();

  // -------------------------------------------------------------
  // 2. Render 2D Screen HUD (Overlays)
  // -------------------------------------------------------------
  hint(DISABLE_DEPTH_TEST);

  // Turn-by-turn guidance card (Top-Left)
  drawTurnCard(currentRoute);

  // Telemetry Dashboard (Bottom)
  drawBottomTelemetry(currentRoute);

  // Live Trackpad Pressure & Level HUD (Top-Right)
  drawPressureHUD();

  // Touch notification banner
  if (touchNotificationTimer > 0) {
    drawTouchNotification();
    touchNotificationTimer--;
  }

  hint(ENABLE_DEPTH_TEST);
}

// -------------------------------------------------------------
// Mapbox Tile Renderer
// -------------------------------------------------------------
void renderMapboxMap(double centerLat, double centerLon, float zoomVal, float screenCenterX, float screenCenterY) {
  int baseZ = round(zoomVal);
  baseZ = constrain(baseZ, 12, 18);
  float zoomFraction = pow(2, zoomVal - baseZ);

  // Center coordinate in tile space
  double centerTileX = (centerLon + 180.0) / 360.0 * (1 << baseZ);
  double latRad = Math.toRadians(centerLat);
  double centerTileY = (1.0 - Math.log(Math.tan(latRad) + 1.0 / Math.cos(latRad)) / Math.PI) / 2.0 * (1 << baseZ);

  float tileSize = 256.0 * zoomFraction;

  // Calculate visible tile range (extra margin for steep 3D tilt)
  int minX = (int) Math.floor(centerTileX - (screenCenterX / tileSize) - 3);
  int maxX = (int) Math.ceil(centerTileX + ((width - screenCenterX) / tileSize) + 3);
  int minY = (int) Math.floor(centerTileY - (screenCenterY / tileSize) - 5);
  int maxY = (int) Math.ceil(centerTileY + ((height - screenCenterY) / tileSize) + 3);

  imageMode(CORNER);

  for (int tx = minX; tx <= maxX; tx++) {
    for (int ty = minY; ty <= maxY; ty++) {
      float screenX = (float) (screenCenterX + (tx - centerTileX) * tileSize);
      float screenY = (float) (screenCenterY + (ty - centerTileY) * tileSize);

      PImage tileImg = getTile(baseZ, tx, ty);
      if (tileImg != null) {
        image(tileImg, screenX, screenY, tileSize, tileSize);
      } else {
        // Dark placeholder
        fill(24, 28, 38);
        noStroke();
        rect(screenX, screenY, tileSize, tileSize);
        stroke(35, 42, 56);
        strokeWeight(1);
        noFill();
        rect(screenX, screenY, tileSize, tileSize);
      }
    }
  }

  // Mapbox Attribution watermark
  fill(0, 170);
  noStroke();
  rect(width - 150, height - 24, 140, 20, 6);
  fill(180, 200, 220);
  textSize(10);
  textAlign(RIGHT, CENTER);
  text("© Mapbox", width - 20, height - 14);
}

// Fetch or queue async load of a Mapbox tile
PImage getTile(int z, int x, int y) {
  String tileKey = "mb_" + mapboxStyle + "_" + z + "_" + x + "_" + y;

  // 1. Check memory cache
  synchronized (tileCache) {
    if (tileCache.containsKey(tileKey)) {
      return tileCache.get(tileKey);
    }
  }

  // 2. Check local disk cache in data/tiles/
  File f = new File(dataPath("tiles/" + tileKey + ".png"));
  if (f.exists()) {
    try {
      PImage img = loadImage(f.getPath());
      if (img != null && img.width > 0) {
        synchronized (tileCache) {
          tileCache.put(tileKey, img);
        }
        return img;
      }
    }
    catch (Exception e) {
      // ignore
    }
  }

  // 3. Queue for background download from Mapbox
  if (!requestedTiles.contains(tileKey)) {
    requestedTiles.add(tileKey);
    downloadQueue.add(z + "_" + x + "_" + y);
  }

  return null;
}

// Background thread worker for downloading missing Mapbox tiles
void tileDownloadWorker() {
  while (tileDownloaderRunning) {
    String tileCoord = downloadQueue.poll();
    if (tileCoord == null) {
      try {
        Thread.sleep(50);
      }
      catch (InterruptedException e) {
        // ignore
      }
      continue;
    }

    String[] parts = split(tileCoord, '_');
    if (parts.length != 3) continue;

    int z = int(parts[0]);
    int x = int(parts[1]);
    int y = int(parts[2]);

    String tileKey = "mb_" + mapboxStyle + "_" + z + "_" + x + "_" + y;

    if (mapboxToken == null || mapboxToken.length() == 0) {
      continue;
    }

    String tileUrl = "https://api.mapbox.com/styles/v1/mapbox/" + mapboxStyle + "/tiles/256/" + z + "/" + x + "/" + y + "?access_token=" + mapboxToken;

    try {
      URL url = new URL(tileUrl);
      URLConnection conn = url.openConnection();
      conn.setRequestProperty("User-Agent", "BikeNavigationApp/1.0");
      conn.setConnectTimeout(3000);
      conn.setReadTimeout(3000);

      InputStream in = conn.getInputStream();
      File tmpFile = new File(dataPath("tiles/" + tileKey + ".tmp"));
      File saveFile = new File(dataPath("tiles/" + tileKey + ".png"));
      tmpFile.getParentFile().mkdirs();

      FileOutputStream out = new FileOutputStream(tmpFile);
      byte[] buffer = new byte[4096];
      int bytesRead;
      while ((bytesRead = in.read(buffer)) != -1) {
        out.write(buffer, 0, bytesRead);
      }
      out.close();
      in.close();

      if (tmpFile.renameTo(saveFile)) {
        PImage img = loadImage(saveFile.getPath());
        if (img != null && img.width > 0) {
          synchronized (tileCache) {
            tileCache.put(tileKey, img);
          }
        }
      }
    }
    catch (Exception e) {
      // ignore network errors
    }
  }
}

// Draw dynamic GPS Route Line on top of Mapbox Map (with alpha fade)
void renderRoutePath(RouteData r, double centerLat, double centerLon, float zoomVal, float screenCenterX, float screenCenterY, float alphaVal) {
  int baseZ = round(zoomVal);
  float zoomFraction = pow(2, zoomVal - baseZ);
  float tileSize = 256.0 * zoomFraction;

  double centerTileX = (centerLon + 180.0) / 360.0 * (1 << baseZ);
  double latRad = Math.toRadians(centerLat);
  double centerTileY = (1.0 - Math.log(Math.tan(latRad) + 1.0 / Math.cos(latRad)) / Math.PI) / 2.0 * (1 << baseZ);

  int outerAlpha = int(120 * alphaVal);
  int coreAlpha = int(255 * alphaVal);

  // Outer glowing route outline
  noFill();
  stroke(0, 170, 255, outerAlpha);
  strokeWeight(10);
  beginShape();
  for (LatLon wp : r.waypoints) {
    double wx = (wp.lon + 180.0) / 360.0 * (1 << baseZ);
    double wLatRad = Math.toRadians(wp.lat);
    double wy = (1.0 - Math.log(Math.tan(wLatRad) + 1.0 / Math.cos(wLatRad)) / Math.PI) / 2.0 * (1 << baseZ);
    float sx = (float) (screenCenterX + (wx - centerTileX) * tileSize);
    float sy = (float) (screenCenterY + (wy - centerTileY) * tileSize);
    vertex(sx, sy);
  }
  endShape();

  // Core bright cyan bike route line
  stroke(0, 240, 255, coreAlpha);
  strokeWeight(5);
  beginShape();
  for (LatLon wp : r.waypoints) {
    double wx = (wp.lon + 180.0) / 360.0 * (1 << baseZ);
    double wLatRad = Math.toRadians(wp.lat);
    double wy = (1.0 - Math.log(Math.tan(wLatRad) + 1.0 / Math.cos(wLatRad)) / Math.PI) / 2.0 * (1 << baseZ);
    float sx = (float) (screenCenterX + (wx - centerTileX) * tileSize);
    float sy = (float) (screenCenterY + (wy - centerTileY) * tileSize);
    vertex(sx, sy);
  }
  endShape();

  // Destination Pin Marker
  LatLon dest = r.destPos;
  double dx = (dest.lon + 180.0) / 360.0 * (1 << baseZ);
  double dLatRad = Math.toRadians(dest.lat);
  double dy = (1.0 - Math.log(Math.tan(dLatRad) + 1.0 / Math.cos(dLatRad)) / Math.PI) / 2.0 * (1 << baseZ);
  float dsx = (float) (screenCenterX + (dx - centerTileX) * tileSize);
  float dsy = (float) (screenCenterY + (dy - centerTileY) * tileSize);

  // Destination Flag / Marker
  fill(255, 50, 80, coreAlpha);
  stroke(255, coreAlpha);
  strokeWeight(2);
  ellipse(dsx, dsy, 18, 18);
  fill(255, coreAlpha);
  noStroke();
  textSize(9);
  textAlign(CENTER, CENTER);
  text("🏁", dsx, dsy - 1);
}

// Biker pulsating GPS icon
void drawBikerLocation(float bx, float by) {
  // Pulsing outer radar ring
  float pulseSize = 34 + 18 * sin(pulseAngle);
  float pulseAlpha = map(sin(pulseAngle), -1, 1, 30, 180);

  noFill();
  stroke(0, 220, 255, pulseAlpha);
  strokeWeight(3);
  ellipse(bx, by, pulseSize, pulseSize);

  // Outer glowing halo
  fill(0, 200, 255, 50);
  noStroke();
  ellipse(bx, by, 38, 38);

  // Core circle
  fill(0, 140, 255);
  stroke(255);
  strokeWeight(3);
  ellipse(bx, by, 20, 20);

  // Direction arrow
  pushMatrix();
  translate(bx, by);
  fill(255);
  noStroke();
  triangle(-4, 3, 4, 3, 0, -6);
  popMatrix();
}

// Top turn-by-turn navigation card
void drawTurnCard(RouteData r) {
  pushMatrix();
  translate(40, 30);

  // Rounded glassmorphic banner
  fill(16, 22, 34, 235);
  stroke(40, 60, 85);
  strokeWeight(1.5);
  rect(0, 0, 500, 110, 16);

  // Turn Icon badge
  fill(0, 170, 255);
  noStroke();
  rect(16, 16, 78, 78, 12);

  // Turn Icon Symbol
  stroke(255);
  strokeWeight(4);
  noFill();
  if (r.nextTurn.equals("RIGHT")) {
    line(45, 70, 45, 45);
    line(45, 45, 68, 45);
    line(58, 35, 70, 45);
    line(58, 55, 70, 45);
  } else if (r.nextTurn.equals("LEFT")) {
    line(65, 70, 65, 45);
    line(65, 45, 42, 45);
    line(52, 35, 40, 45);
    line(52, 55, 40, 45);
  } else {
    line(55, 72, 55, 38);
    line(45, 48, 55, 38);
    line(65, 48, 55, 38);
  }

  // Text labels
  fill(255);
  noStroke();
  textAlign(LEFT, TOP);
  textSize(22);
  text("In " + r.turnDistanceM + " m", 110, 20);

  fill(140, 215, 255);
  textSize(16);
  text(r.nextTurn + " onto " + r.nextStreet, 110, 50);

  fill(130, 150, 175);
  textSize(12);
  text("🚲 MAPBOX BIKE NAVIGATION • " + r.destination, 110, 78);

  popMatrix();
}

// Bottom telemetry dashboard
void drawBottomTelemetry(RouteData r) {
  pushMatrix();
  translate(40, height - 95);

  fill(16, 22, 34, 235);
  stroke(40, 60, 85);
  strokeWeight(1.5);
  rect(0, 0, width - 80, 65, 14);

  // Speed
  fill(255);
  noStroke();
  textAlign(LEFT, CENTER);
  textSize(24);
  text(nf(r.speedKmH, 2, 1), 30, 32);
  fill(130, 160, 190);
  textSize(12);
  text("km/h", 95, 33);

  // Divider
  stroke(40, 60, 85);
  strokeWeight(1);
  line(145, 15, 145, 50);

  // Distance remaining
  noStroke();
  fill(255);
  textSize(20);
  text(nf(r.totalKm, 1, 1) + " km", 175, 32);
  fill(130, 160, 190);
  textSize(12);
  text("REMAINING", 175, 48);

  // Divider
  stroke(40, 60, 85);
  line(315, 15, 315, 50);

  // ETA
  noStroke();
  fill(0, 230, 160);
  textSize(20);
  text(r.etaMin + " min", 345, 32);
  fill(130, 160, 190);
  textSize(12);
  text("ETA", 345, 48);

  // Destination on the right
  textAlign(RIGHT, CENTER);
  fill(255);
  textSize(16);
  text("📍 " + r.destination, width - 120, 26);
  fill(100, 200, 255);
  textSize(12);
  text("Touch sensor to cycle routes", width - 120, 46);

  popMatrix();
}


// Touch notification banner
void drawTouchNotification() {
  pushMatrix();
  translate(width / 2 - 180, 160);

  fill(0, 170, 255, 235);
  stroke(255);
  strokeWeight(1.5);
  rect(0, 0, 360, 45, 12);

  fill(255);
  textAlign(CENTER, CENTER);
  textSize(14);
  text("⚡ Touch Detected: Switched Route!", 180, 22);

  popMatrix();
}

// -------------------------------------------------------------
// Serial communication & Zero-Lag Buffer Draining
// -------------------------------------------------------------
void serialEvent(Serial port) {
  while (port.available() > 0) {
    String message = port.readStringUntil('\n');
    if (message == null) break;
    message = trim(message);
    if (message.length() == 0) continue;

    lastSerialReceiveTime = millis();
    isSerialConnected = true;

    // Capacitive touch: cycle to next bike route (debounced >= 800ms)
    if (message.equals("TOUCH")) {
      if (millis() - lastTouchSwitchTime >= 800) {
        lastTouchSwitchTime = millis();
        println("⚡ Touch detected — switching bike route.");
        currentRouteIdx = (currentRouteIdx + 1) % routes.length;
        touchNotificationTimer = 60;
      }
      continue;
    }

    // Ignore startup ready message
    if (message.equals("READY")) continue;

    // FSR pressure reading
    try {
      int parsedVal = int(message);
      updateScaleFromFSR(parsedVal);
    }
    catch (Exception e) {
      // Ignore parse error
    }
  }
}

// -------------------------------------------------------------
// 3 Levels of Scale Mapping based on FSR pressure (0 - 1200g):
// Level 1: fsrRaw < 80   -> Deep Panned 3D View (64 deg pitch), z17.8, No route line
// Level 2: 80 <= fsrRaw < 400 -> Flat 2D View (0 deg pitch), z16.2 to z14.5, With route line
// Level 3: fsrRaw >= 400 -> Flat 2D View (0 deg pitch), z14.0 to z12.5 (City Overview), With route line
// -------------------------------------------------------------
void updateScaleFromFSR(int val) {
  fsrRaw = constrain(val, 0, 1200);

  if (fsrRaw < 80) {
    currentLevel = 1;
    targetZoom = 17.8;           // Deep close-up street zoom
    targetPitch = 64.0;          // Steep forward panned perspective
    targetRouteLineAlpha = 0.0;  // No route line (clean road view)
  } else if (fsrRaw < 400) {
    currentLevel = 2;
    targetPitch = 0.0;           // Flat top-down
    targetRouteLineAlpha = 1.0;  // With navigation line
    targetZoom = map(fsrRaw, 80, 400, 16.2, 14.5);
  } else {
    currentLevel = 3;
    targetPitch = 0.0;           // Flat top-down
    targetRouteLineAlpha = 1.0;  // With navigation line
    targetZoom = map(constrain(fsrRaw, 400, 1200), 400, 1200, 14.0, 12.5);
  }
}

// Interactive Keyboard Simulation Controls:
// - Spacebar: Switch bike route (simulating capacitive touch)
// - Keys '1', '2', '3': Jump directly to Level 1, 2, or 3
// - UP / DOWN Arrows: Incrementally increase / decrease pressure
void keyPressed() {
  if (key == ' ') {
    println("⚡ Spacebar: Switched route.");
    currentRouteIdx = (currentRouteIdx + 1) % routes.length;
    touchNotificationTimer = 60;
  } else if (key == '1') {
    println("⌨️ Simulated Level 1 (20g)");
    updateScaleFromFSR(20);
  } else if (key == '2') {
    println("⌨️ Simulated Level 2 (200g)");
    updateScaleFromFSR(200);
  } else if (key == '3') {
    println("⌨️ Simulated Level 3 (600g)");
    updateScaleFromFSR(600);
  } else if (keyCode == UP) {
    updateScaleFromFSR(min(1200, fsrRaw + 50));
    println("⌨️ Simulated Force: " + fsrRaw + "g");
  } else if (keyCode == DOWN) {
    updateScaleFromFSR(max(0, fsrRaw - 50));
    println("⌨️ Simulated Force: " + fsrRaw + "g");
  }
}

// -------------------------------------------------------------
// Live Trackpad Pressure & Scale Level HUD
// -------------------------------------------------------------
void drawPressureHUD() {
  pushMatrix();
  float hudW = 340;
  float hudH = 92;
  float hudX = width - hudW - 30;
  float hudY = 30;
  translate(hudX, hudY);

  // Rounded glassmorphic container
  fill(16, 22, 34, 235);
  stroke(40, 60, 85);
  strokeWeight(1.5);
  rect(0, 0, hudW, hudH, 16);

  // Connection status dot
  boolean connected = isSerialConnected && (millis() - lastSerialReceiveTime < 3500);
  if (connected) {
    fill(0, 230, 160); // Emerald green
  } else {
    fill(255, 170, 0); // Amber warning
  }
  noStroke();
  ellipse(20, 22, 10, 10);

  // Header Title
  fill(255);
  textAlign(LEFT, CENTER);
  textSize(13);
  text(connected ? "TRACKPAD FORCE SENSOR" : "WAITING FOR BRIDGE...", 34, 22);

  // Port label
  fill(130, 160, 190);
  textAlign(RIGHT, CENTER);
  textSize(11);
  String shortPort = activePort;
  if (shortPort.startsWith("/dev/")) shortPort = shortPort.substring(5);
  text(connected ? "● " + shortPort : "OFFLINE", hudW - 18, 22);

  // FSR Value or Prompt
  fill(180, 210, 240);
  textAlign(LEFT, CENTER);
  textSize(12);
  if (connected) {
    text("Force: " + fsrRaw + " / 1200g", 18, 46);
  } else {
    fill(255, 200, 100);
    text("Run ./trackpad_pressure in Terminal", 18, 46);
  }

  // Level Badge Pill
  String lvlStr = "LEVEL 1 • 3D STREET";
  int lvlColor = color(0, 170, 255);
  if (currentLevel == 2) {
    lvlStr = "LEVEL 2 • 2D ROUTE";
    lvlColor = color(0, 230, 160);
  } else if (currentLevel == 3) {
    lvlStr = "LEVEL 3 • CITY OVERVIEW";
    lvlColor = color(255, 100, 130);
  }

  fill(lvlColor, 40);
  stroke(lvlColor, 180);
  strokeWeight(1);
  rect(hudW - 165, 36, 147, 20, 8);

  fill(lvlColor);
  textAlign(CENTER, CENTER);
  textSize(9);
  text(lvlStr, hudW - 165 + 73, 45);

  // Force Meter Progress Bar
  float barX = 18;
  float barY = 66;
  float barW = hudW - 36;
  float barH = 10;

  // Background trough
  fill(25, 35, 50);
  noStroke();
  rect(barX, barY, barW, barH, 5);

  // Dynamic filled bar
  float fillPct = constrain(fsrRaw / 1200.0, 0.0, 1.0);
  if (fillPct > 0.01) {
    fill(lvlColor);
    rect(barX, barY, barW * fillPct, barH, 5);
  }

  popMatrix();
}

// -------------------------------------------------------------
// Auto-Reconnect to Trackpad Sensor Port
// -------------------------------------------------------------
void checkSerialConnection() {
  boolean recentlyActive = isSerialConnected && (millis() - lastSerialReceiveTime < 3500);
  if (arduino != null && recentlyActive) {
    return;
  }

  // Throttle check to every 1.5 seconds
  if (millis() - lastReconnectAttempt < 1500) {
    return;
  }
  lastReconnectAttempt = millis();

  File autoPortFile = new File("/tmp/trackpad_pressure_port.txt");
  if (autoPortFile.exists()) {
    String[] lines = loadStrings(autoPortFile);
    if (lines != null && lines.length > 0 && lines[0].trim().length() > 0) {
      String detectedPort = lines[0].trim();
      if (!detectedPort.equals(activePort) || arduino == null || !isSerialConnected) {
        try {
          if (arduino != null) {
            try { arduino.stop(); } catch (Exception ignored) {}
            arduino = null;
          }
          println("🔄 Connecting to trackpad sensor on: " + detectedPort);
          activePort = detectedPort;
          arduino = new Serial(this, detectedPort, 9600);
          arduino.bufferUntil('\n');
          delay(100);
          arduino.clear();
          isSerialConnected = true;
          lastSerialReceiveTime = millis();
        } catch (Exception e) {
          isSerialConnected = false;
        }
      }
    }
  } else {
    isSerialConnected = false;
  }
}
