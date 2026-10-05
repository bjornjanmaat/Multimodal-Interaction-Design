const int SEARCH_LED = 13;  // Blinks while searching
const int MATCH_LED  = 12;  // On when match confirmed

bool searching = true;
unsigned long previousMillis = 0;
const long blinkInterval = 500;  // Blink every 500ms
bool ledState = false;

void setup() {
  Serial.begin(9600);
  pinMode(SEARCH_LED, OUTPUT);
  pinMode(MATCH_LED, OUTPUT);

  digitalWrite(SEARCH_LED, LOW);
  digitalWrite(MATCH_LED, LOW);
}

void loop() {
  // Check for messages from Processing.
  if (Serial.available() > 0) {
    String message = Serial.readStringUntil('\n');
    message.trim();

    if (message == "SEARCHING") {
      searching = true;
      digitalWrite(MATCH_LED, LOW);
    }

    if (message == "MATCH") {
      searching = false;
      digitalWrite(SEARCH_LED, LOW);
      digitalWrite(MATCH_LED, HIGH);
    }
  }

  // Handle blinking without using delay().
  if (searching) {
    unsigned long currentMillis = millis();

    if (currentMillis - previousMillis >= blinkInterval) {
      previousMillis = currentMillis;
      ledState = !ledState;
      digitalWrite(SEARCH_LED, ledState);
    }
  }
}