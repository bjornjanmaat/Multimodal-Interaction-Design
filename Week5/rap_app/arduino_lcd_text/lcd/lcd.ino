#include <LiquidCrystal_I2C.h>
#include <Wire.h>

// Set the LCD address (0x26, 0x27, or 0x3F) for a 20-column, 4-line display
LiquidCrystal_I2C lcd(0x26, 20, 4);

// Button Pin (Connect button between PIN 7 and GND)
const int BUTTON_PIN = 7;
int lastButtonReading = HIGH;
int buttonState = HIGH;
unsigned long lastDebounceTime = 0;
const unsigned long DEBOUNCE_DELAY = 50;

// Helper function to write a full 20-char line, padding remaining characters with spaces
void writeRow(int row, String text) {
  if (row < 0 || row >= 4) return;
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
const unsigned long SCROLL_INTERVAL = 1800; // Time each 4-line view is shown (ms)
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
    int remaining = textLen - charIdx;
    if (remaining <= 20) {
      lines[totalLines++] = text.substring(charIdx);
      break;
    } else {
      // Find the last space within 20 character window for clean word wrapping
      int splitPos = 20;
      int lastSpace = -1;
      for (int i = 0; i < 20; i++) {
        if (text.charAt(charIdx + i) == ' ') {
          lastSpace = i;
        }
      }
      if (lastSpace > 3) {
        splitPos = lastSpace;
      }

      String rowText = text.substring(charIdx, charIdx + splitPos);
      rowText.trim();
      lines[totalLines++] = rowText;

      charIdx += splitPos;
      // Skip leading spaces on the next line
      while (charIdx < textLen && text.charAt(charIdx) == ' ') {
        charIdx++;
      }
    }
  }

  isScrolling = (totalLines > 4);
  renderWindow(0);
  lastScrollTime = millis();
}

void setup() {
  Serial.begin(9600);

  // Use internal pullup resistor: LOW when pressed / switch ON to GND, HIGH when open
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  lcd.init();      // Initialize the LCD
  lcd.backlight(); // Turn on backlight

  // Initial welcome screen
  setText("Whisper LCD Ready Rap Speech-to-Text Speak into mic...");

  Serial.println("LCD_READY");

  // Broadcast initial button state
  int initialRead = digitalRead(BUTTON_PIN);
  buttonState = initialRead;
  lastButtonReading = initialRead;
  if (buttonState == LOW) {
    Serial.println("BTN:ON");
  } else {
    Serial.println("BTN:OFF");
  }
}

void loop() {
  // Read and debounce button switch
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }
  lastButtonReading = reading;

  if ((millis() - lastDebounceTime) > DEBOUNCE_DELAY) {
    if (reading != buttonState) {
      buttonState = reading;
      // INPUT_PULLUP: LOW = Switch Closed / Button Pressed, HIGH = Switch Open / Button Released
      if (buttonState == LOW) {
        Serial.println("BTN:ON");
      } else {
        Serial.println("BTN:OFF");
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
      } 
      else if (msg.equalsIgnoreCase("STATUS")) {
        if (buttonState == LOW) {
          Serial.println("BTN:ON");
        } else {
          Serial.println("BTN:OFF");
        }
      }
      else if (msg.startsWith("LINE:")) {
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
      } 
      else if (msg.startsWith("TEXT:")) {
        setText(msg.substring(5));
        Serial.println("ACK:TEXT_UPDATED");
      } 
      else {
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

