const int TOUCH_PIN = A0;  // AT42QT1012 OUT pin
const int FSR_PIN   = A1;  // FSR output

bool wasTouched = false;

//Intial Setup
void setup() {
  Serial.begin(9600);

  pinMode(TOUCH_PIN, INPUT);

  // Allow the AT42QT1012 to calibrate after power-up.
  delay(1000);

  // Record startup state to avoid a false trigger on boot.
  wasTouched = digitalRead(TOUCH_PIN);

  Serial.println("READY");
}

void loop() {
  // --- Capacitive touch value ---
  bool isTouched = digitalRead(TOUCH_PIN);

  if (isTouched && !wasTouched) {
    Serial.println("TOUCH");
  }

  wasTouched = isTouched;

  // --- FSR value ---
  int fsrValue = analogRead(FSR_PIN);
  Serial.println(fsrValue);

  delay(20);
}