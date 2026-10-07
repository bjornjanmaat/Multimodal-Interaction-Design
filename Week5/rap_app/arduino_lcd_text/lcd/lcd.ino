#include <LiquidCrystal_I2C.h>
#include <Wire.h>

// Set the LCD address (0x26, 0x27, or 0x3F) for a 20-column, 4-line display
LiquidCrystal_I2C lcd(0x26, 20, 4);

// Button / Switch Pins (Internal Pull-Up: Connect button/switch to GND)
const int MIC_SWITCH_PIN = 7;   // Pin 7: Mic toggle switch (ON/OFF)
const int START_BUTTON_PIN = 9; // Pin 9: Battle Start button

// Mic switch debounce state
int lastMicReading = HIGH;
int micState = HIGH;
unsigned long lastMicDebounce = 0;

// Start button debounce state
int lastStartReading = HIGH;
int startButtonState = HIGH;
unsigned long lastStartDebounce = 0;

const unsigned long DEBOUNCE_DELAY = 50;

// ---------------- LED Vote Partition Configuration ----------------
// Man Party: Pins 4, 5, 6
// Machine (Grok) Party: Pins 10, 11, 12
const int MAN_PINS[] = {4, 5, 6};
const int MACHINE_PINS[] = {10, 11, 12};
const int LEDS_PER_PARTY = 3;

int currentManLeds = 0;
int currentMachineLeds = 0;

void setManLeds(int count) {
  count = constrain(count, 0, LEDS_PER_PARTY);
  currentManLeds = count;
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MAN_PINS[i], (i < count) ? HIGH : LOW);
  }
}

void setMachineLeds(int count) {
  count = constrain(count, 0, LEDS_PER_PARTY);
  currentMachineLeds = count;
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    digitalWrite(MACHINE_PINS[i], (i < count) ? HIGH : LOW);
  }
}

void setPartyLeds(int manCount, int machineCount) {
  setManLeds(manCount);
  setMachineLeds(machineCount);
}

void calculatePartition(int manVotes, int machineVotes, int &manLeds, int &machineLeds) {
  int total = manVotes + machineVotes;
  if (total <= 0) {
    manLeds = 0;
    machineLeds = 0;
    return;
  }
  if (machineVotes == 0) {
    manLeds = 3;
    machineLeds = 0;
    return;
  }
  if (manVotes == 0) {
    manLeds = 0;
    machineLeds = 3;
    return;
  }
  float manShare = (float)manVotes / (float)total;
  float machineShare = (float)machineVotes / (float)total;
  manLeds = round(manShare * 3.0);
  machineLeds = round(machineShare * 3.0);
  if (manVotes > 0 && manLeds < 1) manLeds = 1;
  if (machineVotes > 0 && machineLeds < 1) machineLeds = 1;
  manLeds = constrain(manLeds, 0, 3);
  machineLeds = constrain(machineLeds, 0, 3);
}

void updatePartition(int manVotes, int machineVotes) {
  int manLeds = 0;
  int machineLeds = 0;
  calculatePartition(manVotes, machineVotes, manLeds, machineLeds);
  setPartyLeds(manLeds, machineLeds);
  Serial.print("LEDS_PARTITION: Man=");
  Serial.print(manLeds);
  Serial.print("/3, Machine=");
  Serial.print(machineLeds);
  Serial.println("/3");
}

void pulseNewVote(int count = 1) {
  if (count < 1) count = 1;
  for (int c = 0; c < count; c++) {
    int savedMan = currentManLeds;
    int savedMachine = currentMachineLeds;
    setPartyLeds(0, 0);
    delay(70);
    setPartyLeds(savedMan, savedMachine);
    if (c < count - 1) delay(100);
  }
}

// Helper function to write a full 20-char line, padding remaining characters
// with spaces
void writeRow(int row, String text) {
  if (row < 0 || row >= 4)
    return;
  lcd.setCursor(0, row);
  int len = text.length();
  for (int i = 0; i < 20; i++) {
    if (i < len) {
      lcd.print(text[i]);
    } else {
      lcd.print(" ");
    }
  }
}

// Clear all 4 rows
void clearAll() {
  for (int r = 0; r < 4; r++) {
    writeRow(r, "");
  }
}

// Maximum number of wrapped lines to store for scrolling
const int MAX_LINES = 50;
String lines[MAX_LINES];
int totalLines = 0;
int currentScrollLine = 0;
unsigned long lastScrollTime = 0;
const unsigned long SCROLL_INTERVAL =
    1800; // Time each 4-line view is shown (ms)
bool isScrolling = false;

// Render 4 lines starting from startIdx
void renderWindow(int startIdx) {
  for (int r = 0; r < 4; r++) {
    int lineIdx = startIdx + r;
    if (lineIdx < totalLines) {
      writeRow(r, lines[lineIdx]);
    } else {
      writeRow(r, "");
    }
  }
}

// Word-wrap any incoming text into lines of up to 20 characters and start scrolling
void setText(String text) {
  totalLines = 0;
  currentScrollLine = 0;
  text.trim();

  int textLen = text.length();
  int charIdx = 0;

  while (charIdx < textLen && totalLines < MAX_LINES) {
    // Check if there is an explicit newline delimiter '|'
    int nextPipe = text.indexOf('|', charIdx);
    int segEnd = (nextPipe != -1) ? nextPipe : textLen;
    String segment = text.substring(charIdx, segEnd);
    segment.trim();

    if (segment.length() == 0) {
      charIdx = segEnd + 1;
      continue; // Skip empty segments to avoid blank lines
    }

    int segLen = segment.length();
    int segIdx = 0;

    // Word wrap this segment into lines of up to 20 chars
    while (segIdx < segLen && totalLines < MAX_LINES) {
      int remaining = segLen - segIdx;
      if (remaining <= 20) {
        String lastLine = segment.substring(segIdx);
        lastLine.trim();
        if (lastLine.length() > 0) {
          lines[totalLines++] = lastLine;
        }
        break;
      } else {
        int splitPos = 20;
        int lastSpace = -1;
        for (int i = 0; i < 20; i++) {
          if (segment.charAt(segIdx + i) == ' ') {
            lastSpace = i;
          }
        }
        if (lastSpace > 0) {
          splitPos = lastSpace;
        }

        String rowText = segment.substring(segIdx, segIdx + splitPos);
        rowText.trim();
        if (rowText.length() > 0) {
          lines[totalLines++] = rowText;
        }

        segIdx += splitPos;
        while (segIdx < segLen && segment.charAt(segIdx) == ' ') {
          segIdx++;
        }
      }
    }

    charIdx = segEnd + 1;
  }

  isScrolling = (totalLines > 4);
  renderWindow(0);
  lastScrollTime = millis();
}

void setup() {
  Serial.begin(9600);

  // Use internal pullup resistors: LOW when connected to GND, HIGH when open
  pinMode(MIC_SWITCH_PIN, INPUT_PULLUP);
  pinMode(START_BUTTON_PIN, INPUT_PULLUP);

  // Initialize LED output pins (Man: 4, 5, 6 | Machine: 10, 11, 12)
  for (int i = 0; i < LEDS_PER_PARTY; i++) {
    pinMode(MAN_PINS[i], OUTPUT);
    digitalWrite(MAN_PINS[i], LOW);
    pinMode(MACHINE_PINS[i], OUTPUT);
    digitalWrite(MACHINE_PINS[i], LOW);
  }

  lcd.init();      // Initialize the LCD
  lcd.backlight(); // Turn on backlight

  // Initial welcome screen
  setText("Are you ready to battle!?");

  Serial.println("LCD_READY");

  // Broadcast initial mic switch state
  int initialMic = digitalRead(MIC_SWITCH_PIN);
  micState = initialMic;
  lastMicReading = initialMic;
  if (micState == LOW) {
    Serial.println("MIC:ON");
    Serial.println("BTN:ON"); // legacy compatibility
  } else {
    Serial.println("MIC:OFF");
    Serial.println("BTN:OFF"); // legacy compatibility
  }
}

void loop() {
  unsigned long now = millis();

  // 1. Read and debounce Mic Switch (Pin 7)
  int micRead = digitalRead(MIC_SWITCH_PIN);
  if (micRead != lastMicReading) {
    lastMicDebounce = now;
  }
  lastMicReading = micRead;
  if ((now - lastMicDebounce) > DEBOUNCE_DELAY) {
    if (micRead != micState) {
      micState = micRead;
      if (micState == LOW) {
        Serial.println("MIC:ON");
        Serial.println("BTN:ON");
      } else {
        Serial.println("MIC:OFF");
        Serial.println("BTN:OFF");
      }
    }
  }

  // 2. Read and debounce Start Button (Pin 9)
  int startRead = digitalRead(START_BUTTON_PIN);
  if (startRead != lastStartReading) {
    lastStartDebounce = now;
  }
  lastStartReading = startRead;
  if ((now - lastStartDebounce) > DEBOUNCE_DELAY) {
    if (startRead != startButtonState) {
      startButtonState = startRead;
      if (startButtonState == LOW) {
        // Triggered upon pressing down
        Serial.println("START_BTN:PRESSED");
      }
    }
  }

  // Handle serial input non-blockingly
  if (Serial.available() > 0) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() > 0) {
      if (msg.equalsIgnoreCase("CLEAR")) {
        isScrolling = false;
        totalLines = 0;
        clearAll();
        Serial.println("ACK:CLEARED");
      } else if (msg.equalsIgnoreCase("STATUS")) {
        if (micState == LOW) {
          Serial.println("MIC:ON");
          Serial.println("BTN:ON");
        } else {
          Serial.println("MIC:OFF");
          Serial.println("BTN:OFF");
        }
      } else if (msg.startsWith("LINE:")) {
        // Format: LINE:<row>:<text>
        isScrolling = false;
        int firstColon = msg.indexOf(':');
        int secondColon = msg.indexOf(':', firstColon + 1);
        if (secondColon != -1) {
          int row = msg.substring(firstColon + 1, secondColon).toInt();
          String content = msg.substring(secondColon + 1);
          writeRow(row, content);
          Serial.println("ACK:ROW_" + String(row));
        }
      } else if (msg.startsWith("TEXT:")) {
        setText(msg.substring(5));
        Serial.println("ACK:TEXT_UPDATED");
      } else if (msg.startsWith("VOTES:")) {
        int commaIdx = msg.indexOf(',');
        if (commaIdx != -1) {
          int manVotes = msg.substring(6, commaIdx).toInt();
          int machineVotes = msg.substring(commaIdx + 1).toInt();
          updatePartition(manVotes, machineVotes);
          Serial.println("ACK:VOTES_SET");
        }
      } else if (msg.startsWith("LEDS:") || msg.startsWith("PARTITION:")) {
        int colonIdx = msg.indexOf(':');
        int commaIdx = msg.indexOf(',');
        if (commaIdx != -1) {
          int manLeds = msg.substring(colonIdx + 1, commaIdx).toInt();
          int machineLeds = msg.substring(commaIdx + 1).toInt();
          setPartyLeds(manLeds, machineLeds);
          Serial.println("ACK:LEDS_SET");
        }
      } else if (msg.startsWith("NEW_VOTE")) {
        int count = 1;
        int colonIdx = msg.indexOf(':');
        if (colonIdx != -1) {
          count = msg.substring(colonIdx + 1).toInt();
        }
        pulseNewVote(count);
        Serial.println("ACK:NEW_VOTE_PULSED");
      } else if (msg.equalsIgnoreCase("ALL_OFF") || msg.equalsIgnoreCase("LEDS_OFF")) {
        setPartyLeds(0, 0);
        Serial.println("ACK:LEDS_OFF");
      } else if (msg.equalsIgnoreCase("ALL_ON") || msg.equalsIgnoreCase("LEDS_ON")) {
        setPartyLeds(3, 3);
        Serial.println("ACK:LEDS_ON");
      } else {
        // Raw string fallback
        setText(msg);
        Serial.println("ACK:TEXT_UPDATED");
      }
    }
  }

  // Automatic non-blocking vertical scroll if text is longer than 4 lines
  if (isScrolling && totalLines > 4) {
    if (millis() - lastScrollTime >= SCROLL_INTERVAL) {
      lastScrollTime = millis();
      currentScrollLine++;
      // Loop back to the start when reaching the end
      if (currentScrollLine > (totalLines - 4)) {
        // Pause briefly on the last view before resetting to the top
        currentScrollLine = 0;
      }
      renderWindow(currentScrollLine);
    }
  }
}
