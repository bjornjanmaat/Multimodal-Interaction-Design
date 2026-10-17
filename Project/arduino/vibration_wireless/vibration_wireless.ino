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

  // Initialize the Motor Carrier controller
  if (!controller.begin()) {
    Serial.println("Failed to connect to Motor Carrier!");
    while (1);
  }

  // Connect to Wi-Fi
  while (WiFi.begin(ssid, pass) != WL_CONNECTED) {
    delay(1000);
    Serial.println("Connecting to WiFi...");
  }
  Serial.println("WiFi connected!");
  Serial.println(WiFi.localIP());

  Udp.begin(localPort);
}

void loop() {
  controller.ping(); // Keep carrier connection alive

  int packetSize = Udp.parsePacket();
  if (packetSize) {
    int len = Udp.read(packetBuffer, 255);
    packetBuffer[len] = 0;
    
    int intensity = atoi(packetBuffer); // 0 to 255
    // Map 0-255 to percentage duty cycle (-100 to 100 for M1)
    int duty = map(intensity, 0, 255, 0, 100);

    M1.setDuty(duty);
  }
}
