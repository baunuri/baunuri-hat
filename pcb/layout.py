# Places the footprints of popm_board.kicad_pcb (made from the netlist by kinet2pcb) on the 65 x 57 HAT-size board (board.py).
#   .venv/bin/kinet2pcb -i popm_board.net -o popm_board.kicad_pcb -l /usr/share/kicad/footprints
#   .venv/bin/python layout.py
# Connectors and the module go where the robot needs them (FIXED); everything else is packed greedily: big parts on
# the top side near a target point, small parts on the bottom next to the parts they connect to.
# ponytail: a greedy packer, not a layout engineer. Good enough for a first route and a look; the power stage and the
# antenna edge deserve a hand review before ordering.
import math, os, pcbnew

from board import X0, Y0, W, H, HOLES, HEAD_R, ANT, NOTCH, MODULE, CORNER_R

mm = pcbnew.FromMM
V = lambda x, y: pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y))
b = pcbnew.LoadBoard("popm_board.kicad_pcb")
b.SetCopperLayerCount(4)
b.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)   # solid GND plane: the router keeps off it (layers: signal / GND / signal / signal)
# JLCPCB 4-layer capabilities (comfortably inside them): 0.127 mm track / space, 0.2 mm drills, 0.45 mm vias
ds = b.GetDesignSettings()
ds.m_MinClearance = mm(0.127); ds.m_TrackMinWidth = mm(0.127); ds.m_MinThroughDrill = mm(0.2)
ds.m_ViasMinSize = mm(0.45); ds.m_ViasMinAnnularWidth = mm(0.1); ds.m_CopperEdgeClearance = mm(0.3)
nc = ds.m_NetSettings.GetDefaultNetclass()
nc.SetClearance(mm(0.127)); nc.SetTrackWidth(mm(0.2)); nc.SetViaDiameter(mm(0.6)); nc.SetViaDrill(mm(0.3))
# wide tracks where the current is: battery / servos (~5 A peak), 5 V (~1.5 A), the buck's switch node. (Speaker and
# USB VBUS stay default: < 1 A, short, and their pins (QFN, USB-C) are too fine for a wide track to get in.)
ds.m_NetSettings.ClearNetclassPatternAssignments()   # from scratch: the .kicad_pro keeps old ones otherwise
for name, w, via, nets in (("Battery", 2.0, (0.9, 0.5), ["BAT_RAW", "VBAT_FET", "VBAT"]),   # any layer (inner copper is ordered at 1 oz)
                           ("Rail", 0.6, (0.7, 0.35), ["+5V", "+5V4", "BUCK_SW", "VBUS", "PI_5V", "SPK+", "SPK-"]),   # PI_5V: ~1 A when the Pi powers the board
                           ("Logic", 0.4, (0.6, 0.3), ["+3V3"])):
    c = pcbnew.NETCLASS(name); c.SetTrackWidth(mm(w)); c.SetViaDiameter(mm(via[0])); c.SetViaDrill(mm(via[1]))
    c.SetClearance(mm(0.2 if name != "Logic" else 0.127))   # 3V3 reaches 0.5 mm-pitch pins
    ds.m_NetSettings.SetNetclass(name, c)
    for n in nets: ds.m_NetSettings.SetNetclassPatternAssignment(n, name)

# ---- outline -------------------------------------------------------------------------------------------------------
for d in [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]: b.Remove(d)
def outline(b, R=CORNER_R):
    def seg(x0, y0, x1, y1):
        e = pcbnew.PCB_SHAPE(b); e.SetShape(pcbnew.SHAPE_T_SEGMENT); e.SetLayer(pcbnew.Edge_Cuts); e.SetWidth(mm(0.1))
        e.SetStart(V(x0, y0)); e.SetEnd(V(x1, y1)); b.Add(e)
    def arc(cx, cy, sx, sy):              # the corner's quarter circle round (cx, cy), bulging towards (sx, sy) = +-1
        k = R / 2 ** 0.5
        e = pcbnew.PCB_SHAPE(b); e.SetShape(pcbnew.SHAPE_T_ARC); e.SetLayer(pcbnew.Edge_Cuts); e.SetWidth(mm(0.1))
        e.SetArcGeometry(V(cx + sx * R, cy), V(cx + sx * k, cy + sy * k), V(cx, cy + sy * R)); b.Add(e)
    nx, ny0, ny1 = NOTCH                  # the antenna's notch in the left edge (Espressif: no board under the antenna)
    seg(R, 0, W - R, 0); seg(W, R, W, H - R); seg(W - R, H, R, H)
    seg(0, H - R, 0, ny1); seg(0, ny1, nx, ny1); seg(nx, ny1, nx, ny0); seg(nx, ny0, 0, ny0); seg(0, ny0, 0, R)
    arc(R, R, -1, -1); arc(W - R, R, 1, -1); arc(W - R, H - R, 1, 1); arc(R, H - R, -1, 1)
outline(b)

fp = {f.GetReference(): f for f in b.GetFootprints()}

def place(ref, x, y, rot=0, bottom=False):
    f = fp[ref]
    if f.IsFlipped() != bottom: f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    f.SetOrientationDegrees(rot); f.SetPosition(V(x, y))

def box(f):                               # courtyard box on its side, in board mm
    f.BuildCourtyardCaches()          # GetCourtyard() is a cache: stale after a move / flip
    lay = pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd
    c = f.GetCourtyard(lay)
    bb = c.BBox() if c.OutlineCount() else f.GetBoundingBox(False, False)
    return (pcbnew.ToMM(bb.GetX()) - X0, pcbnew.ToMM(bb.GetY()) - Y0, pcbnew.ToMM(bb.GetRight()) - X0, pcbnew.ToMM(bb.GetBottom()) - Y0)

# ---- fixed: module, connectors, holes (positions worked out from each footprint's origin) ---------------------------
FIXED = [   # (ref, x, y, rotation, bottom side)
    ("U4", *MODULE, 90, False),       # ESP32-S3: antenna over the notch in the left edge; pins 27-40 face the header
    ("J13", 8.37, 5.27, 270, True),   # Pi header, female, underneath (on a Pi): each pad over the Pi's pin (pin 1 inside, at the left end)
    ("J4", 12.3, 54.3, 0, False),     # USB-C: mouth at the bottom edge, left (the antenna's keep-out takes the left edge)
    ("J7", 23.14, 53.6, 0, False), ("J8", 32.54, 53.6, 0, False),   # I2C_B1, I2C_B2: mouths at the bottom edge
    ("J10", 41.94, 53.6, 0, False), ("J9", 52.35, 53.6, 0, False),  # QWIIC, TOF
    ("J1", 51.9, 17.7, 270, False),   # BATTERY: XT30 right angle, mouth at the right edge, top
    ("J12", 61.6, 28.6, 90, False),   # UART (XIAO): mouth at the right edge
    ("J14", 58.41, 42.0, 270, False), # microSD: its mouth (the side with contact pads 1-8) at the right edge; the card sticks out ~3 mm
    ("J11", 29.0, 10.5, 0, False),    # SPEAKER, by the amp (the module's I2S pins are on its right end)
    ("J5", 29.0, 46.5, 0, False), ("J6", 40.5, 46.5, 0, False),   # SERVO1, SERVO2: above the bottom plugs
    ("U9", 37.6, 11.5, 270, True),
    ("J15", 10.5, 37.0, 0, False), ("J16", 10.5, 45.0, 0, False),   # CAN, RS485 (JST-GH, vertical): below the module, past its keep-out (x < 5.5); RS485's pads clear of the USB VBUS vias
    ("U10", 10.5, 37.0, 0, True), ("U11", 10.5, 45.0, 0, True),     # their transceivers right underneath (under the module they block the IMU's lines)    # IO expander: underneath, right below the header's middle (its 12 header pins), port 0 up
]
for ref, x, y, rot, bot in FIXED: place(ref, x, y, rot, bot)
holes = [r for r in fp if r.startswith("H")]
for ref, (x, y) in zip(sorted(holes), HOLES): place(ref, x, y)

# ---- greedy packer --------------------------------------------------------------------------------------------------
taken = {False: [], True: []}             # side -> boxes
for ref, *_ in FIXED:
    bx = box(fp[ref])
    if ref == "U4":                       # its courtyard spans the antenna's whole keep-out: just the body here (ANT below)
        bx = (MODULE[0] - 12.25, MODULE[1] - 9, MODULE[0] + 13.25, MODULE[1] + 9)
    if ref == "U9": bx = (bx[0], bx[1] - 2.0, bx[2], bx[3] + 2.0)   # + 2 mm past both pin rows: preroute.py stubs each pin out there
    taken[fp[ref].IsFlipped()].append(bx)
    th = [p for p in fp[ref].Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
    if ref == "U4" and th:                # the module's only through holes are its GND pad's via grid: block just that
        xs = [pcbnew.ToMM(p.GetPosition().x) - X0 for p in th]; ys = [pcbnew.ToMM(p.GetPosition().y) - Y0 for p in th]
        taken[True].append((min(xs) - 0.6, min(ys) - 0.6, max(xs) + 0.6, max(ys) + 0.6))
    elif th: taken[not fp[ref].IsFlipped()].append(bx)   # THT pins go through
for x, y in HOLES:
    for s in (False, True): taken[s].append((x - HEAD_R, y - HEAD_R, x + HEAD_R, y + HEAD_R))
for s in (False, True): taken[s] += [ANT, (0, MODULE[1] - 24, MODULE[0] - 6.75, MODULE[1] + 24)]   # + the module's antenna courtyard
def free(bx, side, gap=0.25):
    x0, y0, x1, y1 = bx
    if x0 < 0.3 or y0 < 0.3 or x1 > W - 0.3 or y1 > H - 0.3: return False
    return all(x1 + gap <= a or x0 >= c + gap or y1 + gap <= b_ or y0 >= d + gap for a, b_, c, d in taken[side])

def pack(ref, tx, ty, sides, rots=(0, 90, 180, 270)):
    """Nearest free spot to (tx, ty) on one of `sides` (True = bottom); the first side is preferred by 1.5 mm."""
    f = fp[ref]; best = None
    for bottom in sides:
        for rot in rots:
            place(ref, 0, 0, rot, bottom); x0, y0, x1, y1 = box(f)
            for i in range(0, int(W * 4)):
                for j in range(0, int(H * 4)):
                    x, y = i / 4, j / 4
                    bx = (x0 + x, y0 + y, x1 + x, y1 + y)
                    d = math.hypot(x - tx, y - ty) + (1.5 if bottom != sides[0] else 0)
                    if (best is None or d < best[0]) and free(bx, bottom): best = (d, x, y, rot, bx, bottom)
    if best is None: print("NO ROOM", ref); place(ref, W + 15, H / 2, 0, sides[0]); return False
    _, x, y, rot, bx, bottom = best
    place(ref, x, y, rot, bottom); taken[bottom].append(bx)
    if f.Pads()[0].GetAttribute() == pcbnew.PAD_ATTRIB_PTH: taken[not bottom].append(bx)
    return True

# top side: the power stage, battery side (right) to logic side (left), plus the buttons and the LED
TOP = [("U2", 44, 27), ("L1", 44, 21), ("C1", 37, 24),   # the buck first (its loop is the one layout really matters for), right of
       ("SW1", 20, 35), ("SW2", 25, 35),   # middle, away from the header's signal lines (top) and the I2C plugs (bottom); then RESET / BOOT
       ("Q1", 35, 38), ("F1", 30, 32), ("D2", 38, 32), ("D3", 37, 16), ("D4", 20, 44)]
# (U3, the LDO, goes underneath too)

# each chip's own capacitors / resistors (refs from popm_board.py's creation order), packed right after the chip, by the
# chip's pin they share a net with. Without this a cap on only power + GND would land anywhere.
SAT = {"U2": "C8 C6 C9 R8 R9 C26 C7 R6 R7",   # buck: input caps, boot cap, feedback (+ feed-forward cap) and enable
       "L1": "C10 C11 C27", "D3": "C12", "U3": "C13 C14 C15", "U4": "C16 C17 C18 C19 R10 R11 R17 R18 R19 R20", "U6": "C20 R24",   # + the I2C pull-ups, each under its own module pin (PIN)
       "U7": "C21 C22", "J9": "C23", "U8": "C24 C25",
       "U9": "C28 R26", "J14": "C29 C30 R27 R28 R29 R30 R31",   # the expander's cap / INT pull-up; the microSD's caps and pull-ups
       "U10": "C31 R32", "U11": "C32 R33", "J15": "D6 R34 JP1", "J16": "D7 R35 JP2",   # CAN / RS485: cap + pull; TVS + terminator by the plug
       "D5": "R25",
       "J13": "D8 R36 R37 Q3 Q4 R38 R39",   # the Pi side: 5 V diode, UART 1k's, reset / boot FETs + pull-downs, by their header pins                       # the LED's resistor right by it (packed apart, the link found no way)
       "C1": "R2"}                        # the battery sense's 100k by the battery (only the divided node travels)
HOT = {"C8", "C6", "C9", "C10"}           # the buck's hot loops (input caps, boot cap, first output cap): no vias in them
UNDER = {"R17", "R18", "R19", "R20"}   # the I2C pull-ups: underneath (on top they'd crowd the module's 0.9 mm-pitch pads)
PIN = {"C21": "8", "C22": "5", "R17": "4", "R18": "5", "R19": "6", "R20": "7"}            # the IMU's caps by its VDD / VDDIO pins (not under the bottom row: SDA / SCL leave there)
def satellites(a):
    for ref in SAT.get(a, "").split():
        nets = {p.GetNetname() for p in fp[ref].Pads()} - {"GND", ""}
        pts = [q.GetPosition() for q in fp[a].Pads() if q.GetNetname() in nets and q.GetNumber() == PIN.get(ref, q.GetNumber())]
        tx = sum(pcbnew.ToMM(q.x) for q in pts) / len(pts) - X0; ty = sum(pcbnew.ToMM(q.y) for q in pts) / len(pts) - Y0
        side = fp[a].IsFlipped()
        pack(ref, tx, ty, (side,) if ref in HOT else (True,) if ref in UNDER else (side, not side)); placed.add(ref)
        g = [q.GetPosition() for q in fp[ref].Pads() if q.GetNetname() == "GND"]   # keep a via spot just past its GND
        o = [q.GetPosition() for q in fp[ref].Pads() if q.GetNetname() not in ("GND", "")]   # pad, so the fan-out finds room
        if len(g) == 1 and o:
            gx_, gy_ = pcbnew.ToMM(g[0].x) - X0, pcbnew.ToMM(g[0].y) - Y0; ox, oy = pcbnew.ToMM(o[0].x) - X0, pcbnew.ToMM(o[0].y) - Y0
            d = math.hypot(gx_ - ox, gy_ - oy) or 1; vx, vy = gx_ + (gx_ - ox) / d * 1.15, gy_ + (gy_ - oy) / d * 1.15
            for sd in ((False, True) if a == "U2" else (fp[ref].IsFlipped(),)): taken[sd].append((vx - 0.45, vy - 0.45, vx + 0.45, vy + 0.45))   # the buck's: a via goes through both sides (all parts': the amp's I2S runs out of room)

placed = {r for r, *_ in FIXED} | {r for r, *_ in TOP} | set(holes)
for k, (ref, x, y) in enumerate(TOP):     # each part then its helpers; but the inductor goes in before the buck's helpers
    rots = (fp["SW1"].GetOrientationDegrees(),) if ref == "SW2" else (0, 90, 180, 270)   # both buttons the same way round
    if not pack(ref, x, y, (False,), rots): print("  ->", ref, "underneath"); pack(ref, x, y, (True,), rots)
    if ref == "L1": satellites("U2")
    if ref != "U2": satellites(ref)
satellites("U4"); satellites("J13"); satellites("U9"); satellites("J9"); satellites("J14"); satellites("U10"); satellites("U11"); satellites("J15"); satellites("J16")
# underneath the fuse's pads: nothing (the IMU's escape vias landed in one: a via goes through every layer)
for q in fp["F1"].Pads():
    bb = q.GetBoundingBox()               # + 2 mm: the IMU's escape vias sit 1.35 mm past its pins
    taken[True].append((pcbnew.ToMM(bb.GetX()) - X0 - 2, pcbnew.ToMM(bb.GetY()) - Y0 - 2, pcbnew.ToMM(bb.GetRight()) - X0 + 2, pcbnew.ToMM(bb.GetBottom()) - Y0 + 2))
# underneath the buck (inductor + chip + 1.5 mm): its own parts only (placed above), no signal chips (the expander landed there)
bx = [box(fp[r]) for r in ("L1", "U2")]
taken[True].append((min(q[0] for q in bx) - 1.5, min(q[1] for q in bx) - 1.5, max(q[2] for q in bx) + 1.5, max(q[3] for q in bx) + 1.5))
# keep the underside clear where preroute.py drops U2's and C6's GND vias (the SW track runs between those pads on top)
for ref, n, dy in (("U2", "1", -1.0), ("C6", "2", -1.05)):
    q = next(q for q in fp[ref].Pads() if q.GetNumber() == n).GetPosition()
    x, y = pcbnew.ToMM(q.x) - X0, pcbnew.ToMM(q.y) - Y0 + dy
    taken[True].append((x - 0.5, y - 0.5, x + 0.5, y + 0.5))
# ... and the underside path of its input link: C6's VBAT via (1.05 mm below its pad) -> C7 -> R6 (preroute.py)
v6 = next(q for q in fp["C6"].Pads() if q.GetNumber() == "1").GetPosition()
pts = [(pcbnew.ToMM(v6.x) - X0, pcbnew.ToMM(v6.y) - Y0 + 1.05)] + \
      [(pcbnew.ToMM(q.GetPosition().x) - X0, pcbnew.ToMM(q.GetPosition().y) - Y0) for r in ("C7", "R6") for q in fp[r].Pads() if q.GetNumber() == "1"]
for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
    taken[True].append((min(xa, xb) - 0.6, min(ya, yb) - 0.6, max(xa, xb) + 0.6, max(ya, yb) + 0.6))

# bottom: everything else, next to the pads it connects to (power and ground nets don't pull)
POWER = {"GND", "+3V3", "+5V", "VBAT", "+5V4"}
def target(ref):
    pts = []
    for p in fp[ref].Pads():
        n = p.GetNetname()
        if not n or n in POWER: continue
        for g in b.GetFootprints():
            if g.GetReference() == ref or g.GetReference() not in placed: continue
            for q in g.Pads():
                if q.GetNetname() == n: c = q.GetPosition(); pts.append((pcbnew.ToMM(c.x) - X0, pcbnew.ToMM(c.y) - Y0))
    if not pts:   # only power pins (a decoupling cap): sit by the chip it serves, or the board's middle
        return (W / 2, H / 2)
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))

rest = [r for r in fp if r not in placed]
# chips first (they anchor their passives), then the rest by how connected they are
rest.sort(key=lambda r: (r[0] not in "UQD", -len(fp[r].Pads())))
for ref in rest:
    if ref in placed: continue            # a satellite already packed with its chip
    tx, ty = target(ref)
    if ref == "U6": tx, ty = 26.0, 41.0       # by the servo plugs, clear of the battery FET on top (under it no via fits: its GND pin
                                              # had 10 mm to the plane). Under the module's pin row (its natural spot) its signals' vias had no room
    if ref.startswith("TP"): tx -= 2.5        # a test pad lands under its pin otherwise: no room for the via joining them
    pack(ref, tx, ty, (True,), (270,) if ref == "U6" else (0, 90, 180, 270))   # the servo buffer: pins 1-3 (TX / RX / DIR) up towards the module
    placed.add(ref)
    if ref == "U7":                       # keep the strip under the IMU's SDA / SCL pins free: preroute.py escapes them there
        q13, q14 = (next(q for q in fp["U7"].Pads() if q.GetNumber() == n).GetPosition() for n in ("13", "14"))
        x0, x1 = sorted((pcbnew.ToMM(q13.x) - X0, pcbnew.ToMM(q14.x) - X0)); yr = pcbnew.ToMM(q13.y) - Y0
        taken[True].append((x0 - 0.5, yr + 0.3, x1 + 0.5, yr + 1.8))
    satellites(ref)
assert len(placed) == len(fp), set(fp) - placed

# planes: GND fills inner layer 1 and both outsides (route.py adds the outside pours after routing)
ka = pcbnew.ZONE(b); ka.SetIsRuleArea(True); ka.SetLayerSet(pcbnew.LSET.AllCuMask())
ka.SetDoNotAllowTracks(True); ka.SetDoNotAllowVias(True); ka.SetDoNotAllowCopperPour(True); ka.SetDoNotAllowPads(False)
ka.SetZoneName("antenna keep-out, all copper layers (Espressif: nothing under the antenna)")
o = ka.Outline(); o.NewOutline()
for x, y in ((-1, ANT[1]), (ANT[2], ANT[1]), (ANT[2], ANT[3]), (-1, ANT[3])): o.Append(V(x, y))
for z in [z for z in b.Zones() if z.GetIsRuleArea() and z.GetZoneName().startswith("antenna keep-out")]: b.Remove(z)
b.Add(ka)

for z in [z for z in b.Zones() if z.GetIsRuleArea() and z.GetZoneName().startswith("screw head")]: b.Remove(z)
for hx, hy in HOLES:                      # screw head / standoff: no copper within HEAD_R of a hole's centre, any layer
    k = pcbnew.ZONE(b); k.SetIsRuleArea(True); k.SetLayerSet(pcbnew.LSET.AllCuMask()); k.SetZoneName(f"screw head {hx} {hy}")
    k.SetDoNotAllowTracks(True); k.SetDoNotAllowVias(True); k.SetDoNotAllowCopperPour(True); k.SetDoNotAllowPads(False)
    o = k.Outline(); o.NewOutline()
    for i in range(32): o.Append(V(hx + HEAD_R * math.cos(i * math.pi / 16), hy + HEAD_R * math.sin(i * math.pi / 16)))
    b.Add(k)

def zone(net, layer, prio=0):
    z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(b.FindNet(net)); z.SetAssignedPriority(prio)
    o = z.Outline(); o.NewOutline()
    for x, y in ((0, 0), (W, 0), (W, H), (0, H)): o.Append(V(x, y))
    z.SetLocalClearance(mm(0.2)); z.SetMinThickness(mm(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)   # SMD pads solid, THT pins on spokes (solderable)
    b.Add(z)
for z in list(b.Zones()):
    if z.GetNetname() in ("GND", "+3V3"): b.Remove(z)
zone("GND", pcbnew.In1_Cu); zone("GND", pcbnew.F_Cu); zone("GND", pcbnew.B_Cu)
b.Save("popm_board.kicad_pcb")
print("placed", len(placed), "parts")
