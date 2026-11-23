# Readable PDF of the board (phone-sized pages): block diagram, every chip / connector with what each pin goes to, and the
# parts list, all from popm_board.net. Run popm_board.py first.   python3 make_pdf.py  -> popm_board.pdf
import html, re, subprocess, sys, os
from collections import defaultdict

here = os.path.dirname(os.path.abspath(__file__))
net = open(os.path.join(here, "popm_board.net")).read()
readme = open(os.path.join(here, "README.md")).read()

comps = {}
for body in re.split(r"\(comp\s*\(ref ", net)[1:]:
    ref = re.match(r'"([^"]+)"', body).group(1)
    g = lambda k: (re.search(r"\(" + k + r' "([^"]*)"', body) or [None, ""])[1]
    lcsc = re.search(r'\(name "LCSC"\)\s*"([^"]*)"', body)
    comps[ref] = dict(value=g("value"), fp=g("footprint").split(":")[-1], lcsc=lcsc.group(1) if lcsc else "",
                      lib=g("part"))
pins = defaultdict(dict)                 # ref -> pin -> (net, pin name)
for body in re.split(r"\(net\s*\(code", net)[1:]:
    name = re.search(r'\(name "([^"]+)"\)', body).group(1)
    for ref, pin, pf in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)(?:\s*\(pinfunction "([^"]*)"\))?', body):
        pins[ref][pin] = (name, pf)
nets = defaultdict(list)
for ref, ps in pins.items():
    for p, (n, pf) in ps.items(): nets[n].append(f"{ref}.{pf or p}")

e = html.escape
key = lambda r: (re.match(r"[A-Z]+", r).group(0), int(re.search(r"\d+", r).group(0)))
nice = lambda n: "—" if n.startswith("N$") or n.startswith("NC") else n
ics = [r for r in sorted(comps, key=key) if r[0] in "UJQ" and not comps[r]["fp"].startswith("MountingHole")]

out = ['<!doctype html><meta charset=utf-8><style>@page{size:105mm 200mm;margin:6mm}body{font:9pt/1.3 sans-serif;color:#2f2340}'
       'h1{font-size:15pt;color:#2e8a75;margin:0 0 4px}h2{font-size:11pt;color:#2e8a75;margin:14px 0 4px;break-after:avoid}'
       'h3{font-size:9.5pt;margin:10px 0 2px;break-after:avoid}pre{font:4.1pt/1.3 monospace;white-space:pre;overflow:hidden;background:#f3f0fb;padding:4px;border-radius:4px}'
       'table{border-collapse:collapse;width:100%;break-inside:auto}td,th{border-bottom:1px solid #e4def5;padding:1px 3px;text-align:left;vertical-align:top}'
       'th{color:#5b4d6e;font-weight:600}.m{font-family:monospace;font-size:8pt}.s{color:#5b4d6e;font-size:8pt}.blk{break-inside:avoid}</style>',
       '<h1>Popm controller · rev A</h1><p class=s>Generated from pcb/popm_board.net (SKiDL). Pins marked — go to a local '
       'connection between two parts (see the net list).</p>']
blocks = re.search(r"## Blocks\n```\n(.*?)```", readme, re.S)
if blocks: out.append("<h2>Blocks</h2><pre>" + e(blocks.group(1)) + "</pre>")
pm = re.search(r"## Pin map.*?\n((?:\|.*\n)+)", readme)
if pm:
    rows = [r.strip("|").split("|") for r in pm.group(1).strip().split("\n") if not r.startswith("|---")]
    out.append("<h2>ESP32 pin map</h2><table>" + "".join("<tr>" + "".join(f"<td>{e(c.strip())}</td>" for c in r) + "</tr>" for r in rows) + "</table>")

out.append("<h2>Chips and connectors</h2>")
for r in ics:
    c = comps[r]
    title = c["value"] if c["value"] not in ("", c["lib"]) else c["lib"]
    rows = sorted(pins[r].items(), key=lambda x: (not x[0].isdigit(), int(x[0]) if x[0].isdigit() else 0, x[0]))
    out.append(f'<div class=blk><h3>{r} · {e(title)}</h3><p class=s>{e(c["fp"])}{" · LCSC " + c["lcsc"] if c["lcsc"] else ""}</p><table>')
    for p, (n, pf) in rows:
        others = [x for x in nets[n] if not x.startswith(r + ".")]
        if n in ("GND", "+3V3", "+5V", "VBAT"): others = []
        out.append(f'<tr><td class=m>{e(p)}</td><td>{e(pf or "")}</td><td><b>{e(nice(n))}</b></td><td class=s>{e(", ".join(others[:4]) + (" …" if len(others) > 4 else ""))}</td></tr>')
    out.append("</table></div>")

out.append("<h2>Net list</h2><table>")
for n in sorted(nets, key=lambda n: (n.startswith("N$"), n)):
    out.append(f'<tr><td><b>{e(n)}</b></td><td class=s>{e(", ".join(sorted(nets[n])))}</td></tr>')
out.append("</table>")

bom = defaultdict(list)
for r, c in comps.items(): bom[(c["value"], c["fp"], c["lcsc"])].append(r)
out.append("<h2>Parts</h2><table><tr><th>Qty</th><th>Part</th><th>Package</th><th>LCSC</th></tr>")
for (v, fp, l), refs in sorted(bom.items(), key=lambda x: key(sorted(x[1], key=key)[0])):
    out.append(f'<tr><td>{len(refs)}</td><td>{e(v)}<br><span class=s>{e(" ".join(sorted(refs, key=key)))}</span></td><td class=s>{e(fp)}</td><td class=m>{e(l)}</td></tr>')
out.append("</table>")

h = os.path.join(here, "popm_board.html")
open(h, "w").write("".join(out))
pdf = os.path.join(here, "popm_board.pdf")
subprocess.run(["google-chrome", "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", "file://" + h],
               check=True, capture_output=True)
print(pdf)
