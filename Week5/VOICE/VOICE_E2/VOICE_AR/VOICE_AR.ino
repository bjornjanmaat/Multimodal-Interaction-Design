const int LED_PIN = 13;

void setup() {
  Serial.begin(9600);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
}

void loop() {
  if (Serial.available() > 0) {
    String message = Serial.readStringUntil('\n');
    message.trim();

    if (message == "ON") {
      digitalWrite(LED_PIN, HIGH);
    }

    if (message == "OFF") {
      digitalWrite(LED_PIN, LOW);
    }
  }
}