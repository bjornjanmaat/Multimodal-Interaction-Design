/*
 * Arduino 6-LED Vote Partition Monitor (Man vs Machine)
 * 
 * Hardware Setup:
 * - Man Party (3 LEDs):
 *     LED 1 -> Pin 4  (through 220Ω resistor to GND)
 *     LED 2 -> Pin 5  (through 220Ω resistor to GND)
 *     LED 3 -> Pin 6  (through 220Ω resistor to GND)
 * 
 * - Machine Party (3 LEDs):
 *     LED 1 -> Pin 10 (through 220Ω resistor to GND)
 *     LED 2 -> Pin 11 (through 220Ω resistor to GND)
 *     LED 3 -> Pin 12 (through 220Ω resistor to GND)
 * 
 * Wiring Checklist:
 * 1. Anode (long leg of LED) -> Arduino Pin (4, 5, 6, 10, 11, or 12)
 * 2. Cathode (short leg of LED) -> 220Ω resistor -> Arduino GND rail
 * 3. Make sure the breadboard GND rail is connected back to one of the Arduino GND pins!
 * 4. If your LEDs turn on with LOW (common anode / connected to 5V), change ACTIVE_LOW to true below.
 */

// ---------------- Pins Configuration ----------------
const int MAN_PINS[] = {4, 5, 6};
const int MACHINE_PINS[] = {10, 11, 12};
const int LEDS_PER_PARTY = 3;

// Active logic: Set to false for standard GND wiring (HIGH=ON). Set to true if wired to 5V (LOW=ON).
bool activeLow = false;

#define PIN_ON  (activeLow ? LOW : HIGH)
#define PIN_OFF (activeLow ? HIGH : LOW)

// Optional Buzzer: Set to a dedicated pin (e.g. Pin 7), or -1 to disable
const int BUZZER_PIN = -1;

// Current state
int currentManLeds = 0;
int currentMachineLeds = 0;

// ---------------- LED Control Functions ----------------

void setManLeds(int count) {
  count = constrain(count, 0, LEDS_PER_PARTY);
  currentManLeds = count;
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MAN_PINS[i], (i < count) ? PIN_ON : PIN_OFF);
  }
}

void setMachineLeds(int count) {
  count = constrain(count, 0, LEDS_PER_PARTY);
  currentMachineLeds = count;
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MACHINE_PINS[i], (i < count) ? PIN_ON : PIN_OFF);
  }
}

void setPartyLeds(int manCount, int machineCount) {
  setManLeds(manCount);
  setMachineLeds(machineCount);
}

// ---------------- Diagnostic Self-Test ----------------

void runSelfTest() {
  Serial.println("--- Starting LED Diagnostic Test ---");
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    Serial.print("Testing Man Pin ");
    Serial.println(MAN_PINS[i]);
    digitalWrite(MAN_PINS[i], PIN_ON);
    delay(200);
    digitalWrite(MAN_PINS[i], PIN_OFF);
  }

  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    Serial.print("Testing Machine Pin ");
    Serial.println(MACHINE_PINS[i]);
    digitalWrite(MACHINE_PINS[i], PIN_ON);
    delay(200);
    digitalWrite(MACHINE_PINS[i], PIN_OFF);
  }

  // Flash all 6 together twice
  for (int f = 0; f < 2; f++) {
    setPartyLeds(3, 3);
    delay(200);
    setPartyLeds(0, 0);
    delay(100);
  }
  Serial.println("--- Diagnostic Test Complete ---");
}

// ---------------- Vote Partition Logic ----------------

void calculatePartition(int manVotes, int machineVotes, int &manLeds, int &machineLeds) {
  int total = manVotes + machineVotes;

  if (total <= 0) {
    manLeds = 0;
    machineLeds = 0;
    return;
  }

  // 100% Man
  if (machineVotes == 0) {
    manLeds = 3;
    machineLeds = 0;
    return;
  }

  // 100% Machine
  if (manVotes == 0) {
    manLeds = 0;
    machineLeds = 3;
    return;
  }

  // Only if both parties received the same votes: equal LEDs (2 and 2)
  if (manVotes == machineVotes) {
    manLeds = 2;
    machineLeds = 2;
    return;
  }
  // Party with more votes always shows more LEDs (at least +1 LED)
  if (manVotes > machineVotes) {
    if (manVotes >= 3 * machineVotes) {
      manLeds = 3;
      machineLeds = 1;
    } else {
      manLeds = 2;
      machineLeds = 1;
    }
  } else {
    if (machineVotes >= 3 * manVotes) {
      machineLeds = 3;
      manLeds = 1;
    } else {
      machineLeds = 2;
      manLeds = 1;
    }
  }
}

void updatePartition(int manVotes, int machineVotes) {
  int manLeds = 0;
  int machineLeds = 0;
  calculatePartition(manVotes, machineVotes, manLeds, machineLeds);
  setPartyLeds(manLeds, machineLeds);

  Serial.print("PARTITION: Man=");
  Serial.print(manLeds);
  Serial.print("/3, Machine=");
  Serial.print(machineLeds);
  Serial.println("/3");
}

// ---------------- Optional Sound / Feedback ----------------

void beep(int freq, int durationMs) {
  if (BUZZER_PIN <= 0) return;
  tone(BUZZER_PIN, freq, durationMs);
  digitalWrite(BUZZER_PIN, HIGH);
  delay(durationMs);
  noTone(BUZZER_PIN);
  digitalWrite(BUZZER_PIN, LOW);
}

void pulseNewVote(int count = 1) {
  if (count < 1) count = 1;
  
  for (int c = 0; c < count; c++) {
    if (BUZZER_PIN > 0) {
      beep(1200, 140);
    }

    // Brief visual pulse
    int savedMan = currentManLeds;
    int savedMachine = currentMachineLeds;
    setPartyLeds(0, 0);
    delay(60);
    setPartyLeds(savedMan, savedMachine);

    if (c < count - 1) {
      delay(120);
    }
  }
}

// ---------------- Arduino Setup ----------------

void setup() {
  Serial.begin(9600);

  // Initialize Man LED pins
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    pinMode(MAN_PINS[i], OUTPUT);
    digitalWrite(MAN_PINS[i], PIN_OFF);
  }

  // Initialize Machine LED pins
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    pinMode(MACHINE_PINS[i], OUTPUT);
    digitalWrite(MACHINE_PINS[i], PIN_OFF);
  }

  // Optional Buzzer pin
  if (BUZZER_PIN > 0) {
    pinMode(BUZZER_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);
    noTone(BUZZER_PIN);
  }

  // Startup visual diagnostic: tests each pin sequentially
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MAN_PINS[i], PIN_ON);
    delay(150);
    digitalWrite(MAN_PINS[i], PIN_OFF);
  }

  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MACHINE_PINS[i], PIN_ON);
    delay(150);
    digitalWrite(MACHINE_PINS[i], PIN_OFF);
  }

  // Flash all 6 LEDs together once
  setPartyLeds(3, 3);
  delay(250);
  setPartyLeds(0, 0);

  Serial.println("READY");
}

// ---------------- Arduino Loop ----------------

void loop() {
  if (Serial.available() > 0) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() == 0) return;

    // 1. Calculate partition from vote counts: "VOTES:man,machine" (e.g. "VOTES:5,3")
    if (msg.startsWith("VOTES:")) {
      int commaIdx = msg.indexOf(',');
      if (commaIdx != -1) {
        int manVotes = msg.substring(6, commaIdx).toInt();
        int machineVotes = msg.substring(commaIdx + 1).toInt();
        updatePartition(manVotes, machineVotes);
      }
    }
    // 2. Direct LED count: "LEDS:man,machine" (e.g. "LEDS:2,1")
    else if (msg.startsWith("LEDS:") || msg.startsWith("PARTITION:")) {
      int colonIdx = msg.indexOf(':');
      int commaIdx = msg.indexOf(',');
      if (commaIdx != -1) {
        int manLeds = msg.substring(colonIdx + 1, commaIdx).toInt();
        int machineLeds = msg.substring(commaIdx + 1).toInt();
        setPartyLeds(manLeds, machineLeds);
        Serial.print("LEDS_SET: Man=");
        Serial.print(manLeds);
        Serial.print(", Machine=");
        Serial.println(machineLeds);
      }
    }
    // 3. New vote event: "NEW_VOTE" or "NEW_VOTE:count"
    else if (msg.startsWith("NEW_VOTE")) {
      int count = 1;
      int colonIdx = msg.indexOf(':');
      if (colonIdx != -1) {
        count = msg.substring(colonIdx + 1).toInt();
      }
      pulseNewVote(count);
    }
    // 4. Test command to blink all pins: "TEST"
    else if (msg.equalsIgnoreCase("TEST")) {
      runSelfTest();
    }
    // 5. Invert active logic toggle: "INVERT"
    else if (msg.equalsIgnoreCase("INVERT")) {
      activeLow = !activeLow;
      Serial.print("LOGIC: Active-");
      Serial.println(activeLow ? "LOW (5V Common)" : "HIGH (GND Common)");
      setPartyLeds(currentManLeds, currentMachineLeds);
    }
    // 6. Turn ALL LEDs ON: "ALL_ON"
    else if (msg.equalsIgnoreCase("ALL_ON")) {
      setPartyLeds(3, 3);
      Serial.println("ALL_ON: All 6 LEDs turned ON");
    }
    // 7. Turn ALL LEDs OFF: "ALL_OFF" or "RESET"
    else if (msg.equalsIgnoreCase("ALL_OFF") || msg.equalsIgnoreCase("RESET") || msg.equalsIgnoreCase("CLEAR")) {
      setPartyLeds(0, 0);
      Serial.println("ALL_OFF: All 6 LEDs turned OFF");
    }
  }
}
