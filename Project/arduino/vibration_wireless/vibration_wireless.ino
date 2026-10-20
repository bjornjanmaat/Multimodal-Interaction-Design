#include <ArduinoMotorCarrier.h>
#include <WiFiNINA.h>
#include <WiFiUdp.h>

char ssid[] = "A52 van B";
char pass[] = "rvir1471";
unsigned int localPort = 5005;

WiFiUDP Udp;
char packetBuffer[255];

void setup() {
  Serial.begin(115200);

  // Wait up to 3 seconds for Serial Monitor; continue anyway if on battery
  unsigned long startWait = millis();
  while (!Serial && (millis() - startWait < 3000)) {
    ;
  }
  delay(500);

  // Initialize the Motor Carrier controller
  if (!controller.begin()) {
    while (1); // Trap if carrier logic fails
  }

  // Check for the WiFi module
  if (WiFi.status() == WL_NO_MODULE) {
    while (1);
  }

  // Connect to Wi-Fi
  while (WiFi.begin(ssid, pass) != WL_CONNECTED) {
    delay(2000);
  }

  Udp.begin(localPort);
}

void loop() {
  controller.ping(); // Keep carrier connection alive

  int packetSize = Udp.parsePacket();
  if (packetSize) {
    int len = Udp.read(packetBuffer, 254);
    packetBuffer[len] = '\0';
    
    int intensity = atoi(packetBuffer);
    int duty = map(intensity, 0, 255, 0, 100);

    M1.setDuty(duty);
  }
}
