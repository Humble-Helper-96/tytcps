# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden test: the engine writes each field exactly as the stock CPS does.

CORPUS/variants/ holds .rdt files saved by the CPS v2.41, each with one field
changed from CORPUS/stock.rdt (made by cps-variants.ahk next to this file; the
log is variants/variants.tsv). For each one:
  1. print the CPS's image with the engine -> conf (stock conf + that change);
  2. apply that conf to the stock image with the engine (offline -c -o);
  3. the result must equal the CPS's image byte for byte, outside the
     programmed-date stamp 0x2001-0x200B.
Every file is tested, including the plain re-save S0_stock_resaved, which
must come out as stock.

Usage: python3 -I golden.py ENGINE CORPUS
"""
import os, subprocess, sys, tempfile

E = sys.argv[1]
RDT = sys.argv[2]
V68 = os.path.join(RDT, "variants")
env = dict(os.environ, TYT_STATE_DIR="/nonexistent")
NOT_EXPOSED = ()


def to_img(path):
    b = open(path, "rb").read()
    assert len(b) == 0xD0235, (path, len(b))
    return b[0x225:0x40225] + b[0x40235:]


work = tempfile.mkdtemp(prefix="golden-")
stock_img = os.path.join(work, "stock.img")
open(stock_img, "wb").write(to_img(os.path.join(RDT, "stock.rdt")))

ok = fail = skipped = 0
for fn in sorted(os.listdir(V68)):
    if not fn.endswith(".rdt"):
        continue
    name = fn[:-4]
    if NOT_EXPOSED and name.startswith(NOT_EXPOSED):
        skipped += 1
        continue
    cps = to_img(os.path.join(V68, fn))
    vimg = os.path.join(work, name + ".img")
    open(vimg, "wb").write(cps)
    conf = os.path.join(work, name + ".conf")
    with open(conf, "wb") as f:
        r = subprocess.run([E, vimg], stdout=f, stderr=subprocess.DEVNULL, env=env)
    out = os.path.join(work, name)
    os.makedirs(out, exist_ok=True)
    r = subprocess.run([E, "-c", "-o", out, stock_img, conf], capture_output=True, env=env)
    if r.returncode:
        fail += 1
        tail = r.stderr.decode("utf-8", "replace").strip().splitlines()[-2:]
        print("FAIL %-24s engine refused: %s" % (name, " / ".join(tail)))
        continue
    mine = open(os.path.join(out, "device.img"), "rb").read()
    diff = [i for i in range(len(mine)) if mine[i] != cps[i] and not (0x2001 <= i <= 0x200B)]
    if diff:
        fail += 1
        print("FAIL %-24s %d bytes differ from the CPS: %s" % (name, len(diff), ", ".join(
            "0x%05X cps %02X engine %02X" % (i, cps[i], mine[i]) for i in diff[:6])))
    else:
        ok += 1
print("golden: %d same as the CPS, %d different, %d skipped (pages not in the engine)" % (ok, fail, skipped))
sys.exit(1 if fail else 0)
