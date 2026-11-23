# Tidies the silkscreen (after stitch.py; touches no copper): plugs and test pads are labelled by what they are
# (BATTERY, WHEELS, TXD0 ...), every other reference is small and moved to the first spot round its part that is clear of
# pads, other parts, other labels and the board edge, or hidden when there's none (JLC places parts from the CPL file,
# not the silkscreen).   .venv/bin/python silk.py
import subprocess, pcbnew
mm = pcbnew.FromMM
from board import X0, Y0, W, H, NOTCH
b = pcbnew.LoadBoard("popm_board.kicad_pcb")
NAMES = {"J1": "BAT", "J4": "USB", "J5": "SRV1", "J6": "SRV2", "J7": "I2C B", "J8": "I2C B",
         "J9": "TOF", "J10": "QWIIC", "J11": "SPK", "J12": "UART", "J13": "PI", "J14": "SD", "J15": "CAN", "J16": "485",
         "SW1": "E", "SW2": "B"}   # buttons: EN (reset) and BOOT, one letter each, to their right   # short names, so they fit beside the plugs on top
FPS = list(b.GetFootprints())

def box(bb, grow=0.0):
    g = mm(grow); return (bb.GetX() - g, bb.GetY() - g, bb.GetRight() + g, bb.GetBottom() + g)
def hit(a, c): return a[0] < c[2] and c[0] < a[2] and a[1] < c[3] and c[1] < a[3]

def body(f):                              # the part's body (its fab outline): silk under it is hidden. Not the courtyard:
    lay = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab   # the module's spans its whole antenna keep-out
    gs = [g for g in f.GraphicalItems() if g.GetLayer() == lay and g.GetClass() not in ("PCB_TEXT", "PCB_FIELD")]
    if not gs: return f.GetBoundingBox(False, False)
    bb = gs[0].GetBoundingBox()
    for g in gs[1:]: bb.Merge(g.GetBoundingBox())
    return bb
blocked = {False: [], True: []}           # side (True = bottom) -> boxes the text mustn't touch
for f in FPS:
    if not f.GetReference().startswith("H"): blocked[f.IsFlipped()].append(box(body(f)))
    for g in f.GraphicalItems():          # the parts' own printed outlines and marks (an XT30's + / -)
        if g.GetClass() != "PCB_FIELD" and g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and getattr(g, "IsVisible", lambda: True)():
            blocked[g.GetLayer() == pcbnew.B_SilkS].append(box(g.GetBoundingBox(), 0.1))
    for p in f.Pads():
        for side, lay in ((False, pcbnew.F_Cu), (True, pcbnew.B_Cu)):
            if p.IsOnLayer(lay): blocked[side].append(box(p.GetBoundingBox(), 0.15))
edge = (mm(X0 + 0.6), mm(Y0 + 0.6), mm(X0 + W - 0.6), mm(Y0 + H - 0.6))
NX, NY0, NY1 = NOTCH                      # the antenna notch in the left edge: keep labels 0.6 mm off it
for s_ in (False, True): blocked[s_].append((mm(X0 - 1), mm(Y0 + NY0 - 0.6), mm(X0 + NX + 0.6), mm(Y0 + NY1 + 0.6)))

# KiCad's footprint for U8 names a 3D model its library doesn't have: show the same 3 x 3 mm TQFN body (renders only)
for f in FPS:
    ms = f.Models()                       # (iterating gives copies: edit by index)
    for i in range(len(ms)):
        if ms[i].m_Filename.endswith("TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm.step"):
            m = ms[i]; m.m_Filename = m.m_Filename.replace("EP1.23x1.23mm", "EP1.6x1.6mm"); ms[i] = m
placed = hidden = 0
# buttons first (two small spots), then plugs (their labels matter most), then chips, then the rest
for f in sorted(FPS, key=lambda f: ("SJTUQDLF".find(f.GetReference()[0]) % 10, f.GetReference())):
    ref, side = f.GetReference(), f.IsFlipped()
    # plugs and test pads show their Value (BATTERY, TXD0 ...): the Reference field's text IS the part's designator, so
    # it's never renamed; for these it's hidden, for the rest the Value is
    big = ref[0] == "J" or ref.startswith("TP")
    btn = ref.startswith("SW")
    t, other = (f.Value(), f.Reference()) if big or btn else (f.Reference(), f.Value())
    other.SetVisible(False)
    if ref.startswith("H"): t.SetVisible(False); continue
    if ref in NAMES: f.SetValue(NAMES[ref])
    s = 0.8                                   # the board's minimum silk text height
    t.SetTextSize(pcbnew.VECTOR2I(mm(s), mm(s))); t.SetTextThickness(mm(s * 0.15))
    t.SetLayer(pcbnew.B_SilkS if side else pcbnew.F_SilkS); t.SetTextAngleDegrees(0); t.SetKeepUpright(True)
    t.SetVisible(True)
    cb = body(f)
    cx, cy = cb.Centre().x, cb.Centre().y
    hw, hh = cb.GetWidth() // 2, cb.GetHeight() // 2
    gap = mm(s * 0.75)
    spots = [(cx, cb.GetY() - gap), (cx, cb.GetBottom() + gap), (cb.GetX() - gap - mm(s * len(t.GetText()) * 0.35), cy),
             (cb.GetRight() + gap + mm(s * len(t.GetText()) * 0.35), cy),
             (cb.GetX(), cb.GetY() - gap), (cb.GetRight(), cb.GetY() - gap), (cb.GetX(), cb.GetBottom() + gap), (cb.GetRight(), cb.GetBottom() + gap)]
    for k in (1.6, 2.4):                    # a little further out too
        spots += [(cx, cb.GetY() - gap * k), (cx, cb.GetBottom() + gap * k)]
    for fx in (-0.5, 0.5, -1.0, 1.0):       # and slid along it
        dx = int(fx * cb.GetWidth() / 2)
        spots += [(cx + dx, cb.GetY() - gap), (cx + dx, cb.GetBottom() + gap), (cx + dx, cb.GetY() - gap * 1.6), (cx + dx, cb.GetBottom() + gap * 1.6)]
    # a plug with no room beside it on its own side gets its name on the other side, right under it (the housing would
    # cover a label on its own body). SMD plugs only: a through-hole plug's pins are there
    if btn:                                   # right of the button: between its pads (at its corners), else further out
        spots = [(cb.GetRight() + mm(k / 10), cy + mm(d / 10)) for d in (-20, -22, -24, -26) for k in range(3, 25)]   # up by its top corner: the two buttons sit 1 mm apart at their side pads
    tries = [(side, xy, s) for xy in spots]
    if big and all(p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD for p in f.Pads() if p.GetNumber() != "MP"):
        tries += [(not side, xy, s) for xy in [(cx, cy)] + spots]
    if s > 0.8: tries += [(sd, xy, 0.8) for sd, xy, _ in tries]   # a plug's name that won't fit gets a go at 0.8 mm
    tries = [(sd, xy, sz, 0) for sd, xy, sz in tries]
    if big:                                   # a plug's name centred over it, up to 5 mm out, before anything further off
        tries = [(side, (cx + mm(dx / 10), cb.GetY() - mm(dy / 10)), s, 0) for dy in range(4, 50, 2) for dx in (0, -5, 5, -10, 10)] + tries
    if big:                                   # a plug's name may also stand on end in a narrow gap beside it (own side first)
        hw = cb.GetWidth() // 2 + gap; side_spots = [(cx - hw, cy), (cx + hw, cy), (cx - hw, cb.GetY()), (cx + hw, cb.GetY())]
        tries = [tr for tr in tries if tr[0] == side] + [(side, xy, s, 90) for xy in side_spots] + [tr for tr in tries if tr[0] != side]
    for sd, (x, y), sz, ang in tries:
        t.SetTextSize(pcbnew.VECTOR2I(mm(sz), mm(sz))); t.SetTextThickness(mm(sz * 0.15)); t.SetTextAngleDegrees(ang)
        t.SetLayer(pcbnew.B_SilkS if sd else pcbnew.F_SilkS); t.SetMirrored(sd)
        t.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
        tb = box(t.GetBoundingBox(), 0.1)
        if not (edge[0] <= tb[0] and tb[2] <= edge[2] and edge[1] <= tb[1] and tb[3] <= edge[3]): continue
        if any(hit(tb, o) for o in blocked[sd]): continue
        blocked[sd].append(tb); placed += 1; break
    else:
        t.SetVisible(False); hidden += 1
# maker, board id and version: one two-line block, in the first clear spot (a grid scan, bottom side first, then top)
BOARD_TEXT = "baunuri.com\nPOPM-HAT rev A"
for d in list(b.Drawings()):
    if d.GetClass() == "PCB_TEXT" and d.GetText().startswith("baunuri.com"): b.Remove(d)
t = pcbnew.PCB_TEXT(b); t.SetText(BOARD_TEXT); b.Add(t)
for sd in (True, False):
    for sz in (1.0, 0.8):
        t.SetTextSize(pcbnew.VECTOR2I(mm(sz), mm(sz))); t.SetTextThickness(mm(sz * 0.15))
        t.SetLayer(pcbnew.B_SilkS if sd else pcbnew.F_SilkS); t.SetMirrored(sd)
        ok = False
        for gy in range(30, int(H * 10) - 30, 5):
            for gx in range(60, int(W * 10) - 60, 5):
                t.SetPosition(pcbnew.VECTOR2I(mm(X0 + gx / 10), mm(Y0 + gy / 10)))
                tb = box(t.GetBoundingBox(), 0.2)
                if edge[0] <= tb[0] and tb[2] <= edge[2] and edge[1] <= tb[1] and tb[3] <= edge[3] and not any(hit(tb, o) for o in blocked[sd]):
                    ok = True; break
            if ok: break
        if ok: break
    if ok: break
assert ok, "no room for the baunuri.com / board id block"
print("board text on", "bottom" if sd else "top", f"at {gx/10:.1f}, {gy/10:.1f} mm, {sz} mm high")
b.Save("popm_board.kicad_pcb")
print(f"labels placed {placed}, hidden {hidden}")
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", "popm_board-drc.json", "popm_board.kicad_pcb"])
