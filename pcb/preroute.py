# Hand-drawn tracks for the buck's power loops, locked so route.py / Freerouting keep them (after layout.py).
#   .venv/bin/python preroute.py
# The loops that switch fast (input cap -> VIN / GND, SW -> inductor, boot cap) are short and on the top layer. The
# SW track has to pass between U2's GND pin and C6's GND pad, so those two GND pads drop straight into the GND plane
# (inner layer 1, right under the top) with vias of their own.
import os, pcbnew
mm = pcbnew.FromMM
b = pcbnew.LoadBoard("popm_board.kicad_pcb")
from board import X0, Y0, W, H, CORNER_R, ANT
P = lambda ref, n: next((q.GetPosition() for q in b.FindFootprintByReference(ref).Pads() if q.GetNumber() == n))
V = lambda x, y: pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y))
xy = lambda p: (pcbnew.ToMM(p.x) - X0, pcbnew.ToMM(p.y) - Y0)

for t in [t for t in b.GetTracks() if t.IsLocked()]: b.Remove(t)   # re-runnable

def track(net, w, *pts, layer=pcbnew.F_Cu):
    for a, c in zip(pts, pts[1:]):
        t = pcbnew.PCB_TRACK(b); t.SetStart(V(*a)); t.SetEnd(V(*c)); t.SetWidth(mm(w)); t.SetLayer(layer)
        t.SetNet(b.FindNet(net)); t.SetLocked(True); b.Add(t)

def via(net, x, y, d=0.6, drill=0.3):
    v = pcbnew.PCB_VIA(b); v.SetPosition(V(x, y)); v.SetWidth(mm(d)); v.SetDrill(mm(drill)); v.SetNet(b.FindNet(net))
    v.SetLocked(True); b.Add(v)

vin, sw, gnd1, boot, en, fb = (xy(P("U2", n)) for n in "321654")
c6v, c6g = xy(P("C6", "1")), xy(P("C6", "2"))
c8v, c8g = xy(P("C8", "1")), xy(P("C8", "2"))
c7v = xy(P("C7", "1"))                    # 10 uF underneath
c9b, c9s = xy(P("C9", "1")), xy(P("C9", "2"))
l1s, l1o = xy(P("L1", "1")), xy(P("L1", "2"))
c10o = xy(P("C10", "1"))
# the placement this is drawn for (layout.py): U2 pins on the left at x 29.86, C6 upright left of them, L1 above
assert abs(c6v[1] - vin[1]) < 0.01 and abs(c6g[1] - gnd1[1]) < 0.01 and l1s[0] < sw[0] < l1o[0], "placement moved: redraw"

# input: C6 straight across to VIN, C8 (100 nF, closest to the pins) up into that track, C7 underneath through a via
track("VBAT", 0.6, c6v, vin)
track("VBAT", 0.6, c8v, (c8v[0], vin[1]))
# GND of U2, C6 and C8: vias into the plane right at the pads
track("GND", 0.5, gnd1, (gnd1[0], gnd1[1] - 1.0)); via("GND", gnd1[0], gnd1[1] - 1.0)   # (under the chip: C26 is below)
track("GND", 0.5, c6g, (c6g[0], c6g[1] - 1.05)); via("GND", c6g[0], c6g[1] - 1.05)
track("GND", 0.5, c8g, (c8g[0], c8g[1] + 1.0)); via("GND", c8g[0], c8g[1] + 1.0)
# IMU: pin 12 (CS, tied to +3V3; the bottom row) loops round the unused pins 9-11 to pin 8 (VDD), so SDA / SCL
# (pins 13, 14, next to it) keep the way out underneath (the router left pin 12 on its own)
p12, p8 = xy(P("U7", "12")), xy(P("U7", "8"))
xr = p8[0] + 0.7
track("+3V3", 0.25, p12, (p12[0], p12[1] + 0.6), (xr, p12[1] + 0.6), (xr, p8[1]), p8, layer=pcbnew.B_Cu)
def outward(ref, n, dist):                # the spot `dist` from a pin (up / down / left / right) furthest from its other pins
    px, py = xy(P(ref, n)); rest = [xy(q.GetPosition()) for q in b.FindFootprintByReference(ref).Pads() if q.GetNumber() != n]
    return max(((px + dx * dist, py + dy * dist) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))),
               key=lambda c: min((c[0] - x) ** 2 + (c[1] - y) ** 2 for x, y in rest))
# the expander's pins (TSSOP-24, both rows): a short stub straight out of each, so the links below can't seal a row in
u9 = b.FindFootprintByReference("U9"); cx9, cy9 = xy(u9.GetPosition())
for q in u9.Pads():
    if q.GetNetname() in ("", "GND"): continue
    px, py = xy(q.GetPosition())          # out of the row, never along it (rotated 90 / 270 the rows run left-right)
    rows_lr = round(u9.GetOrientationDegrees()) % 180 != 0
    sx, sy = (0, 1 if py > cy9 else -1) if rows_lr else (1 if px > cx9 else -1, 0)
    track(q.GetNetname(), 0.2, (px, py), (px + 1.6 * sx, py + 1.6 * sy), layer=pcbnew.B_Cu if u9.IsFlipped() else pcbnew.F_Cu)
# (the servo buffer's GND pin: the checked fan-out below. A fixed "0.8 mm out" via here landed in the FET's pad once the chip moved)
# IMU SDA / SCL (pins 14, 13: the bottom row, 0.5 mm apart): straight out to small staggered vias (the router couldn't
# get into the row)
assert b.FindFootprintByReference("U7").GetOrientationDegrees() == 0, "IMU rotated: redraw its escapes"
for n, out in (("14", 0.75), ("13", 1.35)):
    q = next(q for q in b.FindFootprintByReference("U7").Pads() if q.GetNumber() == n); px, py = xy(q.GetPosition())
    track(q.GetNetname(), 0.2, (px, py), (px, py + out), layer=pcbnew.B_Cu); via(q.GetNetname(), px, py + out, 0.45, 0.2)
# SW: out of pin 2 to the left, up the gap between U2's and C6's pads into L1
x_sw = sw[0] - 1.14
track("BUCK_SW", 0.5, sw, (x_sw, sw[1]), (x_sw, l1s[1] + 2.4))
# boot cap: BOOT -> C9, and C9's other end round the top of U2 to L1's SW pad
y_bs = l1s[1] + 3.3                       # 0.2 mm from L1's pads above and the GND via below
# output: L1 -> C10
# (L1 -> C10: a link below; where the packer puts C10 varies)

# ---- a few links the autorouter keeps failing, found here by a grid search (A*) while the board is still empty:
# the buck's VBAT feed, the two sense pins on battery nets (the battery class is 2 mm wide: no room to
# reach a small pin), and the speaker pair. Top / bottom, vias where needed (never in a pad), then locked.
import pathfind
def link(net, a, b_, w, clr=None, layers=(0, 1, 2), optional=False):   # the net's class clearance (pathfind: larger per obstacle)
    clr = clr if clr is not None else (0.2 if net in pathfind.WIDE_NETS else 0.13)
    pts = pathfind.find(b, net, ("pad", *a), ("pad", *b_), w, clr, vd=0.9 if w >= 1.5 else 0.6, layers=layers)   # the via size draw() puts
    if not pts and optional: print(f"  (no link {net} {a} -> {b_}: left to the router)"); return False
    if not pts: raise SystemExit(f"preroute: no path for {net} {a} -> {b_}")
    print(f"  link {net} {a[0]}.{a[1]} -> {b_[0]}.{b_[1]}: {len(pts)} points, {pathfind.draw(b, net, pts, w, *((0.9, 0.5) if w >= 1.5 else ()))} vias")
    return True
u3p = sorted((q for q in b.FindFootprintByReference("U3").Pads() if q.GetNumber() == "2"), key=lambda q: q.GetSize().x * q.GetSize().y)
track("+3V3", 1.0, xy(u3p[0].GetPosition()), xy(u3p[-1].GetPosition()),   # the LDO's middle pin to its tab ("2" both: joined inside
      layer=pcbnew.B_Cu if b.FindFootprintByReference("U3").IsFlipped() else pcbnew.F_Cu)   # it; KiCad wants them joined here too)

# USB-C: its two VBUS pad pairs (A4/B9, A9/B4) joined first: each straight up to a via, an In2 track between (outside the
# data pins, which still leave upwards between the vias). Drawn after the D+ / D- links, nothing could reach A4 any more.
vb = sorted({xy(q.GetPosition()) for q in b.FindFootprintByReference("J4").Pads() if q.GetNetname() == "VBUS"})
yb = vb[0][1] - 1.55
for x, y in vb: track("VBUS", 0.3, (x, y), (x, yb)); via("VBUS", x, yb)
track("VBUS", 0.3, (vb[0][0], yb), (vb[-1][0], yb), layer=pcbnew.In2_Cu)

# The links, in order: (net, pad, pad, width, must). Their order matters (an early link can wall a later one's pin in), so a
# must-have link that finds no path moves to the front and the links start over (from the board as it is here).
pin = lambda ref, net: next(q.GetNumber() for q in b.FindFootprintByReference(ref).Pads() if q.GetNetname() == net)
LINKS = [
    # the battery / servo trunk, 2 mm (5 A), outer layers preferred (inner copper is ordered at 1 oz too):
    # pack -> switch plug -> reverse-polarity FET -> fuse -> bulk cap -> both servo plugs
    ("BAT_RAW", ("J1", "2"), ("Q1", "5"), 2.0, True),
    ("VBAT_FET", ("Q1", "1"), ("F1", "1"), 2.0, True),
    # the charge path, 1 mm: port -> the ideal diode's FET (source) and its drain -> the pack side of the switch
    ("VBAT", ("F1", "2"), ("C1", "1"), 2.0, True),
    ("VBAT", ("C1", "1"), ("J6", "2"), 2.0, True), ("VBAT", ("J6", "2"), ("J5", "2"), 2.0, True),
    # the buck: boot cap, second input cap, feedback (sensed at an output cap) and enable dividers, then its VBAT feed
    ("BUCK_BOOT", ("U2", "6"), ("C9", "1"), 0.3, True), ("BUCK_SW", ("C9", "2"), ("L1", "1"), 0.4, True),
    ("VBAT", ("C6", "1"), ("C7", "1"), 0.6, True), ("VBAT", ("C7", "1"), ("R6", "1"), 0.3, True),
    ("+5V4", ("L1", "2"), ("C10", "1"), 0.6, True), ("+5V4", ("R8", "1"), ("C11", "1"), 0.3, True), ("+5V4", ("C26", "1"), ("R8", "1"), 0.3, True),
    ("BUCK_FB", ("U2", "4"), ("R9", "1"), 0.25, True), ("BUCK_FB", ("R9", "1"), ("R8", "2"), 0.25, True),
    ("BUCK_FB", ("R8", "2"), ("C26", "2"), 0.25, True),
    ("BUCK_EN", ("U2", "5"), ("R7", "1"), 0.25, True), ("BUCK_EN", ("R7", "1"), ("R6", "2"), 0.25, True),
    ("VBAT", ("C1", "1"), ("C8", "1"), 1.0, True), ("VBAT", ("R2", "1"), ("C1", "1"), 0.3, True),
    # the 5 V rail into the LDO, USB power, the LED, the ideal diode's cathode sense
    ("+5V", ("D3", "1"), ("U3", "3"), 0.6, True), ("+5V", ("C13", "1"), ("U3", "3"), 0.6, True),
    ("VBUS", ("J4", "A9"), ("U5", "5"), 0.4, True), ("N$10", ("U4", "25"), ("R25", "1"), 0.2, False),
    # the amp: speaker pair (0.3 mm gets out between its 0.5 mm-pitch pins), its caps, its signals
    ("SPK-", ("U8", "10"), ("J11", "2"), 0.25, True), ("SPK+", ("U8", "9"), ("J11", "1"), 0.25, True),
    ("+5V", ("C25", pin("C25", "+5V")), ("U8", "8"), 0.3, False), ("+5V", ("C24", pin("C24", "+5V")), ("U8", "7"), 0.3, False),
    ("AMP_SD", ("U4", "17"), ("R23", "1"), 0.2, True), ("N$9", ("R23", "2"), ("U8", "4"), 0.2, True),
    ("I2S_DIN", ("U4", "20"), ("U8", "1"), 0.2, True), ("I2S_BCLK", ("U4", "18"), ("U8", "16"), 0.2, True),
    ("I2S_LRC", ("U4", "19"), ("U8", "14"), 0.2, True),
    # the IMU's INT and the LED's anode first: no room for a via by either pin, and the cap / sense links below wall them in
    ("SERVO_TX", ("U4", "10"), ("U6", "2"), 0.2, False), ("SERVO_RX", ("U4", "11"), ("U6", "3"), 0.2, False),   # before IMU_INT: its run under the module's pin row fenced pin 11 in (twice)
    ("IMU_INT", ("U7", "4"), ("U4", "8"), 0.2, False), ("LED_A", ("D5", "2"), ("R25", "2"), 0.2, False),
    # the module's right-hand pins out past the CAN / RS485 corner (the router walled them in there): USB pair, SD CS, servo RX
    ("USB_D+", ("U4", "14"), ("U5", "4"), 0.2, False), ("USB_D-", ("U4", "13"), ("U5", "6"), 0.2, False),   # D+ first: D- drawn first walled pin 14 in
    ("SD_CS", ("U4", "21"), ("J14", "2"), 0.2, False), ("RS485_DE", ("U4", "12"), ("U11", "3"), 0.2, False),
    ("RP_GATE", ("R1", "1"), ("Q1", "4"), 0.2, False), ("RP_GATE", ("D1", "2"), ("R1", "1"), 0.2, False),
    # the servo buffer's and the IMU's caps / pull-up; the servo bus; the display bus's data line
    ("+3V3", ("C20", pin("C20", "+3V3")), ("U6", "8"), 0.3, False), ("SERVO_DIR", ("R24", pin("R24", "SERVO_DIR")), ("U6", "7"), 0.2, False),
    ("+3V3", ("C21", pin("C21", "+3V3")), ("U7", "8"), 0.25, False), ("+3V3", ("C22", pin("C22", "+3V3")), ("U7", "5"), 0.25, False),
    ("SERVO_DRV", ("U6", "6"), ("R14", "1"), 0.25, False), ("SERVO_DATA", ("R14", "2"), ("J5", "1"), 0.3, False),
    ("SERVO_DATA", ("J5", "1"), ("J6", "1"), 0.3, False), ("SERVO_DATA", ("U6", "5"), ("R14", "2"), 0.25, False),
    ("VBAT_SENSE", ("R2", "2"), ("R3", "1"), 0.2, False),
    # links the router left open on the CAN / RS485 board: claimed before it runs
    ("SPI_MISO", ("U4", "24"), ("J14", "7"), 0.2, False),
    ("USB_D+", ("J4", "A6"), ("J4", "B6"), 0.2, False),   # D+'s two pads: bridged just above the row (D- bridges below it). A
    # VBUS A4 -> A9 link here walled D+ in: the router joins the two VBUS pin pairs
    ("I2C_B_SDA", ("U4", "4"), ("J7", "3"), 0.2, False), ("I2C_B_SDA", ("J7", "3"), ("J8", "3"), 0.2, False),
    # the test pads onto their module pins (the router walls the module's edge pins in otherwise)
    ("RS485_TX", ("U4", "37"), ("TP1", "1"), 0.2, True), ("RS485_RX", ("U4", "36"), ("TP2", "1"), 0.2, True),
    ("EN", ("U4", "3"), ("TP7", "1"), 0.2, False),
    # the ToF's pull-ups: onto the module's pins and onto each other
    ("TOF_INT", ("R22", pin("R22", "TOF_INT")), ("U4", "22"), 0.2, False),
    ("+3V3", ("R21", pin("R21", "+3V3")), ("R22", pin("R22", "+3V3")), 0.25, False),
]
# (the amp's exposed pad: no vias of its own; its GND pins go to the pour. 4 vias there cost the I2S lines their room)

# GND fan-out (R9/C7 before the links, the rest after; all of it first boxes in the speaker pair) (after it, the room next to a crowded pad is gone): every GND SMD pad on an outer layer gets
# a via within 2 mm, unless one is already that close. Checked against every other net's pads, the locked tracks above,
# holes and keep-outs; the router then works round them.
import math
def fanout(only=None):
    global b
    LAYERS = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
    CLR, VD = 0.2, 0.6
    others, holes, smd = [], [], []
    EXEMPT = {("U8", "17"), ("U4", "41")}     # thermal pads take vias; no other SMD pad gets one (solder would wick down it)
    for f in b.GetFootprints():
        for q in f.Pads():
            if q.GetDrillSizeX(): holes.append((q.GetPosition(), q.GetDrillSizeX() / 2 + mm(0.3)))
            if q.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and (f.GetReference(), q.GetNumber()) not in EXEMPT and not f.GetReference().startswith("TP"):
                smd.append(q.GetEffectiveShape(pcbnew.B_Cu if q.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu))
            if q.GetNetname() == "GND" and q.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH: continue
            for L in LAYERS:
                if q.IsOnLayer(L) or q.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH): others.append((q.GetEffectiveShape(L), L))
    TR = list(b.GetTracks())
    for t in TR:
        if t.GetNetname() != "GND":
            for L in LAYERS:
                if t.IsOnLayer(L): others.append((t.GetEffectiveShape(L), L))
    gv = [t.GetPosition() for t in TR if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() == "GND"]
    keep = [z for f in b.GetFootprints() for z in f.Zones() if z.GetIsRuleArea()]
    def free_at(pt, frm, layer):
        x, y = pcbnew.ToMM(pt.x) - X0, pcbnew.ToMM(pt.y) - Y0
        if x < 0.8 or y < 0.8 or x > W - 0.8 or y > H - 0.8: return False
        if ANT[0] - 0.5 <= x <= ANT[2] + 0.5 and ANT[1] - 0.5 <= y <= ANT[3] + 0.5: return False   # the antenna keep-out + a via
        cx, cy = min(max(x, CORNER_R), W - CORNER_R), min(max(y, CORNER_R), H - CORNER_R)     # rounded corners
        if (x - cx) ** 2 + (y - cy) ** 2 > (CORNER_R - 0.8) ** 2: return False
        if any(z.Outline().Contains(pt) for z in keep): return False
        if any((pt.x - h.x) ** 2 + (pt.y - h.y) ** 2 < (r + mm(VD / 2 + CLR)) ** 2 for h, r in holes): return False
        if any((pt.x - g.x) ** 2 + (pt.y - g.y) ** 2 < mm(VD + 0.3) ** 2 for g in gv): return False
        c = pcbnew.SHAPE_CIRCLE(pt, mm(VD / 2))
        if any(sh.Collide(c, mm(CLR)) for sh, L in others): return False
        if any(sh.Collide(c, mm(0.1)) for sh in smd): return False
        seg = pcbnew.SHAPE_SEGMENT(frm, pt, mm(0.3))
        return not any(L == layer and sh.Collide(seg, mm(CLR)) for sh, L in others)
    fan = 0
    for f in b.GetFootprints():
        if only and f.GetReference() not in only: continue
        for q in f.Pads():
            if q.GetNetname() != "GND" or q.GetAttribute() != pcbnew.PAD_ATTRIB_SMD: continue
            Q = q.GetPosition(); layer = pcbnew.B_Cu if q.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
            if any((Q.x - g.x) ** 2 + (Q.y - g.y) ** 2 < mm(1.2) ** 2 for g in gv): continue
            g = next((g for g in sorted(gv, key=lambda g: (Q.x - g.x) ** 2 + (Q.y - g.y) ** 2) if (Q.x - g.x) ** 2 + (Q.y - g.y) ** 2 < mm(2.5) ** 2
                      and not any(L == layer and sh.Collide(pcbnew.SHAPE_SEGMENT(Q, g, mm(0.3)), mm(CLR)) for sh, L in others)), None)
            if g:                               # a GND via close by: just a track to it
                t = pcbnew.PCB_TRACK(b); t.SetStart(Q); t.SetEnd(g); t.SetWidth(mm(0.3)); t.SetLayer(layer); t.SetNet(b.FindNet("GND")); t.SetLocked(True); b.Add(t)
                fan += 1; continue
            for rad in (0.9, 1.2, 1.6, 2.0):
                spot = next((pt for k in range(16) for pt in [pcbnew.VECTOR2I(Q.x + int(mm(rad) * math.cos(k * math.pi / 8)), Q.y + int(mm(rad) * math.sin(k * math.pi / 8)))]
                             if free_at(pt, Q, layer)), None)
                if spot: break
            if not spot: print("no fan-out via for", f.GetReference(), q.GetNumber()); continue
            v = pcbnew.PCB_VIA(b); v.SetPosition(spot); v.SetWidth(mm(VD)); v.SetDrill(mm(0.3)); v.SetNet(b.FindNet("GND")); v.SetLocked(True); b.Add(v)
            t = pcbnew.PCB_TRACK(b); t.SetStart(Q); t.SetEnd(spot); t.SetWidth(mm(0.3)); t.SetLayer(layer); t.SetNet(b.FindNet("GND")); t.SetLocked(True); b.Add(t)
            gv.append(spot); fan += 1
    print("fan-out vias:", fan)
fanout({"R9", "C7", "C13", "C20", "C21", "U8", "U6"})   # the GND pads that ended up walled in when their via came after the links

b.Save("_preroute_base.kicad_pcb")
order = list(range(len(LINKS))); giveup = set()
for attempt in range(20):
    b = pcbnew.LoadBoard("_preroute_base.kicad_pcb"); failed = None
    for k in order:
        net, a, b_, w, must = LINKS[k]
        if not link(net, a, b_, w, optional=True) and must and k not in giveup: failed = k; break
    if failed is None: break
    print(f"  attempt {attempt + 1}: {LINKS[failed][0]} {LINKS[failed][1]} -> {LINKS[failed][2]} found no path: it goes first next time")
    if order[0] == failed: giveup.add(failed)   # no path even on the board as it starts: the router's (route.py's finish checks it)
    order.remove(failed); order.insert(0, failed)
else:
    raise SystemExit("preroute: no order of the links fits them all")
os.remove("_preroute_base.kicad_pcb")

fanout()
# the expander's stubs only kept its rows open for the links and fan-out above: off again, the router goes to the pads
for t in [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T   # (any net: the buses were renamed, a name filter left stubs behind)
          and abs(pcbnew.ToMM(t.GetLength()) - 1.6) < 1e-3 and any(b.FindFootprintByReference("U9").HitTest(p) for p in (t.GetStart(), t.GetEnd()))]:
    b.Remove(t)
b.Save("popm_board.kicad_pcb")
print("prerouted (locked)")
