# Baunuri HAT

A robot controller board the size of a Raspberry Pi HAT (65 × 57 mm, the Pi's hole pattern and 40-pin header), built
around an ESP32-S3. It runs a robot on its own, or sits on a Pi when a robot needs more compute.

It was designed for [Popm](https://baunuri.com/popm/) and now also runs [XL-Duck](https://baunuri.com/xlduck/), whose
trained walking network runs on the ESP32-S3 itself. More: [baunuri.com/hat](https://baunuri.com/hat/).

## On the board
- **MCU:** ESP32-S3-WROOM-1-N16R8 (16 MB flash, 8 MB PSRAM), native USB-C for flashing and logs
- **Servos:** two half-duplex TTL servo bus plugs (Feetech STS3215 pinout), powered straight from the battery
- **RS485** (SP3485, UART0, DE on a GPIO) and **CAN** (SN65HVD230), each with a terminator behind a solder jumper
- **IMU:** LSM6DS3TR-C
- **Sound:** MAX98357A I2S amp, speaker plug
- **microSD** (SPI), **TCA9555** 16-bit I/O expander, two I2C buses (sensor plugs, ToF plug, Qwiic)
- **Power:** 2S–4S battery in (XT30), reverse-polarity FET, fuse, TVS; 5.4 V / 2 A buck, 3.3 V LDO; battery voltage sense
- **Pi header:** UART to the Pi, the Pi can reset the ESP32 or put it into its bootloader; the Pi's 5 V can run the logic,
  the battery never feeds the Pi

Full spec, pin map, power budget and design notes: [`pcb/README.md`](pcb/README.md). Pin map in code:
[`firmware/hat_bringup/board_hat.h`](firmware/hat_bringup/board_hat.h).

## Status
**Rev A**, ordered assembled from JLCPCB in November 2026 and brought up: the bring-up sketch
(`firmware/hat_bringup/`) tests each part over USB. An STS3215 runs on the servo bus at 1 Mbps (position within ~0.4°,
286°/s peak once its acceleration limit, register 85, is raised from the factory 50). XL-Duck's servos run on the RS485
port at 1 Mbps.

## Files
| Path | What |
|---|---|
| `pcb/popm_board.py` | the schematic, as code ([SKiDL](https://github.com/devbisme/skidl)) → netlist |
| `pcb/popm_board.kicad_pcb` | the layout (KiCad 9) |
| `pcb/layout.py`, `route.py`, `stitch.py`, `silk.py`, … | placement / routing / stitching / silkscreen scripts |
| `pcb/fab/` | what was ordered: Gerbers (zip), BOM and placement (CPL) for JLCPCB assembly, schematic PDF |
| `firmware/hat_bringup/` | the pin map (`board_hat.h`) and a bring-up sketch (Arduino, ESP32 core) |

## Making one
Upload `pcb/fab/popm_gerbers.zip` to JLCPCB with `popm_bom.csv` and `popm_cpl.csv` for assembly. **4 layers, 1.6 mm,
1 oz outer and 1 oz inner copper** (not the 0.5 oz inner default). The 2 × 20 Pi socket (J13) isn't in the BOM: solder a
tall stacking header yourself if you'll use a Pi. Check the notes in `pcb/README.md` ("Check by hand") first.

Or get a ready-made one: see [baunuri.com/hat](https://baunuri.com/hat/#get-one).

## Licenses
- **Hardware** (`pcb/`): [CERN-OHL-S-2.0](LICENSE), strongly reciprocal: if you make and distribute a modified board,
  publish its design files under the same licence.
- **Firmware** (`firmware/`): [MIT](firmware/LICENSE).
- **Documentation and images:** [CC BY 4.0](LICENSE-docs).

"Baunuri" and "Baunuri HAT" are names, not covered by these licences: boards you make from these files are welcome, but
please don't sell them under those names.
