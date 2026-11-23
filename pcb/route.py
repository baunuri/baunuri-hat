# Autoroutes popm_board.kicad_pcb with Freerouting (after layout.py and preroute.py), fills the planes, saves, and runs DRC.
#   .venv/bin/python route.py
# Freerouting 1.9.0: ~/.local/share/freerouting/freerouting-1.9.0.jar (github.com/freerouting/freerouting releases;
# 2.1 ignores its pass limit and loops). Each stage runs in a fresh process: after items are removed, pcbnew's SWIG
# wrappers in that process go bad (b.Zones(), b.FindNet() return dead objects).
#   pass 1: every net at its netclass width (battery 1.2 mm, rails 0.6 mm)
#   pass 2: what pass 1 couldn't fit (a wide track can't enter an 0603 / USB-C / QFN / LGA pad) at 0.25 mm, keeping
#   pass 1's tracks, on any layer
import os, subprocess, sys, pcbnew
JAR = os.path.expanduser("~/.local/share/freerouting/freerouting-1.9.0.jar")
WIDE = {"Battery": 2.0, "Rail": 0.6, "Logic": 0.4}   # as layout.py sets them (Logic = +3V3: the IMU's LGA pins are 0.5 mm apart)
from board import W, H

def freeroute(dsn, ses):           # -oit: stop optimizing once a pass gains < 0.1 (it once ran on for 10+ min)
    subprocess.run(["xvfb-run", "-a", "java", "-jar", JAR, "-de", dsn, "-do", ses, "-mp", os.environ.get("FR_PASSES", "40"), "-oit", "0.1"], check=True, timeout=1500)

def widths(b, w=None):
    for name, wide in WIDE.items():
        b.GetDesignSettings().m_NetSettings.GetNetClassByName(name).SetTrackWidth(pcbnew.FromMM(w or wide))

stage = sys.argv[1] if len(sys.argv) > 1 else "start"
b = pcbnew.LoadBoard("popm_board.kicad_pcb")
if stage == "start":
    # outer GND pours make Freerouting think GND pads are already joined (it then adds no vias to the GND plane):
    # route without them, put them back at the end. Listed before anything is removed.
    outer = [z for z in b.Zones() if z.GetNetname() == "GND" and z.GetLayer() in (pcbnew.F_Cu, pcbnew.B_Cu)]
    for t in list(b.GetTracks()):
        if not t.IsLocked(): b.Remove(t)          # locked = drawn by preroute.py: Freerouting keeps them too
    for z in outer: b.Remove(z)
    b.Save("popm_board.kicad_pcb")
    pcbnew.ExportSpecctraDSN(b, "popm_board.dsn")
    freeroute("popm_board.dsn", "popm_board.ses")
    subprocess.run([sys.executable, __file__, "pass2"], check=True)
elif stage == "pass2":
    pcbnew.ImportSpecctraSES(b, "popm_board.ses")
    widths(b, 0.25)
    b.Save("popm_board.kicad_pcb")
    pcbnew.ExportSpecctraDSN(b, "popm_board-2.dsn")   # any layer: what's left here is small (sense pins, 0.25 mm);
                                                      # fab.py checks the battery's main path stays off the inner layers
    freeroute("popm_board-2.dsn", "popm_board-2.ses")
    subprocess.run([sys.executable, __file__, "finish"], check=True)
elif stage == "finish":
    pcbnew.ImportSpecctraSES(b, "popm_board-2.ses")
    widths(b)
    # whatever Freerouting still left unconnected (signal / sense links in tight spots): the grid search (pathfind.py)
    # draws it at 0.25 mm, before the pours go in. GND is left to stitch.py.
    import json, re, pathfind
    b.Save("popm_board.kicad_pcb")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", "popm_board-drc.json", "popm_board.kicad_pcb"], capture_output=True)
    def spec(i):
        d = i["description"]; m = re.match(r"(?:PTH )?[Pp]ad (\S+) \[([^\]]+)\] of (\S+)", d)
        if m: return m.group(2), ("pad", m.group(3), m.group(1))
        m = re.match(r"(Track|Via) \[([^\]]+)\] on ([A-Za-z0-9]+\.Cu)", d)
        if m: return m.group(2), ("at", i["pos"]["x"] - 100, i["pos"]["y"] - 100, [0, 1, 2] if m.group(1) == "Via" else [{"F.Cu": 0, "B.Cu": 1, "In2.Cu": 2}[m.group(3)]])
        return None, None
    for u in json.load(open("popm_board-drc.json"))["unconnected_items"]:
        (na, ea), (nb, eb) = (spec(i) for i in u["items"])
        if not ea or not eb or na != nb or na == "GND": continue
        pts = pathfind.find(b, na, ea, eb, 0.25)
        print("finish:", na, "drawn" if pts else "NO PATH", ea[:3], eb[:3])
        if pts: pathfind.draw(b, na, pts, 0.25, locked=False)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(b); z.SetLayer(layer); z.SetNet(b.FindNet("GND"))
        o = z.Outline(); o.NewOutline()
        for x, y in ((0, 0), (W, 0), (W, H), (0, H)): o.Append(pcbnew.VECTOR2I(pcbnew.FromMM(100 + x), pcbnew.FromMM(100 + y)))
        z.SetLocalClearance(pcbnew.FromMM(0.2)); z.SetMinThickness(pcbnew.FromMM(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)   # SMD pads solid, THT pins on spokes (solderable)
        b.Add(z)
    # the LDO's tab (+3V3) gets a copper area to shed its ~0.5 W into, on its side, over the GND pour there
    # (over the whole regulator: its tab and its middle pin are both "2", joined inside it; the pour joins them here too)
    u3 = b.FindFootprintByReference("U3"); L = pcbnew.B_Cu if u3.IsFlipped() else pcbnew.F_Cu
    xs = [q.GetPosition().x for q in u3.Pads()]; ys = [q.GetPosition().y for q in u3.Pads()]; m = pcbnew.FromMM(2.5)
    z = pcbnew.ZONE(b); z.SetLayer(L); z.SetNet(b.FindNet("+3V3")); z.SetAssignedPriority(1)
    o = z.Outline(); o.NewOutline()
    for x, y in ((min(xs) - m, min(ys) - m), (max(xs) + m, min(ys) - m), (max(xs) + m, max(ys) + m), (min(xs) - m, max(ys) + m)):
        o.Append(pcbnew.VECTOR2I(x, y))
    z.SetLocalClearance(pcbnew.FromMM(0.2)); z.SetMinThickness(pcbnew.FromMM(0.2)); z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    b.Add(z)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save("popm_board.kicad_pcb")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", "popm_board-drc.json", "popm_board.kicad_pcb"])
