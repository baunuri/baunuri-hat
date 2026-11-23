# Design notes: Baunuri HAT rev A (POPM-HAT)

The board: the same circuits as the 74 × 38 POPM-CTRL, on a Raspberry Pi HAT-size board (65 × 57 mm, the Pi's
hole pattern) with a Pi-style 2 × 20 header (HATs plug onto it), a microSD on SPI and a 16-bit I2C GPIO expander.

One board instead of the Waveshare ESP32 servo board, the GY-521, the MAX98357A breakout, the buck converter and the
charge diode. It also adds a connector for the 8×8 ToF sensor.

**Status:** schematic as code (`popm_board.py`, SKiDL; ERC clean, 81 nets, 120 parts), placed, routed and through the
fab gate (`fab.py`); reviewed; ordered from JLCPCB (assembled) on 2026-11-10 at commit a57b8a4.

    cd pcb && python3 -m venv .venv && .venv/bin/pip install skidl   # once; needs KiCad 9's libraries
    .venv/bin/python popm_board.py                                    # -> popm_board.net (import it in Pcbnew)

## Fit
- **Outline:** 65 × 57 mm, rounded corners (R 3). 4 × 3.0 mm NPTH holes (M2.5) at (3.5, 4), (61.5, 4), (3.5, 53), (61.5, 53)
  from the top-left corner: a 58 × 49 mm rectangle, as on a Pi / HAT. No copper within 3.0 mm of a hole's centre, either side
  (screw heads, standoffs). 4 layers, 1.6 mm: F / In1 (solid GND) / In2 (signals) / B.
- **Order:** 4 layers, 1.6 mm, 1 oz outer **and 1 oz inner copper** (not JLC's 0.5 oz inner default: the battery trunk may run on the inner layer). Assemble 2, everything included: JLC solders the through-hole plugs too (`HAND=1` leaves them off and writes an LCSC cart instead).
- **Edges:** top: the Pi header (female, underneath). Left: the ESP32-S3's antenna over a notch (no copper beside it). Bottom: USB-C, I2C_B1, I2C_B2, QWIIC, TOF
  (JST-SH mouths at the edge). Right: BATTERY (XT30), UART (JST-SH), microSD slot. SERVO1/2 and SPEAKER are
  vertical plugs inside.
- **Stack height on a Pi 5:** use a tall stacking header with 15-16 mm (or taller) spacers. On a standard 8.5 mm or a low-profile socket the microSD card and the XT30 lead run into the Pi 5's Ethernet / USB jacks (review, from the Pi 5 drawing).
- **On a Pi:** this board is a HAT: it plugs onto a Raspberry Pi's 40-pin header with a female 2 × 20 socket underneath,
  and its holes line up with the Pi's (M2.5 standoffs). The socket's height sets the gap: underside parts and the plugs'
  through-hole pins (~2–3 mm) must clear the Pi's own parts (not checked against any Pi model).

## Pi header (J13, 2 × 20, 2.54 mm, female, underneath). Each pad right over the Pi's pin: rows at y 4 ± 1.27, pin 1 inside, at the left end
**Not assembled by JLC:** solder a tall 2 × 20 stacking header (2.54 mm, female, for 15-16 mm spacers on a Pi 5) yourself, from underneath (fab.py leaves J13 off the order).
The Pi and the ESP32 never drive the same line: everything else on the header is left open.
| Pi pin | Pi name | Net | This board |
|---|---|---|---|
| 2, 4 | 5V | PI_5V | into our +5V through a Schottky (D8): the Pi can run the ESP side; our battery never feeds the Pi |
| 6, 9, 14, 20, 25, 30, 34, 39 | GND | GND | |
| 8 | TXD (Pi out) | PI_TXD → 1k → UART_RX | ESP GPIO40 (UART2 RX) |
| 10 | RXD (Pi in) | UART_TX → 1k → PI_RXD | ESP GPIO39 (UART2 TX) |
| 11 | GPIO17 | PI_EN → 2N7002 (Q3) → ESP EN | Pi high = ESP held in reset |
| 13 | GPIO27 | PI_BOOT → 2N7002 (Q4) → ESP GPIO0 | Pi high = ESP boots into download mode (with a reset) |
| 7, 15, 16, 18, 22, 26, 29, 31 | | EXP_P00 … EXP_P07 (expander port 0, in that order) | |
| 32, 33, 36, 37 | | EXP_P10 … EXP_P13 (expander port 1) | |
| 1, 17 (3V3), 3, 5 (I2C), 27, 28 (ID EEPROM), 12, 35, 38, 40 (PCM), 19, 21, 23, 24 (SPI) | | not connected | |

- **UART2 is shared with the UART plug (J12):** use the Pi link or a device on the plug, not both (two TX outputs on one RX).
  The 1k resistors stop either side back-powering the other while it's off.
- **Reset / boot from the Pi:** the FETs (100k gate pull-downs; the Pi's GPIO17 / 27 also pull down at boot) stay off while the
  Pi is off or booting. Flash the ESP from the Pi over a USB-C cable (its ROM loader's UART is UART0, the RS485 one).
- **The 12 expander lines** come up as inputs on both sides (TCA9555 and the Pi): set directions in software before driving any.

## GPIO expander (U9, TCA9555PWR, LCSC C465732)
- On I2C bus A (I2C_A_SDA / I2C_A_SCL) at **0x20** (A0-A2 to GND; the IMU is 0x6A, the ToF 0x29). 3V3, 100 nF at VCC.
- P00-P07 and P10-P13 go to the header (table above). P14 / P15: AUX_EN / AUX_BOOT (UART plug; Pi pins 11 / 13 are PI_EN / PI_BOOT: the Pi resets / boot-selects the ESP), P16: the ToF's LPn, P17: test pad TP8.
- **INT is not wired to the ESP32** (no free GPIO): it has a 10k pull-up and test pad TP9. Firmware polls the input registers.

## microSD (J14, Molex 104031-0811, LCSC C585350), SPI mode
- DAT3/CS → SD_CS (GPIO 13), CMD → SPI_MOSI (38), CLK → SPI_SCK (21), DAT0 → SPI_MISO (47). 10k pull-ups to 3V3 on CS, CMD,
  DAT0, DAT1, DAT2; 10 µF + 100 nF at VDD. The card-detect switch isn't wired.
- Slot at the right edge. It's a push-pull socket (the card slides in and is pulled out), not push-push.

## CAN (U10, SN65HVD230, LCSC C12084) and RS485 (U11, SP3485EN, LCSC C8963)
- **CAN:** the ESP32-S3's TWAI on GPIO 41 (TX → D) / 42 (RX ← R). Rs to GND (full speed). 10k pull-up on TX: recessive
  through reset. Plug J15 (JST-GH 4, DroneCAN order): 1 +5V, 2 CANH, 3 CANL, 4 GND.
- **RS485:** UART0 (GPIO 43 TX → DI, 44 RX ← RO; the console is on USB), DE + /RE together on GPIO 8 (high = send), 10k
  pull-down: receiving through reset, so the boot log never reaches the bus. Plug J16 (JST-GH 4): 1 +5V, 2 A, 3 B, 4 GND.
- Each: a 120R terminator behind a solder jumper (JP1 CAN, JP2 RS485: bridge it on the boards at the bus's two ends) and a
  TVS (PESD2CAN, SM712). No RS485 fail-safe bias resistors: add them on the bus if nothing else biases it.

## Blocks
```
 2S–4S pack ───────────── reverse-polarity P-FET ─ fuse ─ TVS ─┬─ VBAT ── 2 × servo bus connectors (STS3215 chains)
                   │                                      └─ buck 5.4 V / 2 A ─ SS34 ─┬─ +5 V ── amp, XIAO, LED
                                                               USB-C VBUS ─ SS34 ──────┘    └─ AMS1117 ── +3V3: ESP32-S3, IMU, eyes, ToF, buffer
 (no switch, no charge port: in the pack's own lead)           VBAT divider ─▶ ADC

 ESP32-S3-WROOM-1-N16R8 ── UART1 ── 74LVC2G241 (DIR) ── servo bus (half duplex)
                        ── I2C bus B (up to 1 MHz) ── I2C_B1, I2C_B2 plugs, e.g. displays (JST-SH 4)
                        ── I2C bus A (400 kHz max) ── IMU + expander on board, ToF (JST-SH 6), Qwiic (JST-SH 4)
                        ── I2S ── MAX98357A ── speaker (JST-PH 2)
                        ── UART2 + EN/BOOT ── XIAO camera (JST-SH 6)
                        ── USB-C (native USB: flash + log, 5 V for the logic on the bench)
                        ── red status LED (GPIO48, high = on), BOOT button (doubles as a user button)
```

## Parts (LCSC numbers to fill in while drawing the schematic: prefer JLC basic / preferred parts)
| Block | Part | Why |
|---|---|---|
| MCU | ESP32-S3-WROOM-1-N16R8 | 16 MB flash (no more 97 %), 8 MB PSRAM, native USB, 2 I2C, 3 UARTs, I2S |
| Servo bus | 74LVC2G241 at 3.3 V + 10 k pull-up | half duplex with one DIR pin (the Robotis circuit). LVC inputs take 5 V, so a 5 V bus is safe on RX |
| IMU | LSM6DS3TR-C (or BMI270) | the MPU-6050 is end-of-life and clones vary; this one is cheap and stocked at JLC. Firmware: new register map |
| Amp | MAX98357AETE+ | same as now; SD_MODE on a GPIO (mute with no pop, save power) |
| 5 V buck | TPS54202 (4.5–28 V in, 2 A), set to 5.4 V, then an SS34 Schottky OR with USB 5 V | headroom over 12.6 V and charger spikes; USB powers the logic on the bench |
| 3.3 V | AMS1117-3.3 from 5 V | the average draw is ~0.2 A (Wi-Fi peaks are short); a second buck if it runs hot |
| Reverse polarity | P-FET, 30 V, ≥ 8 A (AO4407-class) | the pack plugged in backwards |
| Protection | 5 A / 30 V PTC fuse, SMBJ18A TVS on VBAT, USBLC6-2 on USB | rated for a full 4S (16.8 V); battery-side caps 35 V |
| Sense | VBAT 100 k / 18 k → ADC (16.8 V → 2.56 V) | battery % for the page |

## Pin map (ESP32-S3-WROOM-1-N16R8: GPIO 26–37 are taken by the octal flash and PSRAM)
| Function | GPIO |
|---|---|
| Servo TX / RX / DIR (UART1) | 17 / 18 / 16 |
| I2C bus B SDA / SCL (the two I2C_B plugs) | 4 / 5 |
| I2C bus A SDA / SCL (IMU, ToF, expander, Qwiic): **400 kHz max** (the TCA9555 and the IMU are Fast-mode parts) | 6 / 7 |
| IMU INT | 15 |
| ToF INT (LPn: expander P16) | 14 |
| I2S BCLK / LRC / DIN, amp SD | 10 / 11 / 12, 9 |
| VBAT sense (ADC1) | 1 (IO2 is free: it was the charger-present sense) |
| UART2 TX / RX (UART plug, Pi pins 10 / 8) | 39 / 40 |
| CAN TX / RX (TWAI) | 41 / 42 |
| RS485 TX / RX (UART0) / DE | 43 / 44 / 8 (enable GPIO44's pull-up: RO is high-Z while sending) |
| microSD: MOSI / MISO / SCK / CS | 38 / 47 / 21 / 13 |
| Status LED (red, through 1 k; high = on) | 48 |
| BOOT / user button | 0 |
| USB D− / D+ | 19 / 20 |
| Not connected (straps: JTAG select, flash voltage, ROM log) | 3, 45, 46 |
| On the expander: UART plug EN / BOOT, ToF LPn | P14 / P15, P16 (set the expander's outputs at boot: it keeps them through an ESP reset) |

## Connectors
| What | Connector | Pins |
|---|---|---|
| Battery in | XT30PW-M right angle (the pack's lead is an XT30 female) | pad 2 +, pad 1 − |

**No power switch and no charge port on the board** (as Waveshare's servo HAT): the board is live whenever a pack is
plugged in. Put a switch in the pack's lead if you want one, and charge the pack on its own charger, unplugged.

**The pack must be a protected one (it has a BMS: short-circuit, over-discharge, over-charge).** The board's 5 A fuse only
covers the board itself, and nothing on the board can stop the servos from running the cells flat.
| SERVO1, SERVO2: servo bus × 2 (e.g. a drive chain and a head chain) | Molex SPOX 5267-03A (the STS3215's own plug) | pin 1 DATA, 2 VBAT, 3 GND (as Waveshare's Bus Servo Adapter (A)) |
| I2C_B1, I2C_B2 | JST-SH 4 | 1 GND, 2 3V3, 3 SDA, 4 SCL (Qwiic order; bus B) |
| ToF | JST-SH 6 | 1 GND, 2 3V3, 3 SDA, 4 SCL, 5 LPn, 6 INT |
| Qwiic | JST-SH 4 | 1 GND, 2 3V3, 3 SDA, 4 SCL (bus A) |
| Speaker | JST-PH 2 | |
| UART (a co-processor, e.g. a XIAO camera) | JST-SH 6 | 1 GND, 2 5V, 3 TX, 4 RX, 5 EN, 6 BOOT (EN / BOOT from the expander: open drain by switching its direction) |
| USB-C | 16-pin receptacle | |

## Power budget
| Rail | Loads | Peak |
|---|---|---|
| VBAT (2S 6–8.4 V, 3S 9–12.6 V or 4S up to 16.8 V; the buck turns on above ~5.8 V) | servos straight off the pack, so match their version to it (STS3215 7.4 V on 2S, 12 V on 3S; 4S only with servos rated for it). Sense dividers 100k / 18k: 16.8 V reads 2.56 V. Bigger servo counts: power them from a separate hub, not through this board. Popm: 4 × STS3215 12 V (stall ~2.7 A each; driving 0.2–0.5 A each). Firmware torque limits keep stalls short | fuse 5 A hold, traces ≥ 5 A |
| 5 V | amp ~0.7 A at full volume, XIAO + camera ~0.3 A | ~1.0 A of 2 A (TPS54202), shared with everything on the 5 V plugs (CAN, RS485, UART) |
| 3.3 V | ESP32-S3 Wi-Fi ~0.5 A, ToF ~0.1 A, eyes 2 × 25 mA, IMU, buffer | ~0.2 A average (Wi-Fi peaks are short): an AMS1117 in SOT-223 can't sustain 0.7 A (~1.2 W) |

## 8×8 ToF (VL53L5CX family, ordered 2026-11-04)
- **Connector:** on the sensor I2C bus, not the eyes' (those send ~1 KB frames all the time). Bus A runs at 400 kHz max (the expander and the IMU on it).
- **LPn on a GPIO:** it can be reset, or moved off its default address if a second one is added.
- **Firmware:** its driver uploads ~86 KB of sensor firmware over I2C at every boot (~90 KB of flash): fine with 16 MB.
- **Placement:** probably the chest next to the camera, looking forward and a little down. CAD to follow when it arrives
  (measure the breakout: SparkFun / Pimoroni / generic).

## XIAO link (camera, mic)
- **Wires:** UART2 at 2 Mbps (both ends are S3s), plus the XIAO's EN (reset) and BOOT (GPIO0), driven open-drain by the main S3.
- **Messages:** short text lines, as the drive firmware already does on Serial: from the XIAO `face x y size`,
  `motion`, `loud`; to it `cam on/off`, `snap`. Small, easy to log, and a future brain can listen in.
- **Updating the XIAO through Popm:** the main S3 holds BOOT low and pulses EN to put the XIAO in its ROM bootloader, then
  streams a new XIAO firmware over the same UART (the esptool protocol, ESP's serial-flasher library). One update
  from the phone then covers both chips, with no USB cable into the chest.
- **Power:** 5 V from the board's buck, so the XIAO is reset with the robot. Optionally a load switch on a GPIO to turn the
  camera off when it isn't needed (saves ~0.3 A).
- **Pictures:** UART is enough for events and the odd still photo (a 20 KB JPEG in ~0.1 s). A live video stream should come
  straight from the XIAO's own Wi-Fi, joined to Popm's network, not through the main board.

## 5 V buck: checked against the TPS54202 datasheet (its SPICE model is encrypted: TI's tools only)
- Output: 0.596 V × (1 + 82k / 10k) = 5.48 V.
- Crossover (datasheet eq. 14): fo ≈ 3.95 / (Vout × Cout) = 3.95 / (5.48 V × ~40 µF) ≈ 18 kHz, under the 40 kHz limit.
  Cout: 3 × 22 µF 0805, ~13 µF each at 5.5 V bias.
- Feed-forward cap (eq. 16): 1 / (2π × 18 kHz × 82 kΩ) ≈ 108 pF → 100 pF.
- Inductor: 15 µH, as Table 7-2 for 5 V. Near 90 % duty (2S, nearly flat) a peak-current-mode buck leans on its slope
  compensation; 10 µH thinned that margin. Ripple 0.5 A at 16.8 V in; peak ~2 A at the rail's ~1.7 A, under 2.7 A sat.

## Check by hand before ordering
- **Servo plug pin order:** pin 1 DATA, 2 VBAT, 3 GND, taken from Waveshare's Bus Servo Adapter (A) schematic. Worth a
  multimeter check on a real lead (black wire = GND) against the plug's latch side before the first power-up.
- **STS3215 bus level:** the buffer drives 3.3 V. If the servos' input wants a 5 V high, a 5 V buffer is needed. Nothing gets
  damaged either way (the buffer's inputs and its off outputs take 5 V).
- **ToF breakout pinout** against the TOF connector, and whether the XIAO's EN / BOOT are reachable on its pads.
- **USB-only power:** VBUS minus the Schottky leaves ~4.3 V for the AMS1117 (dropout ~1.1 V): Wi-Fi peaks may brown out
  the S3 on the bench without the battery. On the battery (5.4 V buck) it's fine.

## Open questions
- **Servos:** decided 2026-11-04: Feetech STS3215, 12 V version (bought). Firmware needs the Feetech SCS/STS protocol
  (1 Mbps; position, speed and load registers) in place of Dynamixel 2.0.
- **Camera on the board:** fold the camera into the S3 (DVP camera connector) and drop the XIAO? Probably not: the camera
  is in the chest, the board is at the back, and a DVP flex cable that long is fragile.
