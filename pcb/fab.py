# JLCPCB files for a board: Gerbers + drills (zip), BOM and CPL (pick and place), into fab/.
#   .venv/bin/python fab.py [board.kicad_pcb]
# LCSC part numbers come from popm_board.net (the footprints don't carry them). Mounting holes and test pads aren't parts.
import csv, os, re, shutil, subprocess, sys
from collections import defaultdict
here = os.path.dirname(os.path.abspath(__file__))
board = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "popm_board.kicad_pcb")
out = os.path.join(here, "fab"); g = os.path.join(out, "gerber")

# ---- gate: no fab files unless the board passes. ERC clean, DRC with nothing unconnected and no violation outside
# WAIVE (each one written down with its reason), every part in stock at JLC for BOARDS boards.
import json
WAIVE = [   # (DRC type, the footprints it's about, why it's fine)
    ("courtyards_overlap", {"U4", "H1"}, "the module's courtyard includes its antenna keep-out (15 mm round the antenna); the hole is bare (NPTH) and clear of the module itself"),
    ("silk_edge_clearance", {"J1"}, "the XT30's mouth overhangs the edge on purpose; JLC clips its outline"),
    ("silk_edge_clearance", {"U4"}, "the module's antenna overhangs the edge on purpose (Espressif's layout guide)"),
    ("silk_edge_clearance", {"J4"}, "the USB-C mouth overhangs the edge on purpose"),
    ("courtyards_overlap", {"C19", "U4"}, "the same margin (the module's courtyard includes its antenna keep-out): the module's EN cap, by its EN pin; pad copper is 1 mm apart"),
    ("courtyards_overlap", {"U8", "R23"}, "the amp's shutdown resistor right at its pin 4 (anywhere else its track crosses I2S_DIN): the courtyard margins overlap 0.16 mm, pad copper is 0.38 mm apart"),
    ("silk_over_copper", {"U8"}, "the amp's pin-1 mark touches that resistor's pad: JLC clips silkscreen off pads; placement uses the CPL"),
    ("lib_footprint_mismatch", {"U4"}, "pads, keep-out, outline and 3D model match KiCad's library copy (checked by script); only board-side text / fill state differs"),
    ("items_not_allowed", {"H1"}, "the module footprint's antenna keep-out reaches the bare (NPTH, no copper) mounting hole: nothing conductive there"),
] + [("starved_thermal", {r}, "a through-hole GND pin with fewer spokes on one outer layer: still on the solid GND plane (inner layer 1) and its other side; easier to solder")
     for r in ("J5", "J13")]
WAIVE_TYPES = {"lib_footprint_issues": "no footprint library table in the project: footprints come from KiCad's own library (kinet2pcb)"}
erc = subprocess.run([sys.executable, os.path.join(here, "popm_board.py")], cwd=here, capture_output=True, text=True)
assert "No errors or warnings found while running ERC" in erc.stdout + erc.stderr, "ERC is not clean: no fab files"
drc_json = os.path.join(here, "popm_board-drc.json")
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "--schematic-parity", "-o", drc_json, board], capture_output=True)
drc = json.load(open(drc_json))
refs = lambda v: set(re.findall(r"(?:of|Footprint) ([A-Z]+\d+)\b", " ".join(i["description"] for i in v["items"])))
bad = [v for v in drc["violations"] if v["type"] not in WAIVE_TYPES and
       not any(v["type"] == t and refs(v) == r for t, r, _ in WAIVE)]
for v in bad: print("DRC:", v["type"], "|", " / ".join(i["description"] for i in v["items"]))
assert not drc["unconnected_items"], f"{len(drc['unconnected_items'])} unconnected: no fab files"
# parity (KiCad's needs a .kicad_sch; ours is SKiDL code): every numbered pad on the netlist's net
_net = open(os.path.join(here, "popm_board.net")).read()
want = {}
for body in re.split(r"\(net\s*\(code", _net)[1:]:
    nm = re.search(r'\(name "([^"]+)"\)', body).group(1)
    for ref, pin in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', body): want[(ref, pin)] = nm
import pcbnew as _pn0
have = {(f.GetReference(), q.GetNumber()): q.GetNetname() for f in _pn0.LoadBoard(board).GetFootprints() for q in f.Pads() if q.GetNumber()}
diff = [(k, have.get(k), w) for k, w in want.items() if have.get(k) != w and not w.startswith("NC")] + \
       [(k, h, None) for k, h in have.items() if k not in want and h]
assert not diff, f"board and netlist differ ({len(diff)}): {diff[:5]}: no fab files"
assert not bad, f"{len(bad)} DRC violations outside the written waivers: no fab files"
# the battery / servo trunk must be one piece of >= 1 mm copper on one layer at a time, joined at pads only (no via in the path) (DRC can't see a 5 A path necked to 0.25 mm)
TRUNK = {"BAT_RAW": ["J1.2", "Q1.5"], "VBAT_FET": ["Q1.1", "F1.1"], "VBAT": ["F1.2", "C1.1", "J5.2", "J6.2"]}
_b = _pn0.LoadBoard(board); par = {}
def _f(x):
    while par.setdefault(x, x) != x: par[x] = par[par[x]]; x = par[x]
    return x
_objs = [(f"t{k}", t) for k, t in enumerate(_b.GetTracks()) if t.GetNetname() in TRUNK and
         t.Type() != _pn0.PCB_VIA_T and _pn0.ToMM(t.GetWidth()) >= 0.99] + \
        [(fp.GetReference() + "." + q.GetNumber(), q) for fp in _b.GetFootprints() for q in fp.Pads() if q.GetNetname() in TRUNK]
for k, (na, a_) in enumerate(_objs):
    for nb, c_ in _objs[k + 1:]:
        if a_.GetNetname() == c_.GetNetname() and any(a_.IsOnLayer(L) and c_.IsOnLayer(L) and a_.GetEffectiveShape(L).Collide(c_.GetEffectiveShape(L), 0)
                                                      for L in (_pn0.F_Cu, _pn0.B_Cu, _pn0.In2_Cu)): par[_f(na)] = _f(nb)
thin = [net for net, ps in TRUNK.items() if len({_f(p_) for p_ in ps}) > 1]
assert not thin, f"battery trunk not all >= 1 mm copper on {thin}: no fab files"
print(f"gate: ERC clean, board = netlist, battery trunk >= 1 mm, DRC 0 unconnected, {len(drc['violations'])} items, all waived:")
for t, r, why in WAIVE: print(f"   {t} {'/'.join(sorted(r))}: {why}")
print("ORDER WITH: 4 layers, 1.6 mm, outer copper 1 oz, INNER COPPER 1 oz (not the 0.5 oz default: the battery trunk may use it)")

shutil.rmtree(out, ignore_errors=True); os.makedirs(g)
run = lambda *a: subprocess.run(["kicad-cli", "pcb", "export", *a, board], check=True, capture_output=True)

run("gerbers", "-o", g + "/", "--layers", "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts")
run("drill", "-o", g + "/", "--format", "excellon", "-u", "mm", "--excellon-separate-th")
shutil.make_archive(os.path.join(out, "popm_gerbers"), "zip", g)

net = open(os.path.join(here, "popm_board.net")).read()
lcsc = {m.group(1): (re.search(r'\(name "LCSC"\)\s*"([^"]*)"', m.group(2)) or [None, ""])[1]
        for m in re.finditer(r'\(comp\s*\(ref "([^"]+)"\)(.*?)\(tstamps', net, re.S)}
part = lambda r: not r.startswith(("H", "TP", "JP"))   # holes, test pads, solder jumpers: bare copper

pos = os.path.join(out, "pos.csv")
run("pos", "-o", pos, "--format", "csv", "--units", "mm", "--side", "both")
rows = [r for r in csv.DictReader(open(pos)) if part(r["Ref"])]
# Everything is assembled by JLC, the through-hole plugs too (hand soldering at JLC: a few $ per board on top).
# HAND=1 leaves the through-hole plugs off the order and writes an LCSC cart for them instead (BOARDS boards + 1 spare)
import pcbnew as _pn
_B = _pn.LoadBoard(board)
hand = {f.GetReference() for f in _B.GetFootprints() if f.GetAttributes() & _pn.FP_THROUGH_HOLE} if os.environ.get("HAND") == "1" else set()
BOARDS = int(os.environ.get("BOARDS", "2"))
if hand:
    per = defaultdict(list)
    for r in rows:
        if r["Ref"] in hand: per[lcsc[r["Ref"]]].append(r)
    with open(os.path.join(out, "popm_hand_solder_lcsc.csv"), "w", newline="") as fo:
        w = csv.writer(fo); w.writerow(["LCSC Part Number", "Quantity", "Comment"])
        for code, rs in sorted(per.items(), key=lambda x: x[1][0]["Ref"]):
            w.writerow([code, len(rs) * BOARDS + 1, " ".join(r["Ref"] for r in rs) + " " + rs[0]["Val"] + " (solder by hand)"])
OWN = {"J13": "the Pi header: a tall 2 x 20 stacking header (15-16 mm spacers on a Pi 5), bought elsewhere (JLC has none that takes a Pi's square pins)"}
rows = [r for r in rows if r["Ref"] not in hand and r["Ref"] not in OWN]   # OWN: left off, soldered by you
os.remove(pos)
# Placement: JLC places its own footprint for each LCSC part (EasyEDA's), at its own origin and its own 0 degrees, which
# for many parts differ from KiCad's (SOT-23s 270 degrees off, a plug's origin at pin 1 ...). So fetch that footprint
# (cached in .jlc_cache/) and, per part, find the rotation (mirrored for the bottom) and origin that put JLC's numbered
# pads on ours. PADMAP: where JLC numbers pads differently from KiCad (our pad -> JLC pads, averaged).
import json, math, time, pcbnew
B = pcbnew.LoadBoard(board)
CACHE = os.path.join(here, ".jlc_cache"); os.makedirs(CACHE, exist_ok=True)
PADMAP = {"C2286": {"1": ["2"], "2": ["1"]},          # red LED: JLC's pad 1 is the anode, KiCad's the cathode
          "C318884": {"1": ["3", "4"], "2": ["1", "2"]},   # buttons: KiCad pairs a row as 1 / 2, JLC numbers 1-4 (rows 1-2, 3-4)
          "C585350": {**{str(n): [str(n)] for n in range(1, 9)}, "9": ["11"], "10": ["12"], "11": ["9", "10", "13", "14"]}}   # microSD: card pins
          # agree; KiCad's detect switch 9 / 10 is JLC's 11 / 12, and KiCad numbers all four shell tabs 11 (JLC: 9, 10, 13, 14)
def jlc_pads(code):
    p = os.path.join(CACHE, code + ".json")
    for attempt in range(4):                  # its CDN sometimes answers with an error page: only cache real JSON
        if os.path.exists(p): break
        r = subprocess.run(["curl", "-s", "-m", "30", f"https://easyeda.com/api/products/{code}/components?version=6.4.19.5"], capture_output=True, text=True)
        try: json.loads(r.stdout)["result"]["packageDetail"]; open(p, "w").write(r.stdout)
        except Exception: time.sleep(2 + 3 * attempt)
    ds = json.load(open(p))["result"]["packageDetail"]["dataStr"]
    hx, hy = float(ds["head"]["x"]), float(ds["head"]["y"])
    pads = defaultdict(list)                  # JLC pad number -> [(x, y) mm from JLC's origin, y down]
    for sh in ds["shape"]:
        if sh.startswith("PAD~"):
            f = sh.split("~"); xy = ((float(f[2]) - hx) * 0.254, (float(f[3]) - hy) * 0.254)   # EasyEDA units: 10 mil
            for n in (re.findall(r"[AB]\d+", f[8]) if re.fullmatch(r"([AB]\d+){2,}", f[8]) else [f[8]]): pads[n].append(xy)   # USB-C "A1B12"
    return pads
avg = lambda ps: (sum(q[0] for q in ps) / len(ps), sum(q[1] for q in ps) / len(ps))
def place(ref):
    f = B.FindFootprintByReference(ref); code = lcsc[ref]; jp = jlc_pads(code); pm = PADMAP.get(code)
    kp = defaultdict(list)
    for q in f.Pads():
        if q.GetNumber(): kp[q.GetNumber()].append((pcbnew.ToMM(q.GetPosition().x), pcbnew.ToMM(q.GetPosition().y)))
    if pm: pairs = [(avg(kp[n]), avg([e for m in pm[n] for e in jp[m]])) for n in pm]
    else: pairs = [(kp[n][0], jp[n][0]) for n in kp if len(kp[n]) == 1 and len(jp.get(n, [])) == 1]   # numbers once on both
    assert len(pairs) >= 2, f"{ref}: too few matching pads with JLC's footprint ({code})"
    best = None
    for a in (0, 90, 180, 270):               # CCW as seen from the top; the bottom mirrors JLC's footprint first
        c, sn = math.cos(math.radians(a)), math.sin(math.radians(a))
        def tr(e):
            x = -e[0] if f.IsFlipped() else e[0]
            return (x * c + e[1] * sn, -x * sn + e[1] * c)
        d = [(k[0] - tr(e)[0], k[1] - tr(e)[1]) for k, e in pairs]
        T = avg(d); err = max(math.dist(x, T) for x in d)
        if best is None or err < best[0]: best = (err, a, T)
    err, a, T = best
    # big pads (2920 fuse, 6 mm inductor) are drawn a little differently by KiCad and EasyEDA: the part still centres
    assert err < 0.6, f"{ref}: JLC's footprint ({code}) doesn't fit ours: {err:.2f} mm off at best"
    if err > 0.15: print(f"  note: {ref} ({code}) JLC's pads sit up to {err:.2f} mm from ours (land-pattern difference)")
    # JLC reads a bottom part's rotation as seen from below, i.e. the other way round (worked out from their viewer:
    # U3/U5/U6/Q2 wrong as a, U7/U8/USB-C right only because 180 / 0 read the same both ways)
    return T[0], -T[1], ((-a) % 360 if f.IsFlipped() else a)   # kicad-cli / Gerber frame: y up
with open(os.path.join(out, "popm_cpl.csv"), "w", newline="") as fo:
    w = csv.writer(fo); w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in rows:
        x, y, a = place(r["Ref"])
        w.writerow([r["Ref"], f"{x:.4f}mm", f"{y:.4f}mm", "Top" if r["Side"] == "top" else "Bottom", a])
bom = defaultdict(list)                   # one line per LCSC part (else JLC warns that several lines match one part)
for r in rows: bom[lcsc.get(r["Ref"], "")].append(r)
with open(os.path.join(out, "popm_bom.csv"), "w", newline="") as fo:
    w = csv.writer(fo); w.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])   # the header JLC reads
    for l, rs in sorted(bom.items(), key=lambda x: x[1][0]["Ref"]):
        w.writerow([" / ".join(sorted({r["Val"] for r in rs})), ",".join(r["Ref"] for r in rs), rs[0]["Package"], l])
missing = [r["Ref"] for rs in bom.values() for r in rs if not lcsc.get(r["Ref"])]
def jlc_stock(code):                          # live: JLC's parts library (same API as their BOM tool)
    r = subprocess.run(["curl", "-s", "-m", "20", "-A", "Mozilla/5.0", "-H", "Content-Type: application/json", "-X", "POST",
                        "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList",
                        "-d", json.dumps({"keyword": code, "currentPage": 1, "pageSize": 5})], capture_output=True, text=True).stdout
    try: return next((c["stockCount"] for c in json.loads(r)["data"]["componentPageInfo"]["list"] or [] if c["componentCode"] == code), 0)
    except Exception: return None
short = []
for code, rs in bom.items():
    st = jlc_stock(code)
    if st is None: print("  stock check failed for", code, "(network?)")
    elif st < len(rs) * BOARDS + 20: short.append((code, rs[0]["Val"], st))   # + JLC's attrition
assert not short, f"not enough stock at JLC: {short}"
assert not missing, f"no LCSC number: {missing}"
# the schematic (sch.py: drawn from the same netlist, checked against it pin for pin, ERC'd), next to the order files
subprocess.run([sys.executable, os.path.join(here, "sch.py")], check=True)
shutil.copy(os.path.join(here, "sch", "popm_schematic.pdf"), out)
print(out, f"{len(rows)} parts for JLC, {len(bom)} BOM lines; by hand (LCSC cart): {sorted(hand) or 'none'}; left off: " + "; ".join(f"{k} ({v})" for k, v in OWN.items()))
