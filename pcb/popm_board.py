# Popm controller board, rev A: the schematic as code (SKiDL). Spec: README.md.
#   .venv/bin/python popm_board.py      -> popm_board.net (KiCad netlist) + ERC
# Every part carries its LCSC number (JLCPCB assembly). Passives 0603 unless noted, so they can be hand-reworked.
import os
os.environ.setdefault("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
os.environ.setdefault("KICAD9_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
from skidl import *

set_default_tool(KICAD9)
lib_search_paths[KICAD9].append(os.environ["KICAD9_SYMBOL_DIR"])

# ---- helpers ------------------------------------------------------------------------------------------------------
R_LCSC = {"47": "C23182", "1k": "C21190", "1.5k": "C22843", "2.2k": "C4190", "5.1k": "C23186", "10k": "C25804", "12.4k": "C22865",
          "18k": "C25810", "82k": "C23254", "22k": "C31850", "27k": "C22967", "100k": "C25803"}
C_LCSC = {"100p": ("C14858", "0603"), "100n": ("C14663", "0603"), "1u": ("C15849", "0603"), "4.7n": ("C53987", "0603"),
          "10u": ("C15850", "0805"), "22u": ("C45783", "0805")}

# 0402 where JLC has the value as a basic part (room to route: 0603 made the board too full); the rest stay 0603
R_0402 = {"120": "C25079", "330k": "C25778", "1k": "C11702", "1.5k": "C25867", "2.2k": "C25879", "5.1k": "C25905", "10k": "C25744", "100k": "C25741"}
C_0402 = {"100n": "C1525"}                       # 16 V: only off the battery / charger nets (a full 4S is 16.8 V)
HV = {"VBAT", "VBAT_FET", "BAT_RAW"}
def R(v, a, b):
    small = v in R_0402
    r = Part("Device", "R", value=v, footprint="Resistor_SMD:" + ("R_0402_1005Metric" if small else "R_0603_1608Metric"),
             LCSC=R_0402[v] if small else R_LCSC[v])
    r[1] += a; r[2] += b
    return r

def C(v, a, b, hv=False):
    lcsc, size = C_LCSC[v]
    names = {getattr(x, "name", None) or getattr(getattr(x, "net", None), "name", None) for x in (a, b)}
    if v in C_0402 and not (names & HV): lcsc, size = C_0402[v], "0402"
    if hv: lcsc, size = "C13585", "1206"   # 10 uF 50 V X5R: a 25 V 0805 keeps only ~2-3 uF at 16.8 V (DC bias)
    fp = {"0402": "Capacitor_SMD:C_0402_1005Metric", "0603": "Capacitor_SMD:C_0603_1608Metric", "0805": "Capacitor_SMD:C_0805_2012Metric",
          "1206": "Capacitor_SMD:C_1206_3216Metric"}[size]
    c = Part("Device", "C", value=v, footprint=fp, LCSC=lcsc)
    c[1] += a; c[2] += b
    return c

def so8_fet(sym, val, lcsc):
    """A MOSFET in SO-8 (S = 1-3, G = 4, D = 5-8: AO4407A, AO4406A): the 3-pin symbol, renumbered and widened to 8 pins."""
    q = Part("Transistor_FET", sym, value=val, footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", LCSC=lcsc)
    q["G"].num, q["S"].num, q["D"].num = "4", "1", "5"
    q.add_pins(*[Pin(num=n, name=nm, func=Pin.types.PASSIVE) for n, nm in (("2", "S"), ("3", "S"), ("6", "D"), ("7", "D"), ("8", "D"))])
    for n in "23": q[n] += q["1"]
    for n in "678": q[n] += q["5"]
    return q

def conn(n, fp, lcsc, nets, val):
    j = Part("Connector_Generic", f"Conn_01x{n:02d}", footprint=fp, LCSC=lcsc, value=val)
    for i, net in enumerate(nets, 1): j[i] += net
    return j

# ---- nets ---------------------------------------------------------------------------------------------------------
gnd = Net("GND"); gnd.drive = POWER
bat_raw = Net("BAT_RAW")       # the pack's +, straight from its plug (a power switch, if any, goes in the pack's lead)
vbat = Net("VBAT"); vbat.drive = POWER   # protected battery: servos, buck
v5 = Net("+5V"); v5.drive = POWER
v3 = Net("+3V3"); v3.drive = POWER
vbus = Net("VBUS")

# ---- power in: pack, switch, reverse-polarity FET, fuse, TVS --------------------------------------------------------
# No power switch and no charge port on the board (as Waveshare's servo HAT): the user switches / charges the pack in its
# own lead. The pack has its own BMS (short / over-discharge / over-charge).
# The refs they had (J2, J3, U1, Q2, C2, C3, R4, R5, C5) stay unused: the layout / routing scripts name parts by ref, so
# a placeholder takes each number here and is dropped from the circuit at the end of the file.
GONE = []
def gone(lib, name): GONE.append(Part(lib, name, footprint="Resistor_SMD:R_0402_1005Metric"))
conn(2, "Connector_AMASS:AMASS_XT30PW-M_1x02_P2.50mm_Horizontal", "C431092", [gnd, bat_raw], "BATTERY")   # pad 2 = +
gone("Connector_Generic", "Conn_01x02")   # J2
q_rp = so8_fet("Q_PMOS_GSD", "AO4407A", "C2841482")
vfet = Net("VBAT_FET")
q_rp["5"] += bat_raw; q_rp["1"] += vfet          # pack backwards: the gate sits above the source, the FET stays off
gate = Net("RP_GATE")
q_rp["4"] += gate
R("10k", gate, gnd)
z = Part("Device", "D_Zener", value="BZT52C12", footprint="Diode_SMD:D_SOD-123", LCSC="C173429")
z["K"] += vfet; z["A"] += gate                   # holds Vgs under 12 V on spikes
f = Part("Device", "Polyfuse", value="5A hold 30V", footprint="Fuse:Fuse_2920_7451Metric", LCSC="C19078763")   # 30 V: 4S packs
f[1] += vfet; f[2] += vbat
tvs = Part("Device", "D_TVS", value="SMBJ18A", footprint="Diode_SMD:D_SMB", LCSC="C151256")   # 18 V standoff: above a full 4S (16.8 V), clamps < 30 V (the buck's max)
tvs[1] += vbat; tvs[2] += gnd
cb = Part("Device", "C_Polarized", value="100u 35V", footprint="Capacitor_SMD:CP_Elec_6.3x7.7", LCSC="C72478")
cb[1] += vbat; cb[2] += gnd

gone("Connector_Generic", "Conn_01x02"); gone("Power_Management", "LM74700"); gone("Transistor_FET", "Q_NMOS_GDS")   # J3, U1, Q2
gone("Device", "C"); gone("Device", "C")   # C2, C3

# ---- sense: battery (ADC1, 100k / 18k: 16.8 V (4S full) -> 2.56 V, 8.4 V (2S) -> 1.28 V) ---------
vb_s = Net("VBAT_SENSE")
R("100k", vbat, vb_s); R("18k", vb_s, gnd); C("100n", vb_s, gnd)
gone("Device", "R"); gone("Device", "R"); gone("Device", "C")   # R4, R5, C5

# ---- 5 V: buck from VBAT (5.4 V, then a Schottky OR with USB) --------------------------------------------------------
buck = Part("Regulator_Switching", "TPS54202DDC", footprint="Package_TO_SOT_SMD:SOT-23-6", LCSC="C191884")
sw, fb, boot, v5b = Net("BUCK_SW"), Net("BUCK_FB"), Net("BUCK_BOOT"), Net("+5V4")
buck["VIN"] += vbat; buck["GND"] += gnd; buck["SW"] += sw; buck["FB"] += fb; buck["BOOT"] += boot
en = Net("BUCK_EN")
buck["EN"] += en
R("330k", vbat, en); R("82k", en, gnd)           # TPS54202 eq. 1 / 2 (EN 1.21 / 1.19 V, 0.7 + 1.55 uA): on at ~5.85 V, off at
                                                  # ~5.25 V: 0.6 V of hysteresis (TI: > 0.5 V), so a sagging 2S pack can't make it cycle
C("10u", vbat, gnd); C("10u", vbat, gnd, hv=True); C("100n", vbat, gnd)   # C6 0805 25 V (the hot loop's pads line up with U2's:
                                                  # preroute.py), C7 1206 50 V: TI wants > 10 uF of ceramic left at VIN
C("100n", boot, sw)
# 15 uH, as TI's Table 7-2 for 5 V: a peak-current-mode buck near 90 % duty (2S, nearly flat) needs the inductor's
# down-slope small against its internal slope compensation; 10 uH thinned that margin. 2.7 A sat, 2.05 A rms (rail ~1.7 A peak)
l = Part("Device", "L", value="15u", footprint="Inductor_SMD:L_Cenker_CKCS6045", LCSC="C83374")   # SWPA6045S150MT, 6x6
l[1] += sw; l[2] += v5b
R("82k", v5b, fb); R("10k", fb, gnd)             # 0.596 V x (1 + 82 / 10) = 5.48 V (basic-part values)
C("22u", v5b, gnd); C("22u", v5b, gnd)          # (+ a third and a feed-forward cap at the end of the file)
d1 = Part("Device", "D_Schottky", value="SS34", footprint="Diode_SMD:D_SMA", LCSC="C8678")
d1["A"] += v5b; d1["K"] += v5
d2 = Part("Device", "D_Schottky", value="SS34", footprint="Diode_SMD:D_SMA", LCSC="C8678")
d2["A"] += vbus; d2["K"] += v5                    # USB powers the logic on the bench (servos stay off)
C("22u", v5, gnd)

# ---- 3.3 V: LDO from 5 V (average ~0.2 A; Wi-Fi peaks are short) --------------------------------------------------
ldo = Part("Regulator_Linear", "AMS1117-3.3", footprint="Package_TO_SOT_SMD:SOT-223-3_TabPin2", LCSC="C6186")
ldo["VI"] += v5; ldo["VO"] += v3; ldo["GND"] += gnd
C("22u", v5, gnd); C("22u", v3, gnd); C("22u", v3, gnd)

# ---- ESP32-S3 ------------------------------------------------------------------------------------------------------
u = Part("RF_Module", "ESP32-S3-WROOM-1", value="ESP32-S3-WROOM-1-N16R8", LCSC="C2913202")
u["3V3"] += v3; u["GND"] += gnd
C("10u", v3, gnd); C("100n", v3, gnd); C("100n", v3, gnd)
en_n = Net("EN")
u["EN"] += en_n; R("10k", v3, en_n); C("1u", en_n, gnd)
io0 = Net("BOOT")
u["IO0"] += io0; R("10k", v3, io0)
for net, fp_name in ((en_n, "RESET"), (io0, "BOOT")):
    b = Part("Switch", "SW_Push", value=fp_name, footprint="Button_Switch_SMD:SW_SPST_TS-1088-xR020", LCSC="C720477")   # 4 x 3 mm
    b[1] += net; b[2] += gnd

# USB-C: native USB (flash, log), 5 V in
usb = Part("Connector", "USB_C_Receptacle_USB2.0_16P", footprint="Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", LCSC="C165948")
dm, dp = Net("USB_D-"), Net("USB_D+")
usb["VBUS"] += vbus; usb["GND"] += gnd; usb["SHIELD"] += gnd
usb["D-"] += dm; usb["D+"] += dp
R("5.1k", usb["CC1"], gnd); R("5.1k", usb["CC2"], gnd)
esd = Part("Power_Protection", "USBLC6-2SC6", footprint="Package_TO_SOT_SMD:SOT-23-6", LCSC="C2687116")
esd["VBUS"] += vbus; esd["GND"] += gnd
esd[1] += dm; esd[6] += dm; esd[3] += dp; esd[4] += dp
u["USB_D-"] += dm; u["USB_D+"] += dp

# ---- servo bus: half duplex, one DIR pin (the Robotis circuit; Feetech's SCS bus is the same at 1 Mbps) ---------------------------------------------------------
# 74LVC2G241: 1OE (pin 1, active low) + 2OE (pin 7, active high) both on DIR: DIR 0 = transmit, 1 = receive
bus, tx, rx, dirn = Net("SERVO_DATA"), Net("SERVO_TX"), Net("SERVO_RX"), Net("SERVO_DIR")
buf = Part("74xGxx", "74LVC2G241", footprint="Package_SO:VSSOP-8_2.3x2mm_P0.5mm", LCSC="C10430")
buf["VCC"] += v3; buf["GND"] += gnd
buf[1] += dirn; buf[7] += dirn
buf[2] += tx                                      # 1A
bus_drv = Net("SERVO_DRV")
buf[6] += bus_drv                                 # 1Y
R("47", bus_drv, bus)                             # a short on the bus can't kill the buffer
buf[5] += bus                                     # 2A (5 V tolerant)
buf[3] += rx                                      # 2Y
R("10k", v3, bus); R("10k", v3, rx)
C("100n", v3, gnd)
u["IO17"] += tx; u["IO18"] += rx; u["IO16"] += dirn
# Feetech STS3215 (12 V version): each servo has two ports, so they daisy-chain: one plug for the wheels, one for the head.
# Molex SPOX 5267 (the plug the servos' own leads use). Pin 1 DATA, 2 VCC, 3 GND: as Waveshare's Bus Servo Adapter (A)
# (H3 / H5 in its schematic, files.waveshare.com/wiki/Bus-Servo-Adapter-(A)/Bus Servo Adapter (A)-Sch.pdf). Reversed,
# the servo's ground current would run into the data line.
for name in ("SERVO1", "SERVO2"):                  # e.g. one chain for the drive, one for a head
    conn(3, "Connector_Molex:Molex_SPOX_5267-03A_1x03_P2.50mm_Vertical", "C293315", [bus, vbat, gnd], name)

# ---- eye bus (I2C1, 1 MHz) -------------------------------------------------------------------------------------------
esda, escl = Net("I2C_B_SDA"), Net("I2C_B_SCL")   # bus B: nothing on board; two plugs + Pi pins 27 / 28 (was the displays')
u["IO4"] += esda; u["IO5"] += escl
R("1.5k", v3, esda); R("1.5k", v3, escl)
SH4 = "Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal"
SH6 = "Connector_JST:JST_SH_SM06B-SRSS-TB_1x06-1MP_P1.00mm_Horizontal"
for name in ("I2C_B1", "I2C_B2"):                 # a free bus (e.g. displays). Qwiic order: GND, 3V3, SDA, SCL
    conn(4, SH4, "C160404", [gnd, v3, esda, escl], name)

# ---- sensor bus (I2C0): IMU, ToF, Qwiic spare -------------------------------------------------------------------------
ssda, sscl = Net("I2C_A_SDA"), Net("I2C_A_SCL")   # bus A: the IMU, ToF, expander on it; Qwiic + Pi pins 3 / 5
u["IO6"] += ssda; u["IO7"] += sscl
R("2.2k", v3, ssda); R("2.2k", v3, sscl)
imu = Part("Sensor_Motion", "LSM6DS3", value="LSM6DS3TR-C", LCSC="C967633")
imu["VDD"] += v3; imu["VDDIO"] += v3; imu["GND"] += gnd
imu["CS"] += v3                                   # I2C mode
imu["SDO/SA0"] += gnd                             # address 0x6A
imu["SDA"] += ssda; imu["SCL"] += sscl
imu["SDX"] += gnd; imu["SCX"] += gnd
imu_int = Net("IMU_INT"); imu["INT1"] += imu_int; u["IO15"] += imu_int
C("100n", v3, gnd); C("100n", v3, gnd)
tof_lpn, tof_int = Net("TOF_LPN"), Net("TOF_INT")
u["IO14"] += tof_int                             # (LPn: on the expander, P16, at the end of the file)
R("10k", v3, tof_lpn); R("10k", v3, tof_int)    # on unless held off; INT is open drain
conn(6, SH6, "C160405", [gnd, v3, ssda, sscl, tof_lpn, tof_int], "TOF")
conn(4, SH4, "C160404", [gnd, v3, ssda, sscl], "QWIIC")
C("10u", v3, gnd)                                 # the ToF draws ~0.1 A in bursts

# ---- sound: MAX98357A on 5 V ---------------------------------------------------------------------------------------
amp = Part("Audio", "MAX98357A", value="MAX98357AETE+T", LCSC="C910544")
amp["PAD"].func = Pin.types.PASSIVE   # the exposed pad: ground
amp["VDD"] += v5; amp["GND"] += gnd; amp["PAD"] += gnd
bclk, lrc, din, sd = Net("I2S_BCLK"), Net("I2S_LRC"), Net("I2S_DIN"), Net("AMP_SD")
amp["BCLK"] += bclk; amp["LRCLK"] += lrc; amp["DIN"] += din
u["IO10"] += bclk; u["IO11"] += lrc; u["IO12"] += din; u["IO9"] += sd
R("10k", sd, amp["~{SD_MODE}"])                   # GPIO high: ~3 V on the pin (its 100k pull-down) = left channel; low = shutdown
C("10u", v5, gnd); C("100n", v5, gnd)
sp_p, sp_n = Net("SPK+"), Net("SPK-")
amp["OUTP"] += sp_p; amp["OUTN"] += sp_n          # GAIN_SLOT floating: 9 dB, as on the breakout now
conn(2, "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "C131337", [sp_p, sp_n], "SPEAKER")

# ---- XIAO camera link: UART2 + its EN / BOOT (open drain from here: it can be reset and reflashed) ----------------------
xtx, xrx, xen, xboot = Net("UART_TX"), Net("UART_RX"), Net("AUX_EN"), Net("AUX_BOOT")
u["IO39"] += xtx; u["IO40"] += xrx               # (EN / BOOT: on the expander, P14 / P15, at the end: IO41 / IO42 are CAN now)
conn(6, SH6, "C160405", [gnd, v5, xtx, xrx, xen, xboot], "UART")   # any serial device / co-processor (e.g. a XIAO camera): its EN / BOOT too

# ---- status LED, battery and charger sense -----------------------------------------------------------------------------
u["IO1"] += vb_s; u["IO2"] += NC   # (IO2 was the charger-present sense: free)

# ---- debug / spare: test pads (console UART, spare GPIO), no connector ------------------------------------------------
rs_tx, rs_rx = Net("RS485_TX"), Net("RS485_RX")    # UART0: the RS485 chip now (the console is on USB)
for n, pin in ((rs_tx, "TXD0"), (rs_rx, "RXD0")):
    u[pin] += n
    tp = Part("Connector", "TestPoint", value=n.name, footprint="TestPoint:TestPoint_Pad_D1.0mm")
    tp[1] += n
for n in (gnd, v3):
    Part("Connector", "TestPoint", value=n.name, footprint="TestPoint:TestPoint_Pad_D1.0mm")[1] += n

# ---- unused module pins: explicitly not connected -------------------------------------------------------------------
for p in ("IO35", "IO36", "IO37", "IO45"):   # IO45: the flash-voltage strap (a HAT pulling it high would stop the boot)
    u[p] += NC
for p in ("NC",):
    for pin in imu.get_pins(p) or []: pin += NC
imu["INT2"] += NC
for pin in amp.get_pins("NC") or []: pin += NC
amp["GAIN_SLOT"] += NC
usb["SBU1"] += NC; usb["SBU2"] += NC

# ---- mounting: 4 x M2.5 (layout.py places them), bare (no copper: two sit next to the antenna) --------------------------------
for _ in range(4):
    Part("Mechanical", "MountingHole", footprint="MountingHole:MountingHole_3mm")   # Pi / HAT holes: M2.5 screws, 3 mm NPTH

# ---- added after the schematic review (kept last: SKiDL numbers parts in creation order, and layout.py maps refs) -----
C("100p", v5b, fb)                                # C26: feed-forward across the top FB resistor (TPS54202 datasheet: 75 pF
                                                  # with 100k; 100 pF with 82k puts the zero within ~10 % of it, and is basic)
C("22u", v5b, gnd)                                # C27: 22 uF 0805 is ~10 uF at 5.4 V, so three on the buck output
R("10k", v3, dirn)                                # R24: GPIO16 floats through reset / flashing: default to receive

# ---- status LED: a plain red one on GPIO48 (high = on; ~1.3 mA through 1k). Was a WS2812B-2020: JLC flags it as hard
# to assemble, and inside the body nobody sees its colours. Created here (last) so the other parts keep their numbers.
led_a = Net("LED_A")
R("1k", u["IO48"], led_a)
led = Part("Device", "LED", value="red", footprint="LED_SMD:LED_0603_1608Metric", LCSC="C2286")
led["A"] += led_a; led["K"] += gnd

# ---- bring-up test pads (added after the layout review; last, so nothing else renumbers): TP5-TP7
for n in (vbat, v5, en_n):
    Part("Connector", "TestPoint", value=n.name, footprint="TestPoint:TestPoint_Pad_D1.0mm")[1] += n

# ---- POPM-HAT (65 x 57, Raspberry Pi HAT size): a Pi-style 2 x 20 header, a microSD on SPI, a 16-bit I2C GPIO expander.
# Created last, so every part above keeps its number (layout.py maps refs).
spi_mosi, spi_miso, spi_sck, sd_cs = (Net(n) for n in ("SPI_MOSI", "SPI_MISO", "SPI_SCK", "SD_CS"))
u["IO38"] += spi_mosi; u["IO47"] += spi_miso; u["IO21"] += spi_sck; u["IO13"] += sd_cs   # CS: a right-side pin, by the slot
u["IO3"] += NC; u["IO46"] += NC                   # (were header-only: SPI CE0, I2S in; IO3 / IO46 are straps, left alone)
# Pi header: FEMALE, underneath: this board sits on a Raspberry Pi. Pin numbers are the Pi's, each pad right above the Pi's pin
# (odd row inside, even row on the edge). The Pi and the ESP never drive the same line: 3V3, I2C, SPI, I2S and the ID EEPROM
# pins are left open; the Pi gets a UART to the ESP, the ESP's reset / boot, and the expander's 12 lines.
hdr = Part("Connector_Generic", "Conn_02x20_Odd_Even", value="PI_HDR", footprint="Connector_PinSocket_2.54mm:PinSocket_2x20_P2.54mm_Vertical", LCSC="C5124634")
exp = Part("Interface_Expansion", "TCA9555PWR", value="TCA9555PWR", footprint="Package_SO:TSSOP-24_4.4x7.8mm_P0.65mm", LCSC="C465732")
exp_nets = {f"P{k}": Net(f"EXP_P{k}") for k in ("00 01 02 03 04 05 06 07 10 11 12 13 17".split())}
exp_nets |= {"P14": xen, "P15": xboot, "P16": tof_lpn}   # slow on / off lines moved off the ESP to free IO41 / 42 / 13 for CAN /
# RS485. The expander's pins come up as inputs (high-Z): the XIAO's EN / BOOT keep its own pull-ups, LPn its 10k (ToF on)
pi5, pi_tx, pi_rx, pi_en, pi_boot = (Net(n) for n in ("PI_5V", "PI_TXD", "PI_RXD", "PI_EN", "PI_BOOT"))
PI = {2: pi5, 4: pi5, 8: pi_tx, 10: pi_rx, 11: pi_en, 13: pi_boot}
for n in (1, 17, 3, 5, 27, 28, 12, 35, 38, 40, 19, 21, 23, 24): PI[n] = NC
for n in (6, 9, 14, 20, 25, 30, 34, 39): PI[n] = gnd
# the Pi's otherwise unused pins: the expander, port 0 then port 1 in order along the header
for n, pn in zip((7, 15, 16, 18, 22, 26, 29, 31, 32, 33, 36, 37), "00 01 02 03 04 05 06 07 10 11 12 13".split()): PI[n] = exp_nets["P" + pn]
assert len(PI) == 40
for n, net in PI.items(): hdr[n] += net
# expander: sensor bus, address 0x20 (A0-A2 low; the IMU is 0x6A, the ToF 0x29). INT has no free GPIO: pulled up, on a pad (poll)
exp["VCC"] += v3; exp["GND"] += gnd; exp["SDA"] += ssda; exp["SCL"] += sscl
for a in ("A0", "A1", "A2"): exp[a] += gnd
EXP_PIN = dict(zip("P00 P01 P02 P03 P04 P05 P06 P07 P10 P11 P12 P13 P14 P15 P16 P17".split(), (*range(4, 12), *range(13, 21))))
for k, net in exp_nets.items(): exp.p[EXP_PIN[k]] += net   # by number: SKiDL's name match is loose (P1 hits P10-P17)
exp_int = Net("EXP_INT"); exp["~{INT}"] += exp_int
C("100n", v3, gnd); R("10k", v3, exp_int)
# microSD (SPI mode): Molex 104031-0811 (pads 1-8 the card, 9 / 10 its detect switch (unused), 11 the shell)
sd_d1, sd_d2 = Net("SD_DAT1"), Net("SD_DAT2")
sd = conn(11, "Connector_Card:microSD_HC_Molex_104031-0811", "C585350",
          [sd_d2, sd_cs, spi_mosi, v3, spi_sck, gnd, spi_miso, sd_d1, NC, NC, gnd], "MICROSD")
for n in (sd_cs, spi_mosi, spi_miso, sd_d1, sd_d2): R("10k", v3, n)
C("10u", v3, gnd); C("100n", v3, gnd)
for n in (exp_nets["P17"], exp_int):
    Part("Connector", "TestPoint", value=n.name, footprint="TestPoint:TestPoint_Pad_D1.0mm")[1] += n

# ---- CAN (the ESP's TWAI controller) and RS485 (UART0, half duplex), each on a JST-GH 4 (DroneCAN's order: 5V, H, L, GND).
# Each end has a 120R terminator behind a solder jumper (bridge it on the boards at the two ends of the bus) and a TVS.
can_tx, can_rx, canh, canl = Net("CAN_TX"), Net("CAN_RX"), Net("CANH"), Net("CANL")
u["IO41"] += can_tx; u["IO42"] += can_rx
can = Part("Interface_CAN_LIN", "SN65HVD230", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", LCSC="C12084")
can["D"] += can_tx; can["R"] += can_rx; can["CANH"] += canh; can["CANL"] += canl
can["VCC"] += v3; can["GND"] += gnd; can["Rs"] += gnd; can["Vref"] += NC   # Rs low: full speed (no slope control)
C("100n", v3, gnd); R("10k", v3, can_tx)          # TX floats through reset: held recessive, not jamming the bus
rs_de, rs_a, rs_b = Net("RS485_DE"), Net("RS485_A"), Net("RS485_B")
u["IO8"] += rs_de                                 # a bottom-row pin, by the chip (IO13 boxed in there)
rs = Part("Interface_UART", "SP3485EN", footprint="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", LCSC="C8963")
rs["DI"] += rs_tx; rs["RO"] += rs_rx; rs["DE"] += rs_de; rs["~{RE}"] += rs_de; rs["A"] += rs_a; rs["B"] += rs_b
rs["VCC"] += v3; rs["GND"] += gnd
C("100n", v3, gnd); R("10k", rs_de, gnd)          # DE low through reset: the boot log on TX never reaches the bus
JP = lambda: Part("Jumper", "SolderJumper_2_Open", value="TERM", footprint="Jumper:SolderJumper-2_P1.3mm_Open_Pad1.0x1.5mm")
for h, l, tvs, code in ((canh, canl, "PESD2CAN", "C75176"), (rs_a, rs_b, "SM712", "C521963")):
    t = Net(h.name + "_TERM"); R("120", h, t); j = JP(); j[1] += t; j[2] += l
    d = Part("Diode", "SM712_SOT23", value=tvs, footprint="Package_TO_SOT_SMD:SOT-23", LCSC=code)   # both: 2 lines -> pin 3
    d[1] += h; d[2] += l; d[3] += gnd
GH4 = "Connector_JST:JST_GH_BM04B-GHS-TBT_1x04-1MP_P1.25mm_Vertical"
conn(4, GH4, "C161692", [v5, canh, canl, gnd], "CAN")
conn(4, GH4, "C161692", [v5, rs_a, rs_b, gnd], "RS485")

# ---- the Pi side of the header (created last: nothing above renumbers) ----------------------------------------------------
# Pi 5V -> our 5V through a Schottky: the Pi can run the ESP side; the battery never feeds the Pi (the 2 A buck can't run one)
dp = Part("Device", "D_Schottky", value="SS34", footprint="Diode_SMD:D_SMA", LCSC="C8678"); dp["A"] += pi5; dp["K"] += v5
# the Pi's UART, crossed (its TXD, pin 8, into the ESP's RX), through 1k: neither side back-powers the other while it's off. The
# same ESP UART goes to the UART plug: use one or the other.
R("1k", pi_tx, xrx); R("1k", xtx, pi_rx)
# the Pi resets / boot-selects the ESP: a 2N7002 each (Pi pin high = held low). A Pi that's off leaves them off (100k
# pull-downs; GPIO17 / 27 also pull down at boot), so it never holds the ESP in reset
for g_, d_ in ((pi_en, en_n), (pi_boot, io0)):
    q = Part("Transistor_FET", "2N7002", footprint="Package_TO_SOT_SMD:SOT-23", LCSC="C8545")
    q["G"] += g_; q["D"] += d_; q["S"] += gnd; R("100k", g_, gnd)

assert [p.ref for p in GONE] == "J2 J3 U1 Q2 C2 C3 R4 R5 C5".split(), [p.ref for p in GONE]
default_circuit.rmv_parts(*GONE)

if __name__ == "__main__":
    ERC()
    for q in buck.circuit.parts:          # SKiDL keeps LCSC= as an attribute; only .fields reach the netlist (BOM, PDF)
        if getattr(q, "LCSC", None): q.fields["LCSC"] = q.LCSC
    generate_netlist(file_="popm_board.net")
