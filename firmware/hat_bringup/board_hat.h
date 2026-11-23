// POPM-HAT rev A (pcb/popm_board.py, branch pcb-no-sw-chg, ordered 2026-11-10): the ESP32-S3's pins and the I2C parts.
// The one place the pin numbers live: every sketch for this board includes this file.
#pragma once
#include <Arduino.h>
#include <Wire.h>

// servo bus: Feetech STS3215, half duplex through a 74LVC2G241, 1 Mbps. DIR low = transmit, high = receive
// (pulled up: receive through reset)
const int SERVO_TX = 17, SERVO_RX = 18, SERVO_DIR = 16;
// bus A (Wire): IMU, IO expander, ToF plug, Qwiic plug, Pi pins 3 / 5 are NOT on it. 2.2k pull-ups: 400 kHz at most
const int I2C_A_SDA = 6, I2C_A_SCL = 7;
const uint32_t I2C_A_HZ = 400000;
const uint8_t IMU_ADDR = 0x6A, EXP_ADDR = 0x20, TOF_ADDR = 0x29;   // LSM6DS3TR-C, TCA9555, VL53L5CX (if plugged in)
const int IMU_INT = 15, TOF_INT = 14;
// bus B (Wire1): nothing on the board; the two I2C_B plugs (the eyes). 1.5k pull-ups: up to 1 MHz
const int I2C_B_SDA = 4, I2C_B_SCL = 5;
// sound: MAX98357A. AMP_SD high = on, low = shutdown
const int I2S_BCLK = 10, I2S_LRC = 11, I2S_DIN = 12, AMP_SD = 9;
// microSD, SPI mode
const int SD_MOSI = 38, SD_MISO = 47, SD_SCK = 21, SD_CS = 13;
// CAN (TWAI) through an SN65HVD230; RS485 (UART0) through an SP3485: DE high = transmit (its receiver is off then),
// low = receive (pulled down: receive through reset). RX floats while transmitting: keep its pull-up on
const int CAN_TX = 41, CAN_RX = 42;
const int RS485_TX = 43, RS485_RX = 44, RS485_DE = 8;
// UART plug, shared with the Pi's UART (Pi pins 8 / 10 through 1k): use one or the other
const int UART_TX = 39, UART_RX = 40;
// battery: 100k / 18k divider on ADC1. ponytail: nominal ratio; trim VBAT_TRIM against a multimeter on the real board
const int VBAT_ADC = 1;
const float VBAT_RATIO = (100.0f + 18.0f) / 18.0f, VBAT_TRIM = 1.0f;
const int LED = 48;                       // red, high = on
// free: IO2. Not usable: IO0 (BOOT button), IO3 / IO45 / IO46 (straps), IO19 / IO20 (USB), IO35-37 (the module's PSRAM)

// TCA9555 pins on port 1 (port 0 and P10-P13 go to the Pi header, P17 to a test pad)
const uint8_t EXP_AUX_EN = 1 << 4, EXP_AUX_BOOT = 1 << 5, EXP_TOF_LPN = 1 << 6;
enum { EXP_IN0 = 0, EXP_IN1, EXP_OUT0, EXP_OUT1, EXP_POL0, EXP_POL1, EXP_CFG0, EXP_CFG1 };   // its registers

inline bool i2cWrite(TwoWire& w, uint8_t addr, uint8_t reg, uint8_t v) {
  w.beginTransmission(addr); w.write(reg); w.write(v); return w.endTransmission() == 0;
}
inline int i2cRead(TwoWire& w, uint8_t addr, uint8_t reg) {   // -1: no answer
  w.beginTransmission(addr); w.write(reg);
  if (w.endTransmission(false) != 0 || w.requestFrom(addr, (uint8_t)1) != 1) return -1;
  return w.read();
}

// The expander keeps its registers through an ESP reset (only a power cycle clears them), so set them every boot:
// every pin an input (high-Z: the Pi may drive its 12 lines; the UART plug's EN / BOOT and the ToF's LPn sit on their
// pull-ups), output latches low for EN / BOOT (so making one an output pulls it low: open drain) and high for LPn.
inline bool expBegin() {
  return i2cWrite(Wire, EXP_ADDR, EXP_CFG0, 0xFF) && i2cWrite(Wire, EXP_ADDR, EXP_CFG1, 0xFF) &&
         i2cWrite(Wire, EXP_ADDR, EXP_OUT0, 0x00) && i2cWrite(Wire, EXP_ADDR, EXP_OUT1, EXP_TOF_LPN);
}
// pull one of the open-drain lines low (true) or let it go (false): expPull(EXP_AUX_EN, true) holds the co-processor in reset
inline bool expPull(uint8_t bit, bool low) {
  int c = i2cRead(Wire, EXP_ADDR, EXP_CFG1);
  return c >= 0 && i2cWrite(Wire, EXP_ADDR, EXP_CFG1, low ? (c & ~bit) : (c | bit));
}

inline float vbat() { return analogReadMilliVolts(VBAT_ADC) / 1000.0f * VBAT_RATIO * VBAT_TRIM; }
