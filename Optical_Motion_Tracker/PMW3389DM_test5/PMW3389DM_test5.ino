#include <SPI.h>
#include <PMW3389.h>

#define PIN_CS 5

PMW3389 sensor(PIN_CS);

long totalX = 0;
long totalY = 0;
unsigned long lastStatusTime = 0;

void writeCustomReg(uint8_t reg_addr, uint8_t data) {
  SPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE3));
  digitalWrite(PIN_CS, LOW);
  SPI.transfer(reg_addr | 0x80);
  SPI.transfer(data);
  digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
  delayMicroseconds(20);
}

void captureAndDumpFrame() {
  // 1. Terminate any active SPI/Burst session
  digitalWrite(PIN_CS, HIGH);
  delayMicroseconds(50);

  // 2. Trigger frame capture via register 0x12
  writeCustomReg(0x12, 0x83);
  delay(10); // Wait for frame capture completion

  uint8_t frameBuffer[900];

  // 3. Read RawData_Burst (0x64)
  SPI.beginTransaction(SPISettings(2000000, MSBFIRST, SPI_MODE3));
  digitalWrite(PIN_CS, LOW);
  
  SPI.transfer(0x64); 
  delayMicroseconds(35); // tSRAD
  SPI.transfer(0x00);    // Dummy synchronization byte

  for (int i = 0; i < 900; i++) {
    frameBuffer[i] = SPI.transfer(0x00);
  }

  digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
  delayMicroseconds(100);

  // 4. Stream frame over Serial
  Serial.print("FRAME:");
  for (int i = 0; i < 900; i++) {
    Serial.print(frameBuffer[i]);
    if (i < 899) Serial.print(",");
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  if (sensor.begin()) {
    sensor.setDPI(1600);
  } else {
    while (1) { delay(1000); }
  }
}

void loop() {
  // Check for manual capture command from Python dashboard
  if (Serial.available() > 0) {
    char cmd = Serial.read();
    if (cmd == 'F' || cmd == 'f') {
      captureAndDumpFrame();
    }
  }

  PMW3389_Motion motion = sensor.readMotion();

  if (motion.isMotion) {
    if (motion.dx != 0 || motion.dy != 0) {
      totalX += motion.dx;
      totalY += motion.dy;

      Serial.print("MOVE:dx=");
      Serial.print(motion.dx);
      Serial.print(",dy=");
      Serial.print(motion.dy);
      Serial.print(",squal=");
      Serial.print(motion.squal);
      Serial.print(",x=");
      Serial.print(totalX);
      Serial.print(",y=");
      Serial.println(totalY);
    }
  }

  if (millis() - lastStatusTime >= 1000) {
    lastStatusTime = millis();
    Serial.print("STATUS:squal=");
    Serial.println(motion.squal);
  }

  delay(5);
}