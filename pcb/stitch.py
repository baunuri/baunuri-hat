# GND stitching vias (after route.py): a via wherever one fits on a 1.27 mm grid, tying the top and bottom GND pours to
# the GND plane (inner layer 1); none in the antenna's keep-out. Then refills the zones and runs DRC.
#   .venv/bin/python stitch.py
import subprocess, pcbnew

from board import X0, Y0, W, H, HOLES, CORNER_R, ANT
ANT = (ANT[0], ANT[1] - 0.5, ANT[2] + 0.5, ANT[3] + 0.5)   # the antenna keep-out + a via's radius and clearance
VIA_D, VIA_DRILL, CLR = 0.6, 0.3, 0.2
mm = pcbnew.FromMM
b = pcbnew.LoadBoard("popm_board.kicad_pcb")
gnd = b.FindNet("GND")
# (SWIG: b.GetTracks() breaks after the board is changed, so take one snapshot and work from it)
TR = b.GetTracks()
BATT = {"BAT_RAW", "VBAT_FET", "VBAT"}   # the battery / servo current
old = [t for t in TR if (t.GetNetname() == "GND" and ((t.Type() == pcbnew.PCB_VIA_T and t.GetIsFree()) or
       (t.Type() == pcbnew.PCB_TRACE_T and abs(t.GetWidth() - pcbnew.FromMM(0.3)) < 10 and t.GetLength() < pcbnew.FromMM(2.1))))
       or (t.GetNetname() in BATT and ((t.Type() == pcbnew.PCB_VIA_T and t.GetIsFree()) or      # companion vias + their links
           (t.Type() == pcbnew.PCB_TRACE_T and abs(t.GetWidth() - pcbnew.FromMM(1.21)) < 10)))]
for t in old: b.Remove(t)                 # re-runnable: drop the old stitching vias and fan-out stubs
gone = {id(t) for t in old}
TR = [t for t in TR if id(t) not in gone]

LAYERS = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
gvias = [(v.GetPosition().x, v.GetPosition().y) for v in TR if v.Type() == pcbnew.PCB_VIA_T and v.GetNetname() == "GND"]
others = []                               # (shape, layer, net) of every copper item
smd = []                                  # every SMD pad (any net): no via lands in one (solder would wick down it)
EXEMPT = {("U8", "17"), ("U4", "41")}     # thermal pads: the amp's exposed pad and the module's GND pad take vias
circles = []                              # (x, y, r) nm: holes and the vias placed here
for t in TR:                              # every net's copper (checks skip the via's own net: GND for stitching,
    for L in LAYERS:                      # a battery net for its companion vias)
        if t.IsOnLayer(L): others.append((t.GetEffectiveShape(L), L, t.GetNetname()))
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetDrillSizeX():             # any hole, GND ones too: keep vias off it (drill to drill)
            circles.append((p.GetPosition().x, p.GetPosition().y, p.GetDrillSizeX() // 2 + mm(0.3)))
        if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and (f.GetReference(), p.GetNumber()) not in EXEMPT and not f.GetReference().startswith("TP"):
            smd.append(p.GetEffectiveShape(pcbnew.B_Cu if p.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu))
        for L in LAYERS:
            if p.IsOnLayer(L) or p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                others.append((p.GetEffectiveShape(L), L, p.GetNetname()))

for v in TR:                              # the router's own vias: drill to drill
    if v.Type() == pcbnew.PCB_VIA_T: circles.append((v.GetPosition().x, v.GetPosition().y, v.GetWidth(pcbnew.F_Cu) // 2))
keepouts = [z for f in b.GetFootprints() for z in f.Zones() if z.GetIsRuleArea()] + [z for z in b.Zones() if z.GetIsRuleArea()]

import math
def fits(x, y, track_from=None, layer=None, d=VIA_D, net="GND", w=0.3):
    if x < 0.8 or y < 0.8 or x > W - 0.8 or y > H - 0.8: return False
    cx, cy = min(max(x, CORNER_R), W - CORNER_R), min(max(y, CORNER_R), H - CORNER_R)   # rounded corners (layout.py)
    if (x - cx) ** 2 + (y - cy) ** 2 > (CORNER_R - 0.8) ** 2: return False
    if ANT[0] <= x <= ANT[2] and ANT[1] <= y <= ANT[3]: return False
    if any((x - hx) ** 2 + (y - hy) ** 2 < (3.0 + d / 2 + 0.05) ** 2 for hx, hy in HOLES): return False   # the whole via outside the head
    c = pcbnew.SHAPE_CIRCLE(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y)), mm(d / 2))
    # In2 is the 3V3 plane: its fill just clears round the via, so only real items count
    cx, cy, r = mm(X0 + x), mm(Y0 + y), mm(d / 2)
    if any((cx - a) ** 2 + (cy - b_) ** 2 < (r + rr + mm(CLR)) ** 2 for a, b_, rr in circles): return False
    pt = pcbnew.VECTOR2I(cx, cy)
    rim = [pt] + [pcbnew.VECTOR2I(cx + int((r + mm(0.05)) * math.cos(k * math.pi / 4)), cy + int((r + mm(0.05)) * math.sin(k * math.pi / 4))) for k in range(8)]
    if any(z.Outline().Contains(q) for z in keepouts for q in rim): return False   # its rim too, not just its centre
    if any(n != net and s.Collide(c, mm(CLR)) for s, L, n in others): return False
    if any(s.Collide(c, mm(0.1)) for s in smd): return False
    for lay in ([layer] if not isinstance(layer, (list, tuple)) else layer) if track_from is not None else []:
        seg = pcbnew.SHAPE_SEGMENT(track_from, pt, mm(w))   # the short track from the pad / via to this via
        if any(L == lay and n != net and s.Collide(seg, mm(CLR)) for s, L, n in others): return False
    return True

# battery path: every via gets up to two companions 1.2 mm away, linked on both outer layers (one 0.5 mm via is
# marginal for 5 A). Free vias, so a rerun drops and redoes them.
import math
comp = 0
for v in [t for t in TR if t.Type() == pcbnew.PCB_VIA_T and t.GetNetname() in BATT]:
    P = v.GetPosition(); net = v.GetNetname(); d = pcbnew.ToMM(v.GetWidth(pcbnew.F_Cu)); added = 0
    for k in range(8):
        if added == 2: break
        a = k * math.pi / 4; x = pcbnew.ToMM(P.x) - X0 + 1.2 * math.cos(a); y = pcbnew.ToMM(P.y) - Y0 + 1.2 * math.sin(a)
        if not fits(x, y, track_from=P, layer=[pcbnew.F_Cu, pcbnew.B_Cu], d=d, net=net, w=1.21): continue
        nv = pcbnew.PCB_VIA(b); nv.SetPosition(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y))); nv.SetWidth(v.GetWidth(pcbnew.F_Cu))
        nv.SetDrill(v.GetDrillValue()); nv.SetNet(v.GetNet()); nv.SetIsFree(True); b.Add(nv)
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            t = pcbnew.PCB_TRACK(b); t.SetStart(P); t.SetEnd(nv.GetPosition()); t.SetWidth(mm(1.21)); t.SetLayer(lay)
            t.SetNet(v.GetNet()); b.Add(t)
            others.append((t.GetEffectiveShape(lay), lay, net))
        circles.append((nv.GetPosition().x, nv.GetPosition().y, nv.GetWidth(pcbnew.F_Cu) // 2)); added += 1; comp += 1
print("battery companion vias:", comp)

# fan-out first (pads before the grid takes their room): every GND pad on an outer layer gets a via of its own within 2 mm
import math
fan = 0
for f in b.GetFootprints():
    for p in f.Pads():
        if p.GetNetname() != "GND" or p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD: continue
        P = p.GetPosition(); layer = pcbnew.B_Cu if p.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu
        if any((P.x - a) ** 2 + (P.y - c) ** 2 < mm(1.2) ** 2 for a, c in gvias): continue
        done = False
        for rad in (0.9, 1.2, 1.6, 2.0):
            for k in range(16):
                a = k * math.pi / 8
                x = pcbnew.ToMM(P.x) - X0 + rad * math.cos(a); y = pcbnew.ToMM(P.y) - Y0 + rad * math.sin(a)
                if fits(x, y, track_from=P, layer=layer):
                    v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y)))
                    v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL)); v.SetNet(gnd); v.SetIsFree(True); b.Add(v)
                    t = pcbnew.PCB_TRACK(b); t.SetStart(P); t.SetEnd(v.GetPosition()); t.SetWidth(mm(0.3))
                    t.SetLayer(layer); t.SetNet(gnd); b.Add(t)
                    circles.append((v.GetPosition().x, v.GetPosition().y, mm(VIA_D / 2)))
                    gvias.append((v.GetPosition().x, v.GetPosition().y)); fan += 1; done = True; break
            if done: break
        if not done: print("no fan-out via for", f.GetReference(), p.GetNumber())
print("fan-out vias:", fan)
n = 0
step = 1.27
i = 0
while i * step < W:
    j = 0
    while j * step < H:
        x, y = 0.6 + i * step, 0.6 + j * step
        if fits(x, y):
            v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y)))
            v.SetWidth(mm(VIA_D)); v.SetDrill(mm(VIA_DRILL)); v.SetNet(gnd); v.SetIsFree(True)
            b.Add(v); n += 1
            circles.append((v.GetPosition().x, v.GetPosition().y, mm(VIA_D / 2)))   # spacing between vias
            gvias.append((v.GetPosition().x, v.GetPosition().y))
        j += 1
    i += 1
for z in b.Zones():
    if not z.GetIsRuleArea():
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)   # SMD pads solid (no starved spokes), THT on spokes
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
# a patch of top / bottom pour with no via in it hangs off its pads only: give each one a via down to the plane
isl = 0
for z in [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "GND" and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)]:
    polys = z.GetFilledPolysList(z.GetLayer())
    for k in range(polys.OutlineCount()):
        ol = polys.Outline(k)
        if any(ol.PointInside(pcbnew.VECTOR2I(int(x), int(y))) for x, y in gvias): continue
        bb = ol.BBox(); spot = None
        for d, drill in ((VIA_D, VIA_DRILL), (0.5, 0.25), (0.45, 0.2)):   # smaller vias for slivers (JLC: 0.45 / 0.2)
            for i in range(int(pcbnew.ToMM(bb.GetWidth()) / 0.1) + 1):
                for j in range(int(pcbnew.ToMM(bb.GetHeight()) / 0.1) + 1):
                    x = pcbnew.ToMM(bb.GetX()) - X0 + i * 0.1; y = pcbnew.ToMM(bb.GetY()) - Y0 + j * 0.1
                    if ol.PointInside(pcbnew.VECTOR2I(mm(X0 + x), mm(Y0 + y))) and fits(x, y, d=d): spot = (x, y, d, drill); break
                if spot: break
            if spot: break
        if not spot:                      # no room for a via: a GND track from a GND pad in it to a nearby via (grid search)
            import pathfind
            L = z.GetLayer(); done = False
            for f in b.GetFootprints():
                for p in f.Pads():
                    if done or p.GetNetname() != "GND" or not p.IsOnLayer(L) or not ol.PointInside(p.GetPosition()): continue
                    P = p.GetPosition()
                    for vx, vy in sorted(gvias, key=lambda v: (v[0] - P.x) ** 2 + (v[1] - P.y) ** 2)[:4]:
                        if ol.PointInside(pcbnew.VECTOR2I(int(vx), int(vy))): continue
                        pts = pathfind.find(b, "GND", ("pad", f.GetReference(), p.GetNumber()),
                                            ("at", pcbnew.ToMM(vx) - X0, pcbnew.ToMM(vy) - Y0, [0, 1, 2]), 0.3)
                        if pts: pathfind.draw(b, "GND", pts, 0.3, locked=False); done = True; isl += 1; break
            if done: continue
            for f in b.GetFootprints():
                for p in f.Pads():
                    if done or p.GetNetname() != "GND" or not p.IsOnLayer(L) or not ol.PointInside(p.GetPosition()): continue
                    P = p.GetPosition()
                    for vx, vy in sorted(gvias, key=lambda v: (v[0] - P.x) ** 2 + (v[1] - P.y) ** 2)[:6]:
                        seg = pcbnew.SHAPE_SEGMENT(P, pcbnew.VECTOR2I(int(vx), int(vy)), mm(0.3))
                        if (vx - P.x) ** 2 + (vy - P.y) ** 2 > mm(5) ** 2: break
                        if any(LL == L and nn != "GND" and sh.Collide(seg, mm(CLR)) for sh, LL, nn in others): continue
                        t = pcbnew.PCB_TRACK(b); t.SetStart(P); t.SetEnd(pcbnew.VECTOR2I(int(vx), int(vy))); t.SetWidth(mm(0.3))
                        t.SetLayer(L); t.SetNet(gnd); b.Add(t); done = True; isl += 1; break
            if not done: print("island with no via and no clear track at", round(pcbnew.ToMM(bb.Centre().x) - X0, 1), round(pcbnew.ToMM(bb.Centre().y) - Y0, 1))
            continue
        v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(X0 + spot[0]), mm(Y0 + spot[1])))
        v.SetWidth(mm(spot[2])); v.SetDrill(mm(spot[3])); v.SetNet(gnd); v.SetIsFree(True); b.Add(v)
        circles.append((v.GetPosition().x, v.GetPosition().y, mm(spot[2] / 2))); gvias.append((v.GetPosition().x, v.GetPosition().y)); isl += 1
if isl: pcbnew.ZONE_FILLER(b).Fill(b.Zones())
print("island vias:", isl)
b.Save("popm_board.kicad_pcb")
print("stitching vias:", n)
# a stitching via whose pours didn't reach it on both sides ties nothing together: drop those (DRC's via_dangling), refill
import json
for _ in range(5):   # removing a stub can leave the piece behind it dangling: repeat until none
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", "popm_board-drc.json", "popm_board.kicad_pcb"])
    V = json.load(open("popm_board-drc.json"))["violations"]
    dang = {(round(i["pos"]["x"], 3), round(i["pos"]["y"], 3)) for v in V if v["type"] == "via_dangling" for i in v["items"]}
    stubs = [(i["pos"]["x"], i["pos"]["y"], i["description"]) for v in V if v["type"] == "track_dangling" for i in v["items"]]   # router leftovers
    # (only the very track DRC names: same net, same length. A router track merely ending at the same point is a live joint)
    same = lambda t, d: f"[{t.GetNetname()}]" in d and f"length {pcbnew.ToMM(t.GetLength()):.4f} mm" in d
    if not (dang or stubs): break
    b = pcbnew.LoadBoard("popm_board.kicad_pcb")
    near = lambda t, x, y: min(math.dist((pcbnew.ToMM(q.x), pcbnew.ToMM(q.y)), (x, y)) for q in (t.GetStart(), t.GetEnd(), t.GetCenter())) < 0.05
    for t in [t for t in b.GetTracks() if
              (t.Type() == pcbnew.PCB_VIA_T and (round(pcbnew.ToMM(t.GetPosition().x), 3), round(pcbnew.ToMM(t.GetPosition().y), 3)) in dang) or
              (t.Type() == pcbnew.PCB_TRACE_T and not t.IsLocked() and t.GetLength() < pcbnew.FromMM(3.0) and any(near(t, x, y) and same(t, d) for x, y, d in stubs))]:
        b.Remove(t)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones()); b.Save("popm_board.kicad_pcb")
    print("dropped dangling vias / stubs:", len(dang), len(stubs))
