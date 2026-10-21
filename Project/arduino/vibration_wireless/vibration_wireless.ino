#include <ArduinoMotorCarrier.h>
#include <WiFiNINA.h>
#include <WiFiUdp.h>

char ssid[] = "A52 van B";
char pass[] = "rvir1471";
unsigned int localPort = 5005;

WiFiUDP Udp;
char packetBuffer[255];

// Map 0-255 intensity to 0-100 duty cycle for the motor carrier
int intensityToDuty(int intensity) {
  if (intensity <= 0) return 0;
  if (intensity >= 255) return 100;
  return map(intensity, 0, 255, 0, 100);
}

// Set duty cycle (0-100) for a specific motor (1=M1, 2=M2, 3=M3, 4=M4)
void setMotorDuty(int motorNum, int duty) {
  duty = constrain(duty, 0, 100);
  switch (motorNum) {
    case 1: M1.setDuty(duty); break;
    case 2: M2.setDuty(duty); break;
    case 3: M3.setDuty(duty); break;
    case 4: M4.setDuty(duty); break;
  }
}

// Set all 4 motors to the same duty cycle
void setAllMotorsDuty(int duty) {
  duty = constrain(duty, 0, 100);
  M1.setDuty(duty);
  M2.setDuty(duty);
  M3.setDuty(duty);
  M4.setDuty(duty);
}

void setup() {
  Serial.begin(115200);

  // Wait up to 3 seconds for Serial Monitor; continue anyway if on battery
  unsigned long startWait = millis();
  while (!Serial && (millis() - startWait < 3000)) {
    ;
  }
  delay(500);

  Serial.println("Initializing Arduino MKR Motor Carrier...");

  // Initialize the Motor Carrier controller
  if (!controller.begin()) {
    Serial.println("ERROR: Motor Carrier initialization failed!");
    while (1); // Trap if carrier logic fails
  }

  // Ensure all motors start stopped
  setAllMotorsDuty(0);

  // Check for the WiFi module
  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("ERROR: Communication with WiFi module failed!");
    while (1);
  }

  Serial.print("Connecting to WiFi network: ");
  Serial.println(ssid);

  // Connect to Wi-Fi
  while (WiFi.begin(ssid, pass) != WL_CONNECTED) {
    delay(2000);
    Serial.print(".");
  }

  Serial.println("\nWiFi connected successfully!");
  Serial.print("Arduino IP address: ");
  Serial.println(WiFi.localIP());

  Udp.begin(localPort);
  Serial.print("Listening for UDP commands on port: ");
  Serial.println(localPort);
  Serial.println("Ready to drive M1, M2, M3, M4!");
}

void loop() {
  controller.ping(); // Keep carrier connection alive

  int packetSize = Udp.parsePacket();
  if (packetSize) {
    int len = Udp.read(packetBuffer, sizeof(packetBuffer) - 1);
    packetBuffer[len] = '\0';

    // Trim leading whitespace
    char* str = packetBuffer;
    while (*str == ' ' || *str == '\t' || *str == '\r' || *str == '\n') {
      str++;
    }

    // Command 1: Specific motor targeting, e.g. "M1:255", "M2:150", "m3=200", "M4 255"
    if ((str[0] == 'M' || str[0] == 'm') && str[1] >= '1' && str[1] <= '4') {
      int motorNum = str[1] - '0';
      char* sep = strpbrk(str + 2, ":=, ");
      if (sep) {
        int intensity = atoi(sep + 1);
        int duty = intensityToDuty(intensity);
        setMotorDuty(motorNum, duty);
        Serial.print("Motor M");
        Serial.print(motorNum);
        Serial.print(" set to duty: ");
        Serial.println(duty);
      }
    }
    // Command 2: Explicit ALL command, e.g. "ALL:200" or "ALL 255"
    else if (strncasecmp(str, "ALL", 3) == 0) {
      char* sep = strpbrk(str + 3, ":=, ");
      int intensity = sep ? atoi(sep + 1) : 0;
      int duty = intensityToDuty(intensity);
      setAllMotorsDuty(duty);
      Serial.print("All motors set to duty: ");
      Serial.println(duty);
    }
    // Command 3: Comma-separated list for all 4 motors, e.g. "255,100,50,0"
    else if (strchr(str, ',') != NULL) {
      int vals[4] = {0, 0, 0, 0};
      int count = 0;
      char* token = strtok(str, ",");
      while (token != NULL && count < 4) {
        vals[count++] = atoi(token);
        token = strtok(NULL, ",");
      }
      if (count >= 1) setMotorDuty(1, intensityToDuty(vals[0]));
      if (count >= 2) setMotorDuty(2, intensityToDuty(vals[1]));
      if (count >= 3) setMotorDuty(3, intensityToDuty(vals[2]));
      if (count >= 4) setMotorDuty(4, intensityToDuty(vals[3]));
      Serial.print("CSV updated motors [M1-M4]: ");
      Serial.print(intensityToDuty(vals[0])); Serial.print(", ");
      Serial.print(intensityToDuty(vals[1])); Serial.print(", ");
      Serial.print(intensityToDuty(vals[2])); Serial.print(", ");
      Serial.println(intensityToDuty(vals[3]));
    }
    // Command 4: Single integer, e.g. "255" or "0" -> controls ALL motors (backward compatible)
    else {
      int intensity = atoi(str);
      int duty = intensityToDuty(intensity);
      setAllMotorsDuty(duty);
      Serial.print("All motors set to duty: ");
      Serial.println(duty);
    }
  }
}
