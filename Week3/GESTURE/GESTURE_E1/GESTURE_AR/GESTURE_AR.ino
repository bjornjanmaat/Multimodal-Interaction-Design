const int trigPin = 12;
const int echoPin = 13;

unsigned long duration;
float distance;

void setup() {
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  Serial.begin(9600);
}

void loop() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);

  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);

  digitalWrite(trigPin, LOW);

  duration = pulseIn(echoPin, HIGH, 30000);
  distance = (duration * 0.0343) / 2.0;

  // Send only the numeric value, e.g. "42.37"
  Serial.println(distance);

  delay(50);
}