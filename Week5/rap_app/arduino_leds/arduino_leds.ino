/*
 * Arduino 5-LED & Piezo Buzzer Rating Display (Switch-Triggered)
 * 
 * Hardware Connections:
 * - LEDs: Pins 2, 3, 4, 5, 6 (with resistors to GND)
 * - Switch: Pin 12 to GND (uses internal INPUT_PULLUP)
 * - Piezo Buzzer: Pin 13 to GND
 * 
 * Behavior:
 * 1. Flip switch ON (Pin 12 -> LOW) -> sends "FETCH" to Python over Serial.
 * 2. Python gets average score from Supabase and sends score back (e.g. "4\n").
 * 3. Arduino triggers LEDs gradually one-by-one, playing an ascending pitch
 *    on the Pin 13 buzzer for each step (C5, E5, G5, A5, C6).
 * 4. Flip switch OFF -> LEDs sweep off and buzzer silences.
 */

const int LED_PINS[] = {2, 3, 4, 5, 6};
const int NUM_LEDS = 5;
const int SWITCH_PIN = 12;
const int BUZZER_PIN = 13;

// Ascending musical pitches for ratings 1 through 5 (C5, E5, G5, A5, C6)
const int PITCHES[] = {523, 659, 784, 880, 1046};

// LOW when switch connects Pin 12 to GND (INPUT_PULLUP)
const int SWITCH_ACTIVE_STATE = LOW;

int lastReading = HIGH;
int currentSwitchState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long debounceDelay = 50;

void setup() {
  Serial.begin(9600);

  // Initialize LED pins
  for (int i = 0; i < NUM_LEDS; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], LOW);
  }

  // Initialize Buzzer
  pinMode(BUZZER_PIN, OUTPUT);
  noTone(BUZZER_PIN);

  // Initialize Pin 12 switch with internal pullup
  pinMode(SWITCH_PIN, INPUT_PULLUP);
  lastReading = digitalRead(SWITCH_PIN);
  currentSwitchState = lastReading;

  // Startup quick chime & light test
  for (int i = 0; i < NUM_LEDS; i++) {
    digitalWrite(LED_PINS[i], HIGH);
    tone(BUZZER_PIN, PITCHES[i], 60);
    delay(80);
    digitalWrite(LED_PINS[i], LOW);
  }
  noTone(BUZZER_PIN);

  Serial.println("READY");
}

// Gradually trigger LEDs and buzzer pitches up to targetCount
void showRatingGradually(int targetCount) {
  if (targetCount < 0) targetCount = 0;
  if (targetCount > NUM_LEDS) targetCount = NUM_LEDS;

  // First turn off any existing LEDs
  for (int i = 0; i < NUM_LEDS; i++) {
    digitalWrite(LED_PINS[i], LOW);
  }
  noTone(BUZZER_PIN);
  delay(100);

  if (targetCount == 0) {
    // Low tone indicating zero / no ratings
    tone(BUZZER_PIN, 220, 150);
    delay(150);
    noTone(BUZZER_PIN);
    return;
  }

  // Light LEDs gradually one by one with ascending pitch
  for (int i = 0; i < targetCount; i++) {
    digitalWrite(LED_PINS[i], HIGH);
    tone(BUZZER_PIN, PITCHES[i], 120); // 120ms pitch
    delay(160); // 160ms step timing for gradual build-up
  }

  noTone(BUZZER_PIN);
}

// Turn off LEDs in a quick reverse cascade
void turnOffLeds() {
  noTone(BUZZER_PIN);
  for (int i = NUM_LEDS - 1; i >= 0; i--) {
    digitalWrite(LED_PINS[i], LOW);
    delay(35);
  }
}

void loop() {
  // 1. Read switch on Pin 12 with debounce
  int reading = digitalRead(SWITCH_PIN);

  if (reading != lastReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != currentSwitchState) {
      currentSwitchState = reading;

      if (currentSwitchState == SWITCH_ACTIVE_STATE) {
        // Switch toggled ON: request score from Python
        Serial.println("FETCH");
      } else {
        // Switch toggled OFF: turn off display
        turnOffLeds();
        Serial.println("OFF");
      }
    }
  }
  lastReading = reading;

  // 2. Read score command from Python over Serial
  if (Serial.available() > 0) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() == 0) return;

    if (msg.equalsIgnoreCase("OFF") || msg == "0") {
      turnOffLeds();
    } else {
      float val = msg.toFloat();
      int roundedCount = round(val);
      showRatingGradually(roundedCount);
    }
  }
}
