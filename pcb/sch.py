# The schematic as KiCad sheets, drawn from popm_board.net: the circuit in blocks (battery input, buck, ESP32, CAN ...), each
# framed on its page with its parts placed round its chip and wired to it; labels only where a signal leaves its block, power
# symbols on the rails. kicad-cli then re-reads its netlist (it must equal popm_board.net, pin for pin), runs ERC, prints the PDF.
#   .venv/bin/python sch.py -> sch/popm_schematic.pdf
import ast, os, re, subprocess, sys, uuid
from collections import defaultdict

here = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(here, "sch"); os.makedirs(OUT, exist_ok=True)
SYMDIR = "/usr/share/kicad/symbols"
PROJ = "popm_schematic"

# ---- s-expressions --------------------------------------------------------------------------------------------------
def parse(t):
    toks = re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+', t); i = 0
    def node():
        nonlocal i
        if toks[i] == "(":
            i += 1; out = []
            while toks[i] != ")": out.append(node())
            i += 1; return out
        tok = toks[i]; i += 1
        return Q(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\")) if tok.startswith('"') else tok
    return node()
class Q(str): pass                        # a quoted string (vs a bare keyword / number)
def dump(x, ind=0):
    if not isinstance(x, list):
        if isinstance(x, Q): return '"' + x.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
        if isinstance(x, float): return f"{x:.4f}".rstrip("0").rstrip(".")
        return str(x)
    if not any(isinstance(y, list) for y in x): return "(" + " ".join(dump(y) for y in x) + ")"
    k = next(i for i, y in enumerate(x) if isinstance(y, list))
    return "(" + " ".join(dump(y) for y in x[:k]) + "".join("\n" + "  " * (ind + 1) + dump(y, ind + 1) for y in x[k:]) + ")"
def kids(x, k): return [y for y in x if isinstance(y, list) and y and y[0] == k]
def kid(x, k): return next(iter(kids(x, k)), None)
U = lambda: Q(str(uuid.uuid4()))
FONT = ["effects", ["font", ["size", 1.27, 1.27]]]

# ---- the netlist --------------------------------------------------------------------------------------------------------
net = parse(open(os.path.join(here, "popm_board.net")).read())
comps = {}
for c in kids(kid(net, "components"), "comp"):
    ls = kid(c, "libsource")
    fields = {f[1][1]: f[2] for f in kids(kid(c, "fields") or [], "field") if len(f) > 2}
    comps[kid(c, "ref")[1]] = dict(value=kid(c, "value")[1], lib=kid(ls, "lib")[1], part=kid(ls, "part")[1],
                                   fp=(kid(c, "footprint") or [0, ""])[1], lcsc=fields.get("LCSC", ""))
pinnet = {}; netnodes = defaultdict(set)
for n in kids(kid(net, "nets"), "net"):
    name = kid(n, "name")[1]
    for nd in kids(n, "node"):
        pinnet[(kid(nd, "ref")[1], kid(nd, "pin")[1])] = name; netnodes[name].add((kid(nd, "ref")[1], kid(nd, "pin")[1]))

# ---- library symbols (flattened: a derived symbol takes its parent's drawing) -----------------------------------------
libs = {}
def libsym(lib, name):
    if lib not in libs:
        libs[lib] = {s[1]: s for s in kids(parse(open(f"{SYMDIR}/{lib}.kicad_sym").read()), "symbol")}
    s = [y for y in libs[lib][name]]
    ext = kid(s, "extends")
    if ext:
        base = libsym(lib, ext[1]); s = [y for y in s if not (isinstance(y, list) and y[0] == "extends")]
        props = {p[1] for p in kids(s, "property")}
        s += [p for p in kids(base, "property") if p[1] not in props]
        for k in ("pin_names", "pin_numbers", "power"):
            if kid(base, k) and not kid(s, k): s.append(kid(base, k))
        s += [[y[0], Q(y[1].replace(ext[1], name, 1))] + y[2:] for y in kids(base, "symbol")]
    return s
import copy
SO8 = {"G": ["4"], "S": ["1", "2", "3"], "D": ["5", "6", "7", "8"]}   # popm_board.py so8_fet(): the 3-pin symbol on 8 pins
def so8(s):
    s = copy.deepcopy(s)
    for sub in kids(s, "symbol"):
        for p in kids(sub, "pin"):
            nums = SO8[kid(p, "name")[1]]; kid(p, "number")[1] = Q(nums[0])
            for n in nums[1:]:
                q = copy.deepcopy(p); kid(q, "number")[1] = Q(n); sub.append(q)   # stacked on the first: one node
    return s
def units(s):                             # unit -> [(num, name, x, y, angle, length)], unit 0 = common to all units
    out = defaultdict(list); draw = defaultdict(list)
    for sub in kids(s, "symbol"):
        u, st = map(int, sub[1].rsplit("_", 2)[1:])
        if st > 1: continue               # De Morgan alternates
        for p in kids(sub, "pin"):
            at = kid(p, "at"); out[u].append((kid(p, "number")[1], kid(p, "name")[1], float(at[1]), float(at[2]),
                                                float(at[3]) if len(at) > 3 else 0.0, float(kid(p, "length")[1]), "hide" in p or ["hide", "yes"] in p))
        for g in sub:
            if isinstance(g, list) and g[0] in ("rectangle", "polyline", "circle", "arc"):
                for k in ("start", "end", "center", "mid"):
                    if kid(g, k): draw[u].append((float(kid(g, k)[1]), float(kid(g, k)[2])))
                if g[0] == "circle" and kid(g, "radius"):
                    cx, cy, rr = float(kid(g, "center")[1]), float(kid(g, "center")[2]), float(kid(g, "radius")[1])
                    draw[u] += [(cx - rr, cy - rr), (cx + rr, cy + rr)]
                for xy in kids(kid(g, "pts") or [], "xy"): draw[u].append((float(xy[1]), float(xy[2])))
    return out, draw

# ---- blocks: each a framed group on its page, its parts wired together; labels only where a signal leaves the block ----
PAGES = ["Power: battery, 5 V, 3.3 V", "ESP32-S3, USB-C", "Sensors, I2C plugs, audio, servos, UART",
         "Pi header, IO expander, microSD, CAN, RS485"]
BLOCKS = [  # page, title, anchor parts (chips / plugs); the passives join the block of the part they serve
    (0, "Battery in: reverse-polarity FET, fuse, TVS", "J1 Q1 D1 F1 D2"),
    (0, "5 V buck", "U2 L1"),
    (0, "3.3 V regulator, 5 V from USB or buck", "U3 D3 D4"),
    (1, "ESP32-S3 module, reset / boot buttons, LED", "U4 SW1 SW2 D5"),
    (1, "USB-C", "J4 U5"),
    (2, "IMU", "U7"), (2, "ToF sensor, Qwiic", "J9 J10"), (2, "I2C bus B plugs", "J7 J8"),
    (2, "Audio amp", "U8 J11"), (2, "Servo bus", "U6 J5 J6"), (2, "UART plug (co-processor: TX / RX / EN / BOOT)", "J12"),
    (3, "Pi header, IO expander", "J13 U9"), (3, "microSD", "J14"), (3, "CAN", "U10 J15"), (3, "RS485", "U11 J16"),
]
POWER = {"GND", "+3V3", "+5V", "+5V4", "VBAT", "VBUS"}
src = open(os.path.join(here, "layout.py")).read()
i = src.index("SAT = {"); j = src.index("}", i)
SAT = ast.literal_eval(src[i + 6:j + 1])
blk_of, order = {}, {}
for k, (_, _, anchors) in enumerate(BLOCKS):
    for a in anchors.split(): blk_of[a] = k; order[a] = a
for a, sats in SAT.items():
    for r in sats.split():
        if r not in blk_of and a in order: blk_of[r] = blk_of[order[a]]; order[r] = order[a]
def nets_of(r): return {n for (q, _), n in pinnet.items() if q == r}
for r in sorted(comps):
    if r in blk_of: continue
    best = None
    for skip in (POWER, {"GND"}):
        score = defaultdict(int)
        for n in nets_of(r) - skip:
            for q, _ in netnodes[n]:
                if q in order and q != r: score[order[q]] += 1
        if score: best = max(score, key=lambda a: (score[a], -list(blk_of).index(a))); break
    if best is None: best = "J13"         # no nets (the mounting holes): with the Pi header
    blk_of[r] = blk_of[best]; order[r] = best
net_blocks = defaultdict(set)
for (r, _), n in pinnet.items(): net_blocks[n].add(blk_of[r])

ptype = {}                                # a net with a power input but nothing driving it gets a PWR_FLAG (ERC)
def sym_of(r):
    c = comps[r]; s = libsym(c["lib"], c["part"])
    if c["fp"].startswith("Package_SO:SOIC-8") and c["part"].startswith("Q_"): s = so8(s)
    return f"{c['lib']}:{c['part']}", s
for r in comps:
    for sub in kids(sym_of(r)[1], "symbol"):
        for p in kids(sub, "pin"): ptype[(r, kid(p, "number")[1])] = p[1]
flagged = sorted(n for n, nodes in netnodes.items()
                 if (n in POWER or any(ptype.get(x) == "power_in" for x in nodes)) and not any(ptype.get(x) == "power_out" for x in nodes))

# ---- geometry -------------------------------------------------------------------------------------------------------
G, g = 2.54, 1.27
snap = lambda v: round(v / G) * G
TW = lambda t, h=1.27: 0.95 * h * len(t)  # text width, roughly
DIRS = {0: (-1, 0), 90: (0, 1), 180: (1, 0), 270: (0, -1)}   # a pin's angle (+ the symbol's) -> outward, sheet axes
def rotxy(x, y, rot):                     # library (y up) -> sheet offset (y down), the symbol rotated CCW by rot
    c, s_ = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[rot]
    return (x * c - y * s_, -(x * s_ + y * c))
def overlap(a, b, gap=0.0): return not (a[2] + gap <= b[0] or b[2] + gap <= a[0] or a[3] + gap <= b[1] or b[3] + gap <= a[1])
def grow(b, *pts): return (min([b[0]] + [p[0] for p in pts]), min([b[1]] + [p[1] for p in pts]), max([b[2]] + [p[0] for p in pts]), max([b[3]] + [p[1] for p in pts]))

class Item:                               # one symbol unit, placed: its pins, body, what's drawn at its pins
    def __init__(s, r, u, rot):
        s.r, s.u, s.rot = r, u, rot
        s.lid, sy = sym_of(r); pins, draw = units(sy)
        s.two = len(pins[1] + pins[0]) == 2 and max(pins) <= 1
        pts = [rotxy(x, y, rot) for x, y in draw[u] + draw[0]]
        s.pins, seen = [], {}
        for num, name, x, y, a, L, hid in pins[u] + pins[0]:
            P = rotxy(x, y, rot); P = (round(P[0] / g) * g, round(P[1] / g) * g)
            if P in seen: seen[P].append(num); continue
            seen[P] = [num]; d = DIRS[round(a + rot) % 360]
            s.pins.append([num, P, d, pinnet.get((r, num)), seen[P]])
            pts += [P, (P[0] - d[0] * L, P[1] - d[1] * L)]
        s.body = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        c = comps[r]
        if s.two:                         # name / value beside the body: right of a standing part, above a lying one
            vert = s.pins[0][2][1] != 0
            cx, cy = (s.body[0] + s.body[2]) / 2, (s.body[1] + s.body[3]) / 2
            s.texts = ([(r, s.body[2] + 0.6, cy - 0.3, "left bottom"), (c["value"], s.body[2] + 0.6, cy + 0.3, "left top")] if vert else
                       [(r + " " + c["value"], cx, s.body[1] - 0.4, "center bottom")])
        else:                             # a chip / plug: name and value at a corner clear of its top / bottom pins
            x0, y0, x1, y1 = s.body; tb = [p[1][0] for p in s.pins if p[2][1] != 0]
            def clear(xa, xb): return not any(xa - 1.5 <= x <= xb + 1.5 for x in tb)
            spots = []
            for t in (r, c["value"]):
                w = TW(t)
                for y, vj in ((y0 - 0.6 - 1.6 * sum(1 for q in spots if q[3] == "bottom"), "bottom"), (y1 + 0.6 + 1.6 * sum(1 for q in spots if q[3] == "top"), "top")):
                    if clear(x0, x0 + w): spots.append((t, x0, y, vj, "left")); break
                    if clear(x1 - w, x1): spots.append((t, x1, y, vj, "right")); break
                else: spots.append((t, x1 + 1, y0 - 0.6 - 1.6 * len(spots), "bottom", "left"))
            s.texts = [(t, x, y, f"{hj} {vj}") for t, x, y, vj, hj in spots]
        s.keep = s.body
        for t, x, y, j in s.texts:
            w = TW(t); x0 = x - (w / 2 if j.startswith("center") else w if j.startswith("right") else 0)
            s.keep = grow(s.keep, (x0, y - 1.4 if "bottom" in j else y), (x0 + w, y + 1.4 if "top" in j else y))
        s.X = s.Y = 0.0
    def at(s, P): return (s.X + P[0], s.Y + P[1])
    def box(s, b): return (s.X + b[0], s.Y + b[1], s.X + b[2], s.Y + b[3])

def pin_room(it, k):                      # what goes outward at each pin: power symbol, label, or a wire (routed)
    room = {}
    for num, P, d, n, nums in it.pins:
        if n is None: L = 1
        elif n in POWER: L = (3 * G if d[1] == 0 else G) + 4 + (TW(n) if d[1] == 0 else 0)
        elif len(net_blocks[n]) > 1 or len(netnodes[n]) == 1: L = G + TW(n) + 3
        else: L = G
        room[num] = L
    return room
def keepbox(it, k):
    b = it.keep; rm = pin_room(it, k)
    for num, P, d, n, nums in it.pins:
        L = rm[num]; e = (P[0] + d[0] * L, P[1] + d[1] * L)
        hw = TW(n) / 2 + 0.6 if n in POWER and d[1] != 0 else 1.5   # an upright power symbol's name is wider than it
        b = grow(b, e, (e[0] + (d[1] != 0) * hw, e[1] + (d[0] != 0) * hw), (e[0] - (d[1] != 0) * hw, e[1] - (d[0] != 0) * hw))
    return b

# ---- placing one block: its first chip at the middle, each next part where its pins are nearest what they join -------
def place_block(k, refs):
    items = []
    for r in refs:
        _, sy = sym_of(r); pins, _ = units(sy)
        for u in sorted(x for x in pins if x > 0) or [1]: items.append((r, u))
    anchors = BLOCKS[k][2].split()
    placed, boxes = [], []
    def conn(r):
        ns = {n for n in nets_of(r) if n not in POWER}
        return sum(1 for it in placed for p in it.pins if p[3] in ns)
    todo = list(items)
    while todo:
        if not placed: cur = todo[0]
        else:
            cur = max(todo, key=lambda x: (x[0] in anchors and conn(x[0]) > 0, conn(x[0]), x[0] in anchors, -todo.index(x)))
        todo.remove(cur); r, u = cur
        trial = Item(r, u, 0)
        rots = (0, 90, 180, 270) if trial.two else (0, 180) if comps[r]["lib"].startswith("Connector") and trial.pins and \
               all(p[2] == trial.pins[0][2] for p in trial.pins) else (0,)
        best = None
        for rot in rots:
            it = Item(r, u, rot); kb = keepbox(it, k)
            if not placed:
                best = (0, it, 0.0, 0.0); break
            cb = boxes[0]
            for b in boxes[1:]: cb = grow(cb, (b[0], b[1]), (b[2], b[3]))
            targets = defaultdict(list)
            for o in placed:
                for p in o.pins:
                    if p[3] and p[3] not in POWER: targets[p[3]].append(o.at(p[1]))
            for X in [snap(cb[0] - 40) + G * i for i in range(int((cb[2] - cb[0] + 80) / G))]:
                for Y in [snap(cb[1] - 30) + G * j for j in range(int((cb[3] - cb[1] + 60) / G))]:
                    bb = (kb[0] + X, kb[1] + Y, kb[2] + X, kb[3] + Y)
                    sc = 0.0
                    for num, P, d, n, nums in it.pins:
                        q = (X + P[0], Y + P[1])
                        if n in targets:
                            sc += min(abs(q[0] - t[0]) + abs(q[1] - t[1]) for t in targets[n])
                            sc += 3 * min((t[0] - q[0]) * -d[0] + (t[1] - q[1]) * -d[1] > 0 for t in targets[n])   # facing it
                        elif n == "GND": sc += 0 if d == (0, 1) else 8
                        elif n in POWER: sc += 0 if d == (0, -1) else 8
                    sc += 0.15 * (abs(X) + abs(Y))
                    if best is not None and sc >= best[0]: continue
                    if any(overlap(bb, b, 1.27) for b in boxes): continue
                    best = (sc, it, X, Y)
        _, it, X, Y = best
        it.X, it.Y = X, Y; placed.append(it); boxes.append(it.box(keepbox(it, k)))
    return placed

# ---- wiring one block: each net's pins joined by right-angle wires (A* on a 1.27 mm grid) ---------------------------
import heapq
def route_block(k, placed):
    BIG = {it.r for it in placed if len(it.pins) >= 12 and comps[it.r]["lib"].startswith("Connector")}
    C = lambda p: (round(p[0] / g), round(p[1] / g))
    P_ = lambda c: (c[0] * g, c[1] * g)
    blocked = set(); own = defaultdict(dict)          # cell -> net -> {"h", "v", "pt"}
    for it in placed:
        b = it.box(it.body); x0, y0, x1, y1 = C((b[0], b[1])) + C((b[2], b[3]))
        for i in range(x0, x1 + 1):
            for j in range(y0, y1 + 1): blocked.add((i, j))
        for t, x, y, jst in it.texts:
            w = TW(t); xa = it.X + x - (w / 2 if jst.startswith("center") else w if jst.startswith("right") else 0); ya = it.Y + y - (1.3 if "bottom" in jst else 0)
            for i in range(C((xa, 0))[0], C((xa + w, 0))[0] + 1):
                for j in range(C((0, ya))[1], C((0, ya + 1.3))[1] + 1): blocked.add((i, j))
    pend = {}
    for it in placed:
        for p in it.pins:
            c = C(it.at(p[1])); blocked.discard(c); pend[c] = p
            own[c][p[3] or "NC"] = {"pt"}
    wires, extras, edges = [], [], defaultdict(set)
    def mark(c, n, kind): own[c].setdefault(n, set()).add(kind)
    def stub(it, p, L):                   # a straight wire outward from a pin; returns its far end
        a = it.at(p[1]); d = p[2]; ca = C(a); m = "h" if d[1] == 0 else "v"
        steps = int(round(L / g)); cells = [(ca[0] + d[0] * s, ca[1] + d[1] * s) for s in range(steps + 1)]
        for c in cells[1:]:
            if c in blocked or any(nn != p[3] for nn in own.get(c, {})): print("  stub clash:", it.r, p[0], p[3], "at", c)
        for c0, c1 in zip(cells, cells[1:]): edges[p[3]].add(frozenset((c0, c1))); mark(c1, p[3], m)
        mark(cells[-1], p[3], "pt")          # its end (a symbol / label sits there): nothing may cross it
        return P_(cells[-1]), cells[-1]
    def free_line(c, d, steps, n, side=0):  # the cells out from a pin (and `side` cells either side of them) are free
        return all((c[0] + d[0] * s + d[1] * w, c[1] + d[1] * s + d[0] * w) not in blocked and
                   all(nn == n for nn in own.get((c[0] + d[0] * s + d[1] * w, c[1] + d[1] * s + d[0] * w), {}))
                   for s in range(1, steps + 1) for w in range(-side, side + 1))
    # power symbols and labels first (they take their room); the rest gets routed
    nets = defaultdict(list); side_pwr = {}; pwr_end = {}
    for it in placed:
        for p in it.pins:
            n = p[3]
            if n is None: extras.append(("nc", it.at(p[1]))); continue
            if n in flagged and n not in flag_done:
                flag_done.add(n); extras.append(("flag", it.at(p[1])))
            if n in POWER:                # its symbol and its name take their room (sideways: every other one further out)
                d = p[2]; c0 = C(it.at(p[1])); L = G
                nb = next((pe for k_ in (-2, 2) for pe in [pwr_end.get((id(it), n, d, (c0[0] + d[1] * k_, c0[1] + d[0] * k_)))] if pe), None)
                if nb:                    # the next pin is on the same rail: join the two stubs, one symbol for both
                    e, ce = stub(it, p, G); lat = (nb[0] - ce[0], nb[1] - ce[1]); st = (lat[0] // 2 or 0, lat[1] // 2 or 0)
                    edges[n].add(frozenset((ce, (ce[0] + st[0], ce[1] + st[1])))); edges[n].add(frozenset(((ce[0] + st[0], ce[1] + st[1]), nb)))
                    mark((ce[0] + st[0], ce[1] + st[1]), n, "h" if st[1] == 0 else "v"); continue
                if d[1] == 0 and any(side_pwr.get((c0[0], c0[1] + k)) == G for k in (-2, 2)): L = 3 * G
                if d[1] == 0: side_pwr[c0] = L
                e, ce = stub(it, p, L); extras.append(("pwr", n, e, d))
                if L == G: pwr_end[(id(it), n, d, c0)] = ce
                tw = int(TW(n) / g) + 2
                if d[1] == 0: area = [(s, w) for s in range(1, tw + 4) for w in (-1, 0, 1)]
                else: area = [(s, w) for s in range(1, 5) for w in range(-(tw // 2) - 1, tw // 2 + 2)]
                for s_, w in area: blocked.add((ce[0] + d[0] * s_ + d[1] * w, ce[1] + d[1] * s_ + d[0] * w))
            else: nets[n].append((it, p))
    labelled = set()
    def label_at(it, p, n):
        e, ce = stub(it, p, G); d = p[2]
        extras.append(("label", n, e, d, True))
        w = int(TW(n) / g) + 3
        for s in range(1, w + 1):
            for dd in (-1, 0, 1): blocked.add((ce[0] + d[0] * s + (d[1] != 0) * dd, ce[1] + d[1] * s + (d[0] != 0) * dd))
    for n, ps in nets.items():            # a net that leaves the block: its name once, on the pin with the most room
        if len(net_blocks[n]) > 1 or len(ps) == 1:
            it, p = max(ps, key=lambda q: (free_line(C(q[0].at(q[1][1])), q[1][2], int(TW(n) / g) + 5, n), q[0].r in BLOCKS[k][2].split()))
            label_at(it, p, n); labelled.add(n)
    def astar(n, src, d0, targets, tpin):
        # targets: cells of the net already drawn; tpin: target pin cells -> the direction a wire must arrive from
        H = lambda c: min(abs(c[0] - t[0]) + abs(c[1] - t[1]) for t in tlist)
        tlist = list(targets)[:200]
        start = (src, d0); dist = {start: 0}; prev = {}
        pq = [(H(src), 0, src, d0)]
        lim = 40000
        while pq and lim:
            lim -= 1
            f, cost, c, d = heapq.heappop(pq)
            if cost > dist.get((c, d), 1e9): continue
            for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if nd == (-d[0], -d[1]): continue
                if c != src and any(nn != n and own[c][nn] - {"pt"} for nn in own.get(c, {})) and nd != d: continue   # no turning on a crossing
                if c == src and nd != d0: continue
                nc = (c[0] + nd[0], c[1] + nd[1]); m = "h" if nd[1] == 0 else "v"
                if nc in blocked: continue
                oth = {nn: kk for nn, kk in own.get(nc, {}).items() if nn != n}
                if any("pt" in kk or m in kk for kk in oth.values()): continue
                step = 1 + (4 if nd != d else 0) + (3 if oth else 0)
                ncost = cost + step
                if nc in targets and not oth:
                    if nc in tpin and tpin[nc] != (-nd[0], -nd[1]): continue
                    if nc not in tpin and m in own[nc].get(n, set()) and nc not in tpin: pass
                    prev[(nc, nd)] = (c, d); path = [(nc, nd)]
                    while path[-1] in prev: path.append(prev[path[-1]])
                    return path[::-1]
                if ncost < dist.get((nc, nd), 1e9):
                    dist[(nc, nd)] = ncost; prev[(nc, nd)] = (c, d)
                    heapq.heappush(pq, (ncost + H(nc), ncost, nc, nd))
        return None
    failed = []
    def route_net(n, ps, loose):
        if len(ps) < 2 and n in labelled: return
        tree = set(); tpin = {}
        for c, nets_ in own.items():
            if n in nets_ and nets_[n] - {"pt"}: tree.add(c)
        todo = []
        for it, p in ps:
            c = C(it.at(p[1]))
            if c in tree or any(frozenset((c, (c[0] + p[2][0], c[1] + p[2][1]))) in edges[n] for _ in [0]): tree.add(c)
            else: todo.append((it, p, c))
        if not tree:
            it, p, c = todo.pop(0); tree.add(c); tpin[c] = p[2]
        for it, p, c in sorted(todo, key=lambda x: min(abs(x[2][0] - t[0]) + abs(x[2][1] - t[1]) for t in tree)):
            for t in list(tree):
                if t in pend and t not in tpin: tpin[t] = pend[t][2]
            path = None if it.r in BIG or any(t_.r in BIG for t_, _ in ps) else astar(n, c, p[2], tree, tpin)
            if path:
                bends = sum(1 for (_, a_), (_, b_) in zip(path[1:], path[2:]) if a_ != b_)
                far = min(abs(c[0] - t[0]) + abs(c[1] - t[1]) for t in tree)
                if bends > (6 if loose else 3) or len(path) > (2.5 if loose else 1.6) * far + 16: path = None   # spaghetti: name it instead
            if path is None: failed.append((it, p, n, ps[0])); continue
            for (c0, d0_), (c1, d1) in zip(path, path[1:]):
                edges[n].add(frozenset((c0, c1))); m = "h" if d1[1] == 0 else "v"
                mark(c0, n, m); mark(c1, n, m); tree.add(c0); tree.add(c1)
    for n, ps in sorted(nets.items(), key=lambda kv: len(kv[1])): route_net(n, ps, False)
    retry = sorted({f[2] for f in failed}); failed.clear()
    for n in retry: route_net(n, nets[n], True)
    def name_pin(it, p, n, glob):
        glob = True
        c = C(it.at(p[1]))
        if free_line(c, p[2], int(TW(n) / g) + 4, n, 1) and not any(frozenset((c, (c[0] + p[2][0], c[1] + p[2][1]))) in edges[n] for _ in [0]):
            e, ce = stub(it, p, G); extras.append(("label", n, e, p[2], glob))
        else: extras.append(("label", n, it.at(p[1]), p[2], glob))
    for it, p, n, (it0, p0) in failed:    # not wired: its name on the pin (and on the net's first pin)
        glob = len(net_blocks[n]) > 1
        name_pin(it, p, n, glob)
        if n not in labelled: labelled.add(n); name_pin(it0, p0, n, glob)
    return edges, extras, own, pend

# ---- a page: its blocks framed and packed; wires from each net's cell edges -----------------------------------------
pwr_n = [0]; flag_done = set(); OVER = []

# ---- overlap check: every text, label, power symbol, part body and wire as a box; anything overlapping is reported --
def boxes_of(items):
    out = []
    def txt(t, x, y, ang, size, just, tag):
        w, h = TW(t, size), size * 1.05
        hj = "left" if "left" in just else "right" if "right" in just else "center"
        vj = "bottom" if "bottom" in just else "top" if "top" in just else "center"
        a0 = {"left": 0, "right": -w, "center": -w / 2}[hj]; b0 = {"bottom": -h, "top": 0, "center": -h / 2}[vj]
        if ang in (90, 270):              # reads upwards: its length runs along -y
            out.append(((x + b0, y - a0 - w, x + b0 + h, y - a0), tag))
        else: out.append(((x + a0, y + b0, x + a0 + w, y + b0 + h), tag))
    for e in items:
        k = e[0]
        if k == "text":
            at = kid(e, "at"); ef = kid(e, "effects"); sz = float(kid(kid(ef, "font"), "size")[1]); j = kid(ef, "justify") or []
            txt(e[1], float(at[1]), float(at[2]), float(at[3]), sz, " ".join(j[1:]), ("text", e[1]))
        elif k in ("label", "global_label"):
            at = kid(e, "at"); x, y, ang = float(at[1]), float(at[2]), int(float(at[3])); w = TW(e[1]) + (3 if k == "global_label" else 0)
            hh = 1.2 if k == "global_label" else 0.0
            d = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}[ang]
            if k == "label":              # text sits above / left of its wire
                bx = (x, y - 1.4, x + d[0] * w, y - 0.15) if d[1] == 0 else (x - 1.4, y, x - 0.15, y + d[1] * w)
            else:
                bx = (x, y - hh, x + d[0] * w, y + hh) if d[1] == 0 else (x - hh, y, x + hh, y + d[1] * w)
            bx = (min(bx[0], bx[2]), min(bx[1], bx[3]), max(bx[0], bx[2]), max(bx[1], bx[3]))
            if d[1] == 0: bx = (bx[0] + 0.3 * (d[0] > 0), bx[1], bx[2] - 0.3 * (d[0] < 0), bx[3])
            else: bx = (bx[0], bx[1] + 0.3 * (d[1] > 0), bx[2], bx[3] - 0.3 * (d[1] < 0))
            out.append((bx, (k, e[1])))
        elif k == "symbol":
            lid = kid(e, "lib_id")[1]; at = kid(e, "at"); x, y, rot = float(at[1]), float(at[2]), int(float(at[3]))
            props = {q[1]: q for q in kids(e, "property")}
            if lid.startswith("power:"):
                if lid == "power:PWR_FLAG": continue
                v = props["Value"]; vat = kid(v, "at")
                dirn = {"power:GND": {0: (0, 1), 180: (0, -1), 90: (1, 0), 270: (-1, 0)},
                        "power:VCC": {0: (0, -1), 180: (0, 1), 90: (-1, 0), 270: (1, 0)}}[lid][rot]
                ex, ey = x + dirn[0] * 2.4, y + dirn[1] * 2.4
                bx = (min(x, ex) - (1.15 if dirn[0] == 0 else 0), min(y, ey) - (1.15 if dirn[1] == 0 else 0),
                      max(x, ex) + (1.15 if dirn[0] == 0 else 0), max(y, ey) + (1.15 if dirn[1] == 0 else 0))
                bx = (bx[0] + 0.25 * (dirn[0] > 0), bx[1] + 0.25 * (dirn[1] > 0), bx[2] - 0.25 * (dirn[0] < 0), bx[3] - 0.25 * (dirn[1] < 0))
                out.append((bx, ("power", v[2])))
            else:
                r = props["Reference"][2]; u = int(kid(e, "unit")[1]); _, sy = sym_of(r); pins, draw = units(sy)
                pts = [rotxy(px, py, rot) for px, py in draw[u] + draw[0]] + [rotxy(q[2], q[3], rot) for q in pins[u] + pins[0]]
                b = (x + min(p[0] for p in pts) + 0.2, y + min(p[1] for p in pts) + 0.2, x + max(p[0] for p in pts) - 0.2, y + max(p[1] for p in pts) - 0.2)
                out.append((b, ("part", r)))
        elif k == "wire":
            a, b = kids(kid(e, "pts"), "xy")[:2]; x0, y0, x1, y1 = float(a[1]), float(a[2]), float(b[1]), float(b[2])
            out.append(((min(x0, x1) + (0.3 if y0 == y1 else 0), min(y0, y1) + (0.3 if x0 == x1 else 0),
                         max(x0, x1) - (0.3 if y0 == y1 else 0), max(y0, y1) - (0.3 if x0 == x1 else 0)), ("wire", "")))
    return out
def overlaps(items):
    bs = boxes_of(items); bad = []
    for i in range(len(bs)):
        (a, ta) = bs[i]
        for j in range(i + 1, len(bs)):
            (b, tb) = bs[j]
            if ta[0] == "wire" and tb[0] == "wire": continue
            if ta[0] == "part" and tb[0] == "part" and ta[1] == tb[1]: continue
            if a[0] < b[2] - 0.05 and b[0] < a[2] - 0.05 and a[1] < b[3] - 0.05 and b[1] < a[3] - 0.05: bad.append((ta, tb))
    return bad

def sheet(pg, root_uuid, sheet_uuid):
    items, used_libs = [], {}
    path = ["path", Q(f"/{root_uuid}/{sheet_uuid}")]
    blocks = []
    for k, (p, title, anchors) in enumerate(BLOCKS):
        if p != pg: continue
        refs = sorted((r for r in comps if blk_of[r] == k),
                      key=lambda r: (anchors.split().index(order[r]) if order[r] in anchors.split() else 99, r != order[r], r))
        placed = place_block(k, refs)
        edges, extras, own, pend = route_block(k, placed)
        bb = None
        for it in placed: bb = it.box(keepbox(it, k)) if bb is None else grow(bb, *(lambda b: [(b[0], b[1]), (b[2], b[3])])(it.box(keepbox(it, k))))
        for n, es in edges.items():
            for e in es:
                for c in e: bb = grow(bb, (c[0] * g, c[1] * g))
        bb = (bb[0] - 4, bb[1] - 9, max(bb[2] + 4, bb[0] - 4 + TW(title, 2.0) + 6), bb[3] + 4)   # wide enough for its title
        blocks.append((k, title, placed, edges, extras, pend, bb))
    blocks.sort(key=lambda b: -(b[6][3] - b[6][1]))
    best = None                           # rows of blocks, as wide as makes the page nearest landscape A-paper shape
    for PW in range(260, 900, 10):
        x, y, rowh, pos, wmax = 12.0, 14.0, 0.0, [], 0.0
        for b in blocks:
            w, h = b[6][2] - b[6][0], b[6][3] - b[6][1]
            if x + w > PW - 12 and x > 12: x, y, rowh = 12.0, y + rowh + 4, 0.0
            pos.append((snap(x - b[6][0]), snap(y - b[6][1]))); x += w + 4; rowh = max(rowh, h); wmax = max(wmax, x)
        W_, H_ = max(wmax + 8, 297), y + rowh + 40       # + the title block's strip
        W_, H_ = max(W_, H_ * 1.414), max(H_, W_ / 1.414)
        if best is None or W_ * H_ < best[0]: best = (W_ * H_, round(W_), round(H_), pos)
    _, PW, PH, pos = best; paper = None
    def psym(lid, ref, val, at, rot, vat, vjust=None):
        return ["symbol", ["lib_id", Q(lid)], ["at", *at, rot], ["unit", 1], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
                ["dnp", "no"], ["uuid", U()], ["property", Q("Reference"), Q(ref), ["at", *at, 0], FONT + [["hide", "yes"]]],
                ["property", Q("Value"), Q(val), ["at", *at, 0], FONT + [["hide", "yes"]]],
                ["pin", Q("1"), ["uuid", U()]], ["instances", ["project", Q(PROJ), path + [["reference", Q(ref)], ["unit", 1]]]]]
    def ptext(val, vat, just):            # a power symbol's name as plain text (a rotated symbol's own field lands oddly)
        return ["text", Q(val), ["exclude_from_sim", "no"], ["at", *vat, 0],
                ["effects", ["font", ["size", 1.27, 1.27]], ["justify", *just.split()]], ["uuid", U()]]
    for (k, title, placed, edges, extras, pend, bb), (OX, OY) in zip(blocks, pos):
        A = lambda p: (round((OX + p[0]) / g) * g, round((OY + p[1]) / g) * g)
        items.append(["rectangle", ["start", OX + bb[0], OY + bb[1]], ["end", OX + bb[2], OY + bb[3]],
                      ["stroke", ["width", 0.2], ["type", "dash"]], ["fill", ["type", "none"]], ["uuid", U()]])
        items.append(["text", Q(title), ["exclude_from_sim", "no"], ["at", OX + bb[0] + 1.5, OY + bb[1] + 4, 0],
                      ["effects", ["font", ["size", 2.0, 2.0], ["bold", "yes"]], ["justify", "left", "bottom"]], ["uuid", U()]])
        for it in placed:
            c = comps[it.r]; used_libs[it.lid] = sym_of(it.r)[1]; X, Y = A((it.X, it.Y))
            sym = ["symbol", ["lib_id", Q(it.lid)], ["at", X, Y, it.rot], ["unit", it.u], ["exclude_from_sim", "no"], ["in_bom", "yes"],
                   ["on_board", "yes"], ["dnp", "no"], ["uuid", U()]]
            for kk, v in (("Reference", it.r), ("Value", c["value"]), ("Footprint", c["fp"]), ("LCSC", c["lcsc"])):
                if v or kk != "LCSC": sym.append(["property", Q(kk), Q(v), ["at", X, Y, 0], FONT + [["hide", "yes"]]])
            sym += [["pin", Q(num), ["uuid", U()]] for p in it.pins for num in p[4]]
            sym.append(["instances", ["project", Q(PROJ), path + [["reference", Q(it.r)], ["unit", it.u]]]])
            items.append(sym)
            for t, x, y, jst in it.texts:   # name / value as plain text (no field-rotation surprises)
                items.append(["text", Q(t), ["exclude_from_sim", "no"], ["at", X + x, Y + y, 0],
                              ["effects", ["font", ["size", 1.27, 1.27]], ["justify", *[w for w in jst.split() if w != "center"]]], ["uuid", U()]])
        # wires: maximal straight runs of each net's cell edges, broken where three or more meet (a dot there)
        for n, es in edges.items():
            adj = defaultdict(set)
            for e in es:
                a, b = tuple(e); adj[a].add(b); adj[b].add(a)
            deg = {c: len(v) + (1 if c in pend else 0) for c, v in adj.items()}
            done = set()
            for e in es:
                if e in done: continue
                a, b = tuple(e); d = (b[0] - a[0], b[1] - a[1])
                run = [a, b]; done.add(e)
                for end, dd in ((0, (-d[0], -d[1])), (1, d)):
                    while True:
                        c = run[0] if end == 0 else run[-1]; nx = (c[0] + dd[0], c[1] + dd[1]); ee = frozenset((c, nx))
                        if ee not in es or ee in done or deg.get(c, 0) > 2: break
                        done.add(ee)
                        if end == 0: run.insert(0, nx)
                        else: run.append(nx)
                p0, p1 = A((run[0][0] * g, run[0][1] * g)), A((run[-1][0] * g, run[-1][1] * g))
                items.append(["wire", ["pts", ["xy", *p0], ["xy", *p1]], ["stroke", ["width", 0], ["type", "default"]], ["uuid", U()]])
            for c, dg in deg.items():
                if dg >= 3: items.append(["junction", ["at", *A((c[0] * g, c[1] * g))], ["diameter", 0], ["color", 0, 0, 0, 0], ["uuid", U()]])
        for e in extras:
            if e[0] == "nc": items.append(["no_connect", ["at", *A(e[1])], ["uuid", U()]])
            elif e[0] == "flag":
                used_libs["power:PWR_FLAG"] = libsym("power", "PWR_FLAG"); pwr_n[0] += 1
                items.append(psym("power:PWR_FLAG", f"#FLG{pwr_n[0]:03d}", "PWR_FLAG", A(e[1]), 0, A(e[1])))
            elif e[0] == "pwr":
                _, n, P, d = e; pid = "power:GND" if n == "GND" else "power:VCC"
                used_libs[pid] = libsym("power", pid.split(":")[1]); pwr_n[0] += 1; x, y = A(P)
                if d[1] == 0:             # at a sideways wire's end: pointing along it
                    rot = (90 if d[0] > 0 else 270) if n == "GND" else (270 if d[0] > 0 else 90)
                    items.append(psym(pid, f"#PWR{pwr_n[0]:03d}", n, (x, y), rot, None))
                    items.append(ptext(n, (x + d[0] * 3.0, y), "left" if d[0] > 0 else "right"))
                else:
                    rot = 0 if (n == "GND") == (d == (0, 1)) else 180
                    items.append(psym(pid, f"#PWR{pwr_n[0]:03d}", n, (x, y), rot, None))
                    items.append(ptext(n, (x, y + (1 if d == (0, 1) else -1) * 3.0), "top" if d == (0, 1) else "bottom"))
            elif e[0] == "label":
                _, n, P, d, glob = e; x, y = A(P)
                ang = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}[d]
                if glob:
                    items.append(["global_label", Q(n), ["shape", "bidirectional"], ["at", x, y, ang], ["fields_autoplaced", "yes"],
                                  FONT + [["justify", "left" if ang in (0, 90) else "right"]], ["uuid", U()],
                                  ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", x, y, 0], FONT + [["hide", "yes"]]]])
                else:
                    items.append(["label", Q(n), ["at", x, y, ang], ["fields_autoplaced", "yes"],
                                  FONT + [["justify", "left" if ang in (0, 90) else "right", "bottom"]], ["uuid", U()]])
    bad = overlaps(items); OVER.append((PAGES[pg], bad))
    lib = ["lib_symbols"] + [[s[0], Q(kk)] + s[2:] for kk, s in sorted(used_libs.items())]
    return ["kicad_sch", ["version", 20250114], ["generator", Q("popm_sch")], ["generator_version", Q("9.0")], ["uuid", sheet_uuid],
            ["paper", Q("User"), PW, PH], ["title_block", ["title", Q(PAGES[pg])], ["company", Q("baunuri.com")], ["rev", Q("A")],
                                  ["comment", 1, Q("generated by pcb/sch.py from popm_board.net (popm_board.py): do not edit")]],
            lib] + items

# ---- the root sheet: one box per page --------------------------------------------------------------------------------
root_uuid = U(); root = []
for k, title in enumerate(PAGES):
    su = U(); fn = f"{k + 1:02d}_{re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')[:40]}.kicad_sch"
    open(os.path.join(OUT, fn), "w").write(dump(sheet(k, root_uuid, su)) + "\n")
    x, y = 20 + (k % 2) * 130, 40 + (k // 2) * 55
    root.append(["sheet", ["at", x, y], ["size", 110, 35], ["fields_autoplaced", "yes"], ["stroke", ["width", 0.1524], ["type", "solid"]],
                 ["fill", ["color", 0, 0, 0, 0.0]], ["uuid", su],
                 ["property", Q("Sheetname"), Q(title), ["at", x, y - 0.7, 0], FONT + [["justify", "left", "bottom"]]],
                 ["property", Q("Sheetfile"), Q(fn), ["at", x, y + 35.6, 0], FONT + [["justify", "left", "top"]]],
                 ["instances", ["project", Q(PROJ), ["path", Q(f"/{root_uuid}"), ["page", Q(str(k + 2))]]]]])
    root.append(["text", Q("\n".join(t for p, t, _ in BLOCKS if p == k)), ["exclude_from_sim", "no"], ["at", x + 2, y + 3, 0],
                 ["effects", ["font", ["size", 1.5, 1.5]], ["justify", "left", "top"]], ["uuid", U()]])
doc = ["kicad_sch", ["version", 20250114], ["generator", Q("popm_sch")], ["generator_version", Q("9.0")], ["uuid", root_uuid],
       ["paper", Q("A4")], ["title_block", ["title", Q("POPM-HAT")], ["company", Q("baunuri.com")], ["rev", Q("A")]],
       ["lib_symbols"]] + root + [["sheet_instances", ["path", Q("/"), ["page", Q("1")]]]]
top = os.path.join(OUT, PROJ + ".kicad_sch")
for f in os.listdir(OUT):
    if f.endswith(".kicad_sch"): os.remove(os.path.join(OUT, f)) if f[:2].isdigit() and not any(f.startswith(f"{k + 1:02d}_") for k in range(len(PAGES))) else None
open(top, "w").write(dump(doc) + "\n")
open(os.path.join(OUT, PROJ + ".kicad_pro"), "w").write('{"erc": {"rule_severities": {"lib_symbol_issues": "ignore"}}}\n')   # symbols are embedded

# ---- checks: the schematic's own netlist must be popm_board.net's, then ERC; then the PDF -----------------------------
xn = os.path.join(OUT, "check.net")
subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", xn, top], check=True, capture_output=True)
back = defaultdict(set)
for n in kids(kid(parse(open(xn).read()), "nets"), "net"):
    nodes = frozenset((kid(nd, "ref")[1], kid(nd, "pin")[1]) for nd in kids(n, "node") if not kid(nd, "ref")[1].startswith("#"))
    if nodes: back[nodes] = kid(n, "name")[1]
want = {frozenset(v) for k, v in netnodes.items()}
got = {k for k in back if len(k) > 1 or k in want}
miss, extra = want - got, got - want
assert not miss and not extra, (f"schematic != netlist: missing {[sorted(m) for m in miss][:5]}, extra {[ (back[e], sorted(e)) for e in extra][:5]}")
erc = os.path.join(OUT, "erc.rpt")
subprocess.run(["kicad-cli", "sch", "erc", "-o", erc, top], capture_output=True)
print(open(erc).read().strip().splitlines()[-1] if os.path.exists(erc) else "no ERC report")
pdf = os.path.join(OUT, PROJ + ".pdf")
subprocess.run(["kicad-cli", "sch", "export", "pdf", "-o", pdf, top], check=True, capture_output=True)
from collections import Counter
for pgname, bad in OVER:
    print(f"  overlaps on '{pgname}': {len(bad)}", dict(Counter(tuple(sorted((a[0], b[0]))) for a, b in bad)))
    if "-v" in sys.argv:
        for a, b in bad: print("     ", a, b)
print(pdf, f"{len(PAGES) + 1} sheets, {len(comps)} parts, {len(want)} nets: matches popm_board.net")
