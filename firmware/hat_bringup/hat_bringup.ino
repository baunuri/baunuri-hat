// POPM-HAT bring-up: checks every part of the board it can reach on its own and prints one line each over USB.
//   arduino-cli compile -b esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi firmware/hat_bringup
//   arduino-cli upload  -b esp32:esp32:esp32s3:CDCOnBoot=cdc,FlashSize=16M,PSRAM=opi -p /dev/ttyACM0 firmware/hat_bringup
//   (first flash of a blank board: hold BOOT, tap RESET, release BOOT; then upload)
//   arduino-cli monitor -p /dev/ttyACM0        then press a key:
//     t  run the tests again      b  beep            s  scan the servo bus (IDs 0-253)
//     m  swing the first servo 18 deg and back      f / F  90 / 180 deg and back at top speed, traced
//     d  dump the servo's speed-related registers   A  raise its acceleration limit (until power-off)
//     r  send "popm\n" on RS485   u  UART plug loopback (join its TX and RX pins first)
// Order of bring-up: USB only first (no pack: servos and VBAT read as absent, that's expected), then a pack with no
// servos, then servos one at a time. The board has no power switch: it is live as soon as a pack is plugged in.
// PASS / FAIL lines are what the board itself can tell; "----" lines need something plugged in or a meter.
#include "board_hat.h"
#include <WiFi.h>
#include <SPI.h>
#include <SD.h>
#include <ESP_I2S.h>
#include "driver/twai.h"

HardwareSerial& bus = Serial1;            // servo bus
HardwareSerial& rs485 = Serial0;          // UART0 (the console is on USB: Serial)
HardwareSerial& aux = Serial2;            // UART plug / Pi
I2SClass i2s;
bool i2s_ok = false;

void line(const char* what, int ok, const String& note) {   // ok: 1 pass, 0 fail, -1 can't tell
  Serial.printf("%-5s %-12s %s\n", ok > 0 ? "PASS" : ok == 0 ? "FAIL" : "----", what, note.c_str());
}

// ---- Feetech SCS / STS packets: FF FF id len instr params... chk, chk = ~(id + len + instr + params)
size_t stsPacket(uint8_t* p, uint8_t id, uint8_t instr, const uint8_t* par, uint8_t n) {
  p[0] = p[1] = 0xFF; p[2] = id; p[3] = n + 2; p[4] = instr;
  uint8_t sum = id + p[3] + instr;
  for (int k = 0; k < n; k++) { p[5 + k] = par[k]; sum += par[k]; }
  p[5 + n] = ~sum;
  return n + 6;
}
// send, then read the reply's parameters into out (up to n). Returns the count read, -1 on no / bad answer
int stsTxRx(uint8_t id, uint8_t instr, const uint8_t* par, uint8_t np, uint8_t* out, uint8_t n, uint32_t wait_ms = 5) {
  uint8_t p[16]; size_t len = stsPacket(p, id, instr, par, np);
  while (bus.available()) bus.read();
  digitalWrite(SERVO_DIR, LOW); bus.write(p, len); bus.flush(); digitalWrite(SERVO_DIR, HIGH);   // flush(): until the last bit is out
  uint8_t r[16]; size_t got = 0, want = 6 + n; uint32_t t0 = millis();
  while (got < want && millis() - t0 < wait_ms) if (bus.available()) r[got++] = bus.read();
  if (got < want || r[0] != 0xFF || r[1] != 0xFF || r[2] != id || r[3] != n + 2) return -1;
  uint8_t sum = r[2] + r[3] + r[4];
  for (int k = 0; k < n; k++) sum += r[5 + k];
  if ((uint8_t)~sum != r[5 + n]) return -1;
  for (int k = 0; k < n; k++) out[k] = r[5 + k];
  return n;
}
bool stsPing(uint8_t id) { return stsTxRx(id, 0x01, nullptr, 0, nullptr, 0) == 0; }
int stsRead(uint8_t id, uint8_t addr, uint8_t n, uint8_t* out) { uint8_t par[2] = {addr, n}; return stsTxRx(id, 0x02, par, 2, out, n); }

bool stsWrite(uint8_t id, uint8_t addr, const uint8_t* d, uint8_t n) {
  uint8_t par[10] = {addr}; memcpy(par + 1, d, n); return stsTxRx(id, 0x03, par, n + 1, nullptr, 0) == 0;
}
int stsPos(uint8_t id) { uint8_t v[2]; return stsRead(id, 56, 2, v) == 2 ? v[0] | v[1] << 8 : -1; }   // present position, 0-4095

int servoFirst() { for (int id = 0; id <= 20; id++) if (stsPing(id)) return id; return -1; }   // -1: none on IDs 0-20

// 'm' / 'f' / 'F': the first servo on IDs 0-20 swings `swing` steps toward the side away from the 0 / 4095 wrap and back,
// then torque off. Prints how long each leg took and the peak speed the servo reported. speed 0 and acc 0 = its max.
// ponytail: position mode assumed (reg 33 = 0); 4096 steps = 360 deg
void servoMove(int swing, int speed, int acc = 0, bool trace = false) {
  int id = servoFirst(); if (id < 0) { line("servo move", 0, "no servo on IDs 0-20"); return; }
  uint8_t mode = 0xFF; stsRead(id, 33, 1, &mode);
  int home = stsPos(id); if (home < 0) { line("servo move", 0, "can't read its position"); return; }
  Serial.printf("      servo id %d: mode %d, at %d, swing %d, speed %d, acc %d\n", id, mode, home, swing, speed, acc);
  uint8_t on = 1; stsWrite(id, 40, &on, 1);                     // torque on
  int worst = 0;
  for (int goal : {home + (home < 2048 ? swing : -swing), home}) {
    goal = constrain(goal, 0, 4095);
    uint8_t g[7] = {(uint8_t)acc, (uint8_t)goal, (uint8_t)(goal >> 8), 0, 0, (uint8_t)speed, (uint8_t)(speed >> 8)};   // acc, goal, time, speed
    uint32_t t0 = millis(), arrived = 0; int peak = 0, at = -1, ma = 0;
    stsWrite(id, 41, g, 7);
    while (millis() - t0 < 1500) {                               // regs 56-59: present position, present speed
      uint8_t v[4]; if (stsRead(id, 56, 4, v) != 4) continue;
      at = v[0] | v[1] << 8; peak = max(peak, (v[2] | (v[3] & 0x7F) << 8));   // speed: bit 15 = direction
      if (!arrived && abs(at - goal) <= 10) arrived = millis() - t0;
      static uint32_t last; if (trace && millis() - last >= 25) { last = millis(); Serial.printf("        %4u ms  pos %4d  speed %4d\n", millis() - t0, at, v[2] | (v[3] & 0x7F) << 8); }
    }
    uint8_t l[2] = {0, 0}; stsRead(id, 69, 2, l); ma = (l[0] | (l[1] & 0x7F) << 8) * 13 / 2;   // 6.5 mA per unit
    worst = max(worst, abs(at - goal));
    Serial.printf("      goal %4d  at %4d  (off by %d)  took %u ms  peak %d steps/s (%.0f deg/s)  %d mA\n",
                  goal, at, at - goal, arrived, peak, peak * 360.0f / 4096, ma);
  }
  uint8_t off = 0; stsWrite(id, 40, &off, 1);
  line("servo move", worst <= 15, "worst error " + String(worst) + " steps (15 = 1.3 deg)");
}

// 'd': the first servo's settings that bear on speed (Feetech STS memory table; 84-86 are factory, read-only)
void servoDump() {
  int id = servoFirst(); if (id < 0) { line("servo dump", 0, "no servo on IDs 0-20"); return; }
  const uint8_t regs[] = {3, 4, 5, 16, 17, 18, 19, 21, 22, 23, 24, 25, 26, 27, 28, 33, 34, 35, 36, 41, 46, 47, 48, 49, 55, 80, 81, 82, 83, 84, 85, 86};
  for (uint8_t r : regs) { uint8_t v = 0; Serial.printf("      reg %2d = %s\n", r, stsRead(id, r, 1, &v) == 1 ? String(v).c_str() : "--"); }
}

int servoScan(int last) {
  int found = 0;
  for (int id = 0; id <= last; id++) if (stsPing(id)) {
    uint8_t v[2] = {0, 0}; stsRead(id, 62, 2, v);          // present voltage (0.1 V), temperature (C)
    Serial.printf("      servo id %d: %.1f V, %d C\n", id, v[0] / 10.0f, v[1]); found++;
  }
  return found;
}

void beep(float hz, int ms) {
  if (!i2s_ok) return;
  digitalWrite(AMP_SD, HIGH); delay(10);
  int16_t b[160];
  for (int n = 0, total = 16 * ms; n < total; n += 160) {
    for (int k = 0; k < 160; k++) b[k] = 3000 * sinf(2 * PI * hz * (n + k) / 16000.0f);   // ~10 % of full scale
    i2s.write((uint8_t*)b, sizeof b);
  }
  memset(b, 0, sizeof b); i2s.write((uint8_t*)b, sizeof b);
  delay(30); digitalWrite(AMP_SD, LOW);
}

bool canLoop() {   // the controller sends a frame to itself through the transceiver: TX -> SN65HVD230 -> RX
  twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT((gpio_num_t)CAN_TX, (gpio_num_t)CAN_RX, TWAI_MODE_NO_ACK);
  twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS(); twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();
  if (twai_driver_install(&g, &t, &f) != ESP_OK) return false;
  bool ok = false;
  if (twai_start() == ESP_OK) {
    twai_message_t m = {}; m.identifier = 0x123; m.data_length_code = 2; m.data[0] = 0x50; m.data[1] = 0x4D; m.self = 1;
    twai_message_t r;
    ok = twai_transmit(&m, pdMS_TO_TICKS(100)) == ESP_OK && twai_receive(&r, pdMS_TO_TICKS(200)) == ESP_OK &&
         r.identifier == 0x123 && r.data[0] == 0x50 && r.data[1] == 0x4D;
    twai_stop();
  }
  twai_driver_uninstall();
  return ok;
}

void tests() {
  Serial.println("\n== POPM-HAT bring-up ==");
  line("module", ESP.getFlashChipSize() >= 16u << 20 && ESP.getPsramSize() >= 7u << 20,
       String(ESP.getChipModel()) + ", flash " + (ESP.getFlashChipSize() >> 20) + " MB, PSRAM " + (ESP.getPsramSize() >> 20) + " MB");

  float v = vbat();
  line("battery", v > 6 && v < 17.5f ? 1 : -1, String(v, 2) + " V" + (v < 1 ? " (no pack: on USB / Pi power)" : v < 6 ? " (too low for the buck: < 6 V)" : ""));

  // bus A: IMU, expander, ToF (if plugged in)
  int who = i2cRead(Wire, IMU_ADDR, 0x0F);
  line("imu", who == 0x6A, who < 0 ? "no answer at 0x6A" : "WHO_AM_I 0x" + String(who, HEX) + " (LSM6DS3TR-C: 0x6a)");
  if (who == 0x6A) {
    i2cWrite(Wire, IMU_ADDR, 0x10, 0x40); i2cWrite(Wire, IMU_ADDR, 0x11, 0x40); delay(60);   // accel + gyro at 104 Hz, 2 g / 250 dps
    Wire.beginTransmission(IMU_ADDR); Wire.write(0x28);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(IMU_ADDR, (uint8_t)6) == 6) {
      int16_t a[3]; for (int k = 0; k < 3; k++) { a[k] = Wire.read(); a[k] |= Wire.read() << 8; }
      float g[3] = {a[0] * 0.061e-3f, a[1] * 0.061e-3f, a[2] * 0.061e-3f}, mag = sqrtf(g[0] * g[0] + g[1] * g[1] + g[2] * g[2]);
      line("imu accel", mag > 0.85f && mag < 1.15f, String(g[0], 2) + " " + String(g[1], 2) + " " + String(g[2], 2) + " g (|a| " + String(mag, 2) + ": 1.00 lying still)");
    } else line("imu accel", 0, "read failed");
    pinMode(IMU_INT, INPUT);
    i2cWrite(Wire, IMU_ADDR, 0x0D, 0x01); delay(30);        // INT1 = accel data ready: the pin should go high
    line("imu int", digitalRead(IMU_INT), "INT1 on IO15 with data ready routed to it");
    i2cWrite(Wire, IMU_ADDR, 0x0D, 0x00);
  }
  bool e = expBegin(); int in1 = i2cRead(Wire, EXP_ADDR, EXP_IN1);
  line("expander", e, e ? "TCA9555 set up; port 1 reads 0x" + String(in1, HEX) + " (LPn, bit 6, should be 1)" : "no answer at 0x20");
  if (e) line("tof lpn", in1 & EXP_TOF_LPN ? 1 : 0, "the ToF's enable line on its pull-up");
  Wire.beginTransmission(TOF_ADDR);
  line("tof", Wire.endTransmission() == 0 ? 1 : -1, "VL53L5CX at 0x29 (only with the sensor plugged into TOF)");
  String b; for (uint8_t a = 8; a < 120; a++) { Wire1.beginTransmission(a); if (Wire1.endTransmission() == 0) b += " 0x" + String(a, HEX); }
  line("bus B", b.length() ? 1 : -1, b.length() ? "answers at" + b + " (eyes: 0x3c, 0x3d)" : "nothing plugged into I2C_B1 / B2");

  line("sound", i2s_ok, i2s_ok ? "I2S up; a beep now: listen (speaker on SPEAKER)" : "I2S did not start");
  beep(880, 150);

  bool sd = false;   // after a reset (no power cycle) the card ignores its first CMD0 or two: retry
  for (int i = 0; i < 4 && !sd; i++) { sd = SD.begin(SD_CS, SPI, 10000000); if (!sd) SD.end(); }
  line("microSD", sd ? 1 : -1, sd ? String((uint32_t)(SD.cardSize() >> 20)) + " MB card" : "no card (or it didn't answer)");
  if (sd) SD.end();

  line("can", canLoop(), "a frame through the transceiver and back (needs a terminator: JP1 bridged or a 120R on the bus)");

  int n = servoScan(20);
  line("servos", n ? 1 : -1, n ? String(n) + " answered (IDs 0-20; 's' scans all)" : "none on IDs 0-20 (needs a pack: the bus is on VBAT)");

  int nets = WiFi.scanNetworks(); int best = -127;
  for (int k = 0; k < nets; k++) best = max(best, (int)WiFi.RSSI(k));
  line("wifi", nets > 0, nets > 0 ? String(nets) + " networks, strongest " + best + " dBm" : "no networks seen (antenna?)");
  WiFi.scanDelete();

  line("rs485", -1, "'r' sends \"popm\": watch A / B with an adapter");
  line("uart", -1, "'u' with the UART plug's TX and RX joined");
  Serial.println("keys: t tests, b beep, s servo scan, m / f / F move servo, d dump, A accel limit, r RS485, u UART loopback");
}

void setup() {
  pinMode(LED, OUTPUT); digitalWrite(LED, HIGH);
  pinMode(AMP_SD, OUTPUT); digitalWrite(AMP_SD, LOW);
  pinMode(SERVO_DIR, OUTPUT); digitalWrite(SERVO_DIR, HIGH);     // receive
  pinMode(RS485_DE, OUTPUT); digitalWrite(RS485_DE, LOW);        // receive
  Serial.begin(115200);
  for (uint32_t t0 = millis(); !Serial && millis() - t0 < 3000;) delay(10);   // USB: wait for the monitor, 3 s at most
  uint8_t p[8]; stsPacket(p, 1, 0x01, nullptr, 0);               // self-check: ping to ID 1 is FF FF 01 02 01 FB
  if (p[3] != 0x02 || p[5] != 0xFB) Serial.println("BUG: stsPacket checksum");
  Wire.begin(I2C_A_SDA, I2C_A_SCL, I2C_A_HZ);
  Wire1.begin(I2C_B_SDA, I2C_B_SCL, 400000);
  bus.begin(1000000, SERIAL_8N1, SERVO_RX, SERVO_TX);
  rs485.begin(115200, SERIAL_8N1, RS485_RX, RS485_TX); pinMode(RS485_RX, INPUT_PULLUP);   // RX floats while DE is high
  aux.begin(115200, SERIAL_8N1, UART_RX, UART_TX);
  SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
  i2s.setPins(I2S_BCLK, I2S_LRC, I2S_DIN);
  i2s_ok = i2s.begin(I2S_MODE_STD, 16000, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO);
  WiFi.mode(WIFI_STA);
  tests();
}

void loop() {
  digitalWrite(LED, millis() / 500 % 2);                         // heartbeat
  if (!Serial.available()) return;
  switch (Serial.read()) {
    case 't': tests(); break;
    case 'b': beep(440, 300); Serial.println("beep"); break;
    case 'm': servoMove(200, 1000); break;
    case 'd': servoDump(); break;
    case 'A': {   // reg 85, the acceleration limit: 50 from the factory caps the ramp at ~435 deg/s^2 whatever reg 41 says.
                  // 254 here; EEPROM lock (reg 55) left on, so the servo is back to 50 after a power cycle
      int id = servoFirst(); uint8_t v = 254, r = 0; bool ok = id >= 0 && stsWrite(id, 85, &v, 1); if (ok) stsRead(id, 85, 1, &r);
      Serial.printf("      reg 85 write %s, reads %d\n", ok ? "acked" : "failed", r); break;
    }
    case 'F': servoMove(2048, 0, 254, true); break;
    case 'f': servoMove(1024, 0, 254, true); break;
    case 's': Serial.printf("servo scan: %d found\n", servoScan(253)); break;
    case 'r':
      digitalWrite(RS485_DE, HIGH); rs485.print("popm\n"); rs485.flush(); digitalWrite(RS485_DE, LOW);
      Serial.println("RS485: sent \"popm\\n\" at 115200"); break;
    case 'u': {
      while (aux.available()) aux.read();
      aux.print("popm"); aux.flush(); delay(20);
      char r[5] = {0}; int k = 0; while (aux.available() && k < 4) r[k++] = aux.read();
      line("uart", !strcmp(r, "popm"), k ? String("got \"") + r + "\"" : "nothing came back (TX and RX joined?)"); break;
    }
  }
}
