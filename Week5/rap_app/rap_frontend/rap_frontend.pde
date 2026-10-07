void setup() {
  size(600, 400);
  background(30, 30, 40);
}

void draw() {
  // Slight background fade for trailing effect
  fill(30, 30, 40, 25);
  noStroke();
  rect(0, 0, width, height);
  
  // Interactive circle following mouse
  fill(0, 200, 255);
  stroke(255);
  strokeWeight(2);
  circle(mouseX, mouseY, 40);
}
