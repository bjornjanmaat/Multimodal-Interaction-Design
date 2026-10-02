#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// Set the LCD address to 0x27 for a 20-column, 4-line display
// (If 0x27 does not work, change to 0x3F)
LiquidCrystal_I2C lcd(0x26, 20, 4);

void setup() {
  lcd.init();          // Initialize the LCD
  lcd.backlight();     // Turn on backlight

  // Print text across rows (col 0 to 19, row 0 to 3)
  lcd.setCursor(0, 0);
  lcd.print("Hey Akshat");

  lcd.setCursor(0, 1);
  lcd.print("Andrei");

  lcd.setCursor(0, 2);
  lcd.print("Sasha");

  lcd.setCursor(0, 3);
  lcd.print("你好");
}

void loop() {
  // Static display, no loop updates needed
}
