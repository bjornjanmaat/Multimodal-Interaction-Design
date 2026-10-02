/*
 * Arduino 5-LED & Piezo Buzzer Live Rating Monitor
 * 
 * Hardware:
 * - LEDs: 
 *     Light 1 -> Pin 2 (through 220Ω resistor to GND)
 *     Light 2 -> Pin 3 (through 220Ω resistor to GND)
 *     Light 3 -> Pin 4 (through 220Ω resistor to GND)
 *     Light 4 -> Pin 5 (through 220Ω resistor to GND)
 *     Light 5 -> Pin 6 (through 220Ω resistor to GND)
 * - Buzzer: Pin 13 (positive leg to Pin 13, negative leg to GND)
 *   (Tip: If Pin 13 is too quiet due to the onboard LED, you can move it to Pin 11)
 * 
 * Behavior:
 * 1. Startup Diagnostic: Lights up each LED 1-by-1 (Pins 2 to 6) and beeps buzzer
 *    so you can instantly verify all 5 LEDs and the buzzer are working.
 * 2. Real-time LED Level: LEDs (Pins 2 to 6) stay ON showing the rounded average rating.
 * 3. New Vote: Plays a high beep when a new vote arrives.
 * 4. Average UP: Plays a high-pitch ascending alert.
 * 5. Average DOWN: Plays a low-pitch descending alert.
 */

const int LED_PINS[] = {2, 3, 4, 5, 6};
const int NUM_LEDS = 5;

// Change to 11 if Pin 13 onboard LED interferes with buzzer volume
const int BUZZER_PIN = 13;

int currentLevel = 0;

void setLeds(int count) {
  if (count < 0) count = 0;
  if (count > NUM_LEDS) count = NUM_LEDS;
  currentLevel = count;

  for (int i = 0; i < NUM_LEDS; i++) {
    if (i < count) {
      digitalWrite(LED_PINS[i], HIGH);
    } else {
      digitalWrite(LED_PINS[i], LOW);
    }
  }
}

// Sound generator (compatible with both passive and active buzzers)
void beep(int freq, int durationMs) {
  tone(BUZZER_PIN, freq, durationMs);
  // Fallback for active buzzers that require DC HIGH
  digitalWrite(BUZZER_PIN, HIGH);
  delay(durationMs);
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
}

// 1. High beep when new vote(s) are submitted (beeps 'count' times)
void playNewVoteBeep(int count = 1) {
  if (count < 1) count = 1;
  for (int i = 0; i < count; i++) {
    beep(1200, 160);
    if (i < count - 1) {
      delay(90); // Short pause between consecutive beeps
    }
  }
}

// 2. High-pitch chime when average goes UP
void playAvgUpBeep() {
  beep(1400, 110);
  delay(50);
  beep(1850, 160);
}

// 3. Low-pitch chime when average goes DOWN
void playAvgDownBeep() {
  beep(400, 140);
  delay(50);
  beep(250, 200);
}

void setup() {
  Serial.begin(9600);

  // Initialize LED pins as OUTPUT
  for (int i = 0; i < NUM_LEDS; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    digitalWrite(LED_PINS[i], LOW);
  }

  // Initialize Buzzer pin as OUTPUT
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  noTone(BUZZER_PIN);

  // -------------------------------------------------------------
  // STARTUP SELF-TEST DIAGNOSTIC:
  // Tests each LED sequentially so you can see if all 5 are wired correctly!
  // -------------------------------------------------------------
  for (int i = 0; i < NUM_LEDS; i++) {
    digitalWrite(LED_PINS[i], HIGH);
    beep(800 + (i * 250), 100);
    delay(150);
    digitalWrite(LED_PINS[i], LOW);
    delay(50);
  }

  // Flash all 5 LEDs together once
  setLeds(5);
  delay(200);
  setLeds(0);

  Serial.println("READY");
}

void loop() {
  if (Serial.available() > 0) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() == 0) return;

    if (msg.startsWith("NEW_VOTE")) {
      int count = 1;
      int colonIdx = msg.indexOf(':');
      if (colonIdx != -1) {
        count = msg.substring(colonIdx + 1).toInt();
      }
      playNewVoteBeep(max(1, count));
    } 
    else if (msg.equalsIgnoreCase("AVG_UP")) {
      playAvgUpBeep();
    } 
    else if (msg.equalsIgnoreCase("AVG_DOWN")) {
      playAvgDownBeep();
    } 
    else if (msg.startsWith("LEVEL:")) {
      int count = msg.substring(6).toInt();
      setLeds(count);
    } 
    else {
      // Raw integer level fallback
      float val = msg.toFloat();
      setLeds(round(val));
    }
  }
}
