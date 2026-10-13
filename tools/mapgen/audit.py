#!/usr/bin/env python3
"""Audit of a road set for DRAWING and ROUTING: finds the kinds of errors seen in the road network of a big city map and counts them, per kind and per
2 km square, so that a sweep of the whole map says where to look.

  python audit.py <the road file> [--csv saida.csv]

Kinds (and how each is found):
  tiny        a piece shorter than 3.5 m (with a road's width and rounded ends it draws a blob; it is a bridge of two lanes or a stub)
  duplicate   a piece that lies on another one (80% of its length within 1.5 m of another piece, running the same way): the same road twice
  split       two pieces that meet end to end alone, same street/class/width and a straight continuation: one road in two pieces
  wide        a piece 10 m or wider with another road running along it within 14 m on one side or both (a centre line left in a median)
  spike       a piece that turns back on itself (a turn of more than 150 degrees between two of its segments)
  group       a connected group of 6 pieces or fewer that does not touch the big network (the route functions cannot reach it)
  loose-near  a loose end within 6 m of another road's line (a join that was not made)
  gap         two loose ends facing each other within 45 m, same street (a break in a road)
  crossing    two pieces whose lines cross in the middle of both, at the same height (within 2 m), with no vertex near: a crossing that is not a junction
  loose       any other loose end (a dead end, the end of the modelled map: reported, not an error)
"""
import collections
import csv
import json
import math
import sys

import numpy as np
from scipy.spatial import cKDTree

ROAD = ("via", "rodovia", "brt")
TOL = 2.5


def dense(pts, step):
    out = []
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) / step))
        out += [(ax + (bx - ax) * j / n, ay + (by - ay) * j / n) for j in range(n)]
    if pts:
        out.append(pts[-1])
    return out


def length(p):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:]))


def heading(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def angdiff(a, b):
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def audit(d):
    vias = [v for v in d["vias"] if v["c"] in ROAD]
    pcs = []
    for v in vias:
        p = v["p"]
        pcs.append(list(zip(p[0::2], p[1::2])))
    n = len(pcs)
    found = collections.defaultdict(list)            # kind -> [(piece or None, (x, y))]
    pts, own = [], []
    for k, p in enumerate(pcs):
        for q in dense(p, 1.5):
            pts.append(q)
            own.append(k)
    arr = np.array(pts)
    own = np.array(own)
    tree = cKDTree(arr)

    for k, p in enumerate(pcs):
        if length(p) < 3.5:
            found["tiny"].append((k, p[0]))
        # spike
        for i in range(1, len(p) - 1):
            a, b, c = p[i - 1], p[i], p[i + 1]
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.5 and math.hypot(c[0] - b[0], c[1] - b[1]) > 0.5 and angdiff(heading(a, b), heading(b, c)) > math.radians(150):
                found["spike"].append((k, b))
                break

    # duplicate: another piece under most of this one, same direction
    for k, p in enumerate(pcs):
        dn = dense(p, 3.0)
        if len(dn) < 3:
            continue
        counts = collections.Counter()
        for q in dn:
            for j in tree.query_ball_point(q, 1.5):
                if own[j] != k:
                    counts[int(own[j])] += 1
        if counts:
            o, c = counts.most_common(1)[0]
            if c / len(dn) >= 0.8 and length(pcs[o]) >= length(p) and (o < k or length(pcs[o]) > length(p)):
                found["duplicate"].append((k, p[len(p) // 2]))

    # wide: 10 m or more with another road within 14 m alongside (not under)
    for k, p in enumerate(pcs):
        if (vias[k].get("w") or 0) < 10.0:
            continue
        dn = dense(p, 6.0)
        close = 0
        for q in dn:
            near = {int(own[j]) for j in tree.query_ball_point(q, 14.0)} - {k}
            if near:
                close += 1
        if dn and close / len(dn) > 0.6:
            found["wide"].append((k, dn[len(dn) // 2]))

    # loose ends, groups
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    loose = []
    for k, p in enumerate(pcs):
        for e in (p[0], p[-1]):
            touched = False
            for j in tree.query_ball_point(e, TOL):
                if own[j] != k:
                    touched = True
                    parent[find(k)] = find(int(own[j]))
            if not touched:
                loose.append((k, e))
    size = collections.Counter(find(k) for k in range(n))
    big = max(size, key=size.get)
    for k in range(n):
        if find(k) != big and size[find(k)] <= 6:
            found["group"].append((k, pcs[k][len(pcs[k]) // 2]))
    # loose-near and gap
    ends = np.array([e for _, e in loose]) if loose else np.zeros((0, 2))
    et = cKDTree(ends) if len(ends) else None
    gap_used = set()
    for i, (k, e) in enumerate(loose):
        near = [j for j in tree.query_ball_point(e, 6.0) if own[j] != k]
        if near:
            found["loose-near"].append((k, e))
            continue
        p = pcs[k]
        a, b = (p[0], p[1]) if math.hypot(p[0][0] - e[0], p[0][1] - e[1]) < 1e-6 else (p[-1], p[-2])
        h = heading(b, a)
        hit = False
        if et is not None and i not in gap_used:
            for j in et.query_ball_point(e, 45.0):
                if j == i or j in gap_used or loose[j][0] == k:
                    continue
                m, f = loose[j]
                ang = heading(e, f)
                q = pcs[m]
                a2, b2 = (q[0], q[1]) if math.hypot(q[0][0] - f[0], q[0][1] - f[1]) < 1e-6 else (q[-1], q[-2])
                if angdiff(h, ang) < math.radians(40) and angdiff(heading(b2, a2), ang + math.pi) < math.radians(40) \
                        and (vias[k].get("n") or 0) == (vias[m].get("n") or 0) and (vias[k].get("n") or 0):
                    gap_used.update((i, j))
                    found["gap"].append((k, e))
                    hit = True
                    break
        if not hit:
            found["loose"].append((k, e))

    # split: end to end, alone at the joint
    ends_at = collections.defaultdict(list)
    for k, p in enumerate(pcs):
        ends_at[(round(p[0][0]), round(p[0][1]))].append((k, 0))
        ends_at[(round(p[-1][0]), round(p[-1][1]))].append((k, 1))
    for key, lst in ends_at.items():
        if len(lst) != 2 or lst[0][0] == lst[1][0]:
            continue
        (a, ea), (b, eb) = lst
        va, vb = vias[a], vias[b]
        if (va.get("n") or 0) != (vb.get("n") or 0) or va["c"] != vb["c"] or abs((va.get("w") or 0) - (vb.get("w") or 0)) > 1.0:
            continue
        pa = pcs[a] if ea == 1 else pcs[a][::-1]
        pb = pcs[b] if eb == 0 else pcs[b][::-1]
        if len(pa) < 2 or len(pb) < 2:
            continue
        if angdiff(heading(pa[-2], pa[-1]), heading(pb[0], pb[1])) <= math.radians(25):
            found["split"].append((a, pa[-1]))

    # crossing without a node, same height
    seg = []
    for k, p in enumerate(pcs):
        z = vias[k].get("z", 0.0)
        for i in range(len(p) - 1):
            seg.append((k, p[i], p[i + 1], z))
    mid = np.array([((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for _, a, b, _ in seg])
    st = cKDTree(mid)
    crossings = 0
    seen = set()
    for i, (k, a, b, z) in enumerate(seg):
        for j in st.query_ball_point(mid[i], math.hypot(b[0] - a[0], b[1] - a[1]) / 2 + 20.0):
            if j <= i:
                continue
            m, c, dd, z2 = seg[j]
            if m == k or abs(z - z2) > 2.0 or (min(k, m), max(k, m)) in seen:
                continue
            x = _inter(a, b, c, dd)
            if not x:
                continue
            # a vertex of either piece within 2.5 m of the crossing means it is a node
            if min(math.hypot(x[0] - q[0], x[1] - q[1]) for q in (a, b, c, dd)) < 2.5:
                continue
            if min(math.hypot(x[0] - q[0], x[1] - q[1]) for q in pcs[k] + pcs[m]) < 2.5:
                continue
            seen.add((min(k, m), max(k, m)))
            found["crossing"].append((k, x))
    return found, pcs, len(vias), len(loose), size


def _inter(a, b, c, d):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-9:
        return None
    t = ((c[0] - a[0]) * s[1] - (c[1] - a[1]) * s[0]) / den
    u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den
    if 0.02 < t < 0.98 and 0.02 < u < 0.98:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def main():
    path = sys.argv[1]
    d = json.load(open(path, encoding="utf-8"))
    found, pcs, n, nloose, size = audit(d)
    ox, oy = (d.get("meta") or {}).get("origem_mundo", (0, 0))
    print(f"{path}: {n} road pieces, {len(size)} connected groups")
    order = ["tiny", "duplicate", "split", "wide", "spike", "group", "loose-near", "gap", "crossing", "loose"]
    for kind in order:
        print(f"  {kind:11s} {len(found[kind]):6d}")
    if "--csv" in sys.argv:
        out = sys.argv[sys.argv.index("--csv") + 1]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["kind", "piece", "x_author", "y_author", "square_2km"])
            for kind in order:
                for k, (x, y) in found[kind]:
                    w.writerow([kind, k, round(x + ox), round(y + oy), f"{int((x + ox) // 2000)}_{int((y + oy) // 2000)}"])
        print("written", out)
    return found


if __name__ == "__main__":
    main()
