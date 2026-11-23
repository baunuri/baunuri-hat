# Grid A* for single links on the outer layers (vias where they fit, never in a pad). preroute.py draws the few links
# the autorouter keeps failing; route.py finishes whatever it still left unconnected. 0.05 mm grid: a 0.3 mm track gets
# out between 0.5 mm-pitch pins. Board frame: mm from the top-left corner.
import heapq, math
import numpy as np
import pcbnew

from board import X0, Y0, W, H, CORNER_R, ANT, HOLES
G = 0.05
NX, NY = int(W / G), int(H / G)
gx = (np.arange(NX) + 0.5) * G; gy = (np.arange(NY) + 0.5) * G
XX, YY = np.meshgrid(gx, gy)
LAY = (pcbnew.F_Cu, pcbnew.B_Cu, pcbnew.In2_Cu)   # the signal layers (In1 is the GND plane)
COST = (1.0, 1.0, 1.5)                     # the inner layer is the last resort (thinner copper)

# nets in layout.py's Battery / Rail classes: 0.2 mm clearance; KiCad keeps the larger of two nets' clearances between them
WIDE_NETS = {"BAT_RAW", "VBAT_FET", "VBAT", "+5V", "+5V4", "BUCK_SW", "VBUS", "PI_5V", "SPK+", "SPK-"}
def rr(w, clr, other): return w / 2 + max(clr, 0.2 if other in WIDE_NETS else 0.127)

def mmxy(p): return pcbnew.ToMM(p.x) - X0, pcbnew.ToMM(p.y) - Y0
def box_d(xx, yy, x0, y0, x1, y1):             # distance to a rectangle
    return np.hypot(np.maximum(np.maximum(x0 - xx, xx - x1), 0), np.maximum(np.maximum(y0 - yy, yy - y1), 0))

def blocked(b, net, w, clr, win=None):
    """[F, B] grids of the cells a track of width w can't have its centre on (other nets' copper, holes, the edge)."""
    r = w / 2 + clr
    blk = [np.zeros((NY, NX), bool) for _ in LAY]
    wx0, wy0, wx1, wy1 = win or (0, 0, W, H)  # only shapes near the window matter (the rest is blocked anyway)
    def mark(Ls, x0, y0, x1, y1, hit):
        if x1 + 3 < wx0 or x0 - 3 > wx1 or y1 + 3 < wy0 or y0 - 3 > wy1: return
        i0, i1 = max(int((x0 - 3) / G), 0), min(int((x1 + 3) / G) + 1, NX)
        j0, j1 = max(int((y0 - 3) / G), 0), min(int((y1 + 3) / G) + 1, NY)
        if i0 < i1 and j0 < j1:
            m = hit(XX[j0:j1, i0:i1], YY[j0:j1, i0:i1])
            for l in Ls: blk[l][j0:j1, i0:i1] |= m
    for f in b.GetFootprints():
        for q in f.Pads():
            if q.GetNetname() == net and q.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH: continue
            bb = q.GetBoundingBox(); (x0, y0), (x1, y1) = mmxy(bb.GetOrigin()), mmxy(bb.GetEnd())   # (keep bb: SWIG)
            Ls = [0, 1, 2] if q.GetDrillSizeX() else [l for l in (0, 1) if q.IsOnLayer(LAY[l])]
            rq = w / 2 + max(clr, 0.3) if q.GetDrillSizeX() else rr(w, clr, q.GetNetname())   # holes: hole clearance (0.25) + margin
            mark(Ls, x0, y0, x1, y1, lambda xx, yy, a=(x0, y0, x1, y1), rq=rq: box_d(xx, yy, *a) < rq)
    for t in b.GetTracks():
        if t.GetNetname() == net: continue
        if t.Type() == pcbnew.PCB_VIA_T:
            cx, cy = mmxy(t.GetPosition()); vr = pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2; rt = rr(w, clr, t.GetNetname())
            mark([0, 1, 2], cx, cy, cx, cy, lambda xx, yy, cx=cx, cy=cy, vr=vr, rt=rt: np.hypot(xx - cx, yy - cy) < rt + vr)
        elif t.GetLayer() in LAY:
            ax, ay = mmxy(t.GetStart()); bx, by = mmxy(t.GetEnd()); hw = pcbnew.ToMM(t.GetWidth()) / 2; rt = rr(w, clr, t.GetNetname())
            def seg(xx, yy, ax=ax, ay=ay, bx=bx, by=by, hw=hw, r=rt):
                dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy or 1e-9
                u = np.clip(((xx - ax) * dx + (yy - ay) * dy) / L2, 0, 1)
                return np.hypot(xx - ax - u * dx, yy - ay - u * dy) < r + hw
            mark([LAY.index(t.GetLayer())], min(ax, bx), min(ay, by), max(ax, bx), max(ay, by), seg)
    cx, cy = np.clip(XX, CORNER_R, W - CORNER_R), np.clip(YY, CORNER_R, H - CORNER_R)
    e = 0.3 + w / 2                            # board edge clearance
    out = (np.hypot(XX - cx, YY - cy) > CORNER_R - e) | ((XX < ANT[2] + w / 2 + 0.2) & (YY > ANT[1] - w / 2 - 0.2) & (YY < ANT[3] + w / 2 + 0.2)) | (XX > W - e) | (YY < e) | (YY > H - e)   # + the antenna keep-out
    if win: out = out | (XX < wx0) | (XX > wx1) | (YY < wy0) | (YY > wy1)
    return [m | out for m in blk]

def via_ok(b, net, vd, clr, win=None):
    """Cells a via can sit on: clear of other nets on both layers, of every SMD pad (any net) and of the holes."""
    a = blocked(b, net, vd, clr, win); v = ~(a[0] | a[1] | a[2])   # a via goes through every layer
    for f in b.GetFootprints():
        for q in f.Pads():
            bb = q.GetBoundingBox(); (x0, y0), (x1, y1) = mmxy(bb.GetOrigin()), mmxy(bb.GetEnd())   # (keep bb: SWIG)
            if q.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and not f.GetReference().startswith("TP"):   # (a test pad isn't soldered)
                i0, i1 = max(int((x0 - vd) / G), 0), min(int((x1 + vd) / G) + 1, NX)
                j0, j1 = max(int((y0 - vd) / G), 0), min(int((y1 + vd) / G) + 1, NY)
                v[j0:j1, i0:i1] &= ~(box_d(XX[j0:j1, i0:i1], YY[j0:j1, i0:i1], x0, y0, x1, y1) < vd / 2 + 0.1)
        if f.GetReference().startswith("H"):
            hx, hy = mmxy(f.GetPosition()); v &= np.hypot(XX - hx, YY - hy) > 3.0
    for t in b.GetTracks():                    # every existing via, own net too: drill to drill (never two in one spot)
        if t.Type() == pcbnew.PCB_VIA_T:
            cx, cy = mmxy(t.GetPosition()); d0 = vd / 2 + pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2 + 0.2
            i0, i1 = max(int((cx - d0) / G), 0), min(int((cx + d0) / G) + 1, NX); j0, j1 = max(int((cy - d0) / G), 0), min(int((cy + d0) / G) + 1, NY)
            v[j0:j1, i0:i1] &= ~(np.hypot(XX[j0:j1, i0:i1] - cx, YY[j0:j1, i0:i1] - cy) < d0)
    return v

def where(b, e):                               # an endpoint's position (mm)
    if e[0] == "pad": return mmxy(next(q for q in b.FindFootprintByReference(e[1]).Pads() if q.GetNumber() == e[2]).GetPosition())
    return e[1], e[2]

def find(b, net, start, goal, w, clr=0.2, vd=0.6, layers=(0, 1, 2), margin=8.0):
    """As _find, in a window round the two ends first (fast), then on the whole board."""
    (ax, ay), (bx, by) = where(b, start), where(b, goal)
    win = (min(ax, bx) - margin, min(ay, by) - margin, max(ax, bx) + margin, max(ay, by) + margin)
    return _find(b, net, start, goal, w, clr, vd, layers, win) or _find(b, net, start, goal, w, clr, vd, layers, None)

def _find(b, net, start, goal, w, clr, vd, layers, win):
    """start / goal: ("pad", ref, number) or ("at", x, y, [layers 0 = F, 1 = B, 2 = In2]). -> [(x, y, layer), ...] or None."""
    blk = blocked(b, net, w, clr, win); vok = via_ok(b, net, vd, clr, win)
    def end(e):                                # the free cell nearest the pad's centre inside it, or nearest the point
        if e[0] == "pad":
            q = next(q for q in b.FindFootprintByReference(e[1]).Pads() if q.GetNumber() == e[2])
            Ls = [0, 1, 2] if q.GetDrillSizeX() else [l for l in (0, 1) if q.IsOnLayer(LAY[l])]
            x, y = mmxy(q.GetPosition()); bb = q.GetBoundingBox(); (x0, y0), (x1, y1) = mmxy(bb.GetOrigin()), mmxy(bb.GetEnd())   # (keep bb: SWIG)
        else:
            _, x, y, Ls = e; x0, y0, x1, y1 = x - 0.15, y - 0.15, x + 0.15, y + 0.15
        onpad = (lambda i, j: q.HitTest(pcbnew.VECTOR2I(pcbnew.FromMM(X0 + (i + 0.5) * G), pcbnew.FromMM(Y0 + (j + 0.5) * G)))) \
            if e[0] == "pad" else (lambda i, j: True)   # on the pad's copper (a round pad's box has corners off it)
        cells = [(math.hypot((i + 0.5) * G - x, (j + 0.5) * G - y), i, j) for i in range(max(int(x0 / G), 0), min(int(x1 / G) + 1, NX))
                 for j in range(max(int(y0 / G), 0), min(int(y1 / G) + 1, NY)) if any(not blk[l][j, i] for l in Ls) and onpad(i, j)]
        if not cells: return None
        _, i, j = min(cells); return i, j, [l for l in Ls if not blk[l][j, i] and l in layers]
    s, t = end(start), end(goal)
    if not s or not t: return None
    (si, sj, sL), (ti, tj, tL) = s, t
    h = lambda i, j: math.hypot(i - ti, j - tj)
    openq = [(h(si, sj), 0.0, si, sj, l, None) for l in sL]; seen = {}
    while openq:
        _, g_, i, j, l, par = heapq.heappop(openq)
        if (i, j, l) in seen: continue
        seen[(i, j, l)] = par
        if (i, j) == (ti, tj) and l in tL: break
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < NX and 0 <= nj < NY and not blk[l][nj, ni] and (ni, nj, l) not in seen:   # (l is allowed)
                ng = g_ + math.hypot(di, dj) * COST[l]; heapq.heappush(openq, (ng + h(ni, nj), ng, ni, nj, l, (i, j, l)))
        if vok[j, i]:                         # a via: to any other layer (costs ~4 mm of track)
            for l2 in range(len(LAY)):
                if l2 != l and l2 in layers and not blk[l2][j, i] and (i, j, l2) not in seen:
                    heapq.heappush(openq, (g_ + 80 + h(i, j), g_ + 80, i, j, l2, (i, j, l)))
    else:
        return None
    path = []; k = (i, j, l)
    while k: path.append(k); k = seen[k]
    pts = [((pi + 0.5) * G, (pj + 0.5) * G, pl) for pi, pj, pl in reversed(path)]
    keep = [pts[0]]                            # corners and layer changes only
    for p0, p1, p2 in zip(pts, pts[1:], pts[2:]):
        if p1[2] != p0[2] or p2[2] != p1[2] or abs((p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])) > 1e-9:
            keep.append(p1)
    return keep + [pts[-1]]

def draw(b, net, pts, w, vd=0.6, vdr=0.3, locked=True):
    V = lambda x, y: pcbnew.VECTOR2I(pcbnew.FromMM(X0 + x), pcbnew.FromMM(Y0 + y)); n = b.FindNet(net); vias = 0
    for p0, p1 in zip(pts, pts[1:]):
        if p0[2] != p1[2]:
            v = pcbnew.PCB_VIA(b); v.SetPosition(V(p1[0], p1[1])); v.SetWidth(pcbnew.FromMM(vd)); v.SetDrill(pcbnew.FromMM(vdr))
            v.SetNet(n); v.SetLocked(locked); b.Add(v); vias += 1
        elif (p0[0], p0[1]) != (p1[0], p1[1]):
            t = pcbnew.PCB_TRACK(b); t.SetStart(V(*p0[:2])); t.SetEnd(V(*p1[:2])); t.SetWidth(pcbnew.FromMM(w))
            t.SetLayer(LAY[p0[2]]); t.SetNet(n); t.SetLocked(locked); b.Add(t)
    return vias
