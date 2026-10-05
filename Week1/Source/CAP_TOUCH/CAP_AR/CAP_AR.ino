const int TOUCH_PIN = A0;

// This value determines the threshold for what constitutes a touch. Each touch must produce a value higher than this threshold. Modify this to experiment. 
const int TOUCH_THRESHOLD = 500;

bool wasTouched = false;

void setup() {
  Serial.begin(9600);
}

void loop() {
  int touchValue = analogRead(TOUCH_PIN);

  // Is the sensor currently being touched?
  bool isTouched = touchValue > TOUCH_THRESHOLD;

  // Only send a message at the moment the sensor is first touched.
  if (isTouched && !wasTouched) {
    Serial.println("TOUCH");
  }

  wasTouched = isTouched;

  delay(20);
}