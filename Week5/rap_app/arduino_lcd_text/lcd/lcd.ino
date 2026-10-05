#include <LiquidCrystal_I2C.h>
#include <Wire.h>

// Set the LCD address (0x26, 0x27, or 0x3F) for a 20-column, 4-line display
LiquidCrystal_I2C lcd(0x26, 20, 4);

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

// Word-wrap and display text across the 4 rows of the 20x4 LCD
void displayText(String text) {
  int textLen = text.length();
  int charIdx = 0;

  for (int row = 0; row < 4; row++) {
    if (charIdx >= textLen) {
      writeRow(row, "");
      continue;
    }

    int remaining = textLen - charIdx;
    if (remaining <= 20) {
      writeRow(row, text.substring(charIdx));
      charIdx = textLen;
    } else {
      // Find the last space within the 20 character window
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
      writeRow(row, rowText);

      charIdx += splitPos;
      // Skip whitespace at start of next line
      while (charIdx < textLen && text.charAt(charIdx) == ' ') {
        charIdx++;
      }
    }
  }
}

void setup() {
  Serial.begin(9600);

  lcd.init();      // Initialize the LCD
  lcd.backlight(); // Turn on backlight

  // Initial welcome screen
  writeRow(0, "Whisper LCD Ready");
  writeRow(1, "Rap Speech-to-Text");
  writeRow(2, "--------------------");
  writeRow(3, "Speak into mic...");

  Serial.println("LCD_READY");
}

void loop() {
  if (Serial.available() > 0) {
    String msg = Serial.readStringUntil('\n');
    msg.trim();

    if (msg.length() == 0) return;

    if (msg.equalsIgnoreCase("CLEAR")) {
      clearAll();
      Serial.println("ACK:CLEARED");
    } 
    else if (msg.startsWith("LINE:")) {
      // Format: LINE:<row>:<text>
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
      displayText(msg.substring(5));
      Serial.println("ACK:TEXT_UPDATED");
    } 
    else {
      // Raw string fallback
      displayText(msg);
      Serial.println("ACK:TEXT_UPDATED");
    }
  }
}

