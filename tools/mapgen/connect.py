#!/usr/bin/env python3
"""Connectivity of the road pieces of the road file (what a route function walks on) and the repair of its breaks.

  python connect.py medir  <the road file>                  connected groups and loose ends
  python connect.py unir   <the road file> <out.json>       join the ends (<= 6 m: snap; a T gets a vertex)
  python connect.py ligar  <the road file> <out.json>       a straight connector between two facing loose ends of the same street (<= 45 m, 40 degrees)
  python connect.py limpar <the road file> <out.json>       cut pieces under 3.5 m, merge straight continuations
  python connect.py grupos <the road file> <out.json>       connect each small group (<= 6 pieces) to the network (<= 30 m, 45 degrees)

A piece touches another when one of its ends lies within TOL metres of the other's line (end to end, or a T onto its side).
"""
import collections
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


def pieces_of(d):
    out = []
    for k, v in enumerate(d["vias"]):
        if v["c"] in ROAD:
            p = v["p"]
            out.append((k, list(zip(p[0::2], p[1::2]))))
    return out


def analyse(pieces, tol=TOL):
    n = len(pieces)
    pts, owner = [], []
    for k, p in enumerate(pieces):
        for q in dense(p, 1.5):
            pts.append(q)
            owner.append(k)
    tree = cKDTree(np.array(pts))
    owner = np.array(owner)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    loose = []
    for k, p in enumerate(pieces):
        for end in (p[0], p[-1]):
            touched = False
            for j in tree.query_ball_point(end, tol):
                o = int(owner[j])
                if o != k:
                    touched = True
                    parent[find(k)] = find(o)
            if not touched:
                loose.append((k, end))
    comp = collections.defaultdict(list)
    for k in range(n):
        comp[find(k)].append(k)
    sizes = sorted((len(v) for v in comp.values()), reverse=True)
    return dict(pieces=n, groups=len(comp), biggest=sizes[0], second=sizes[1] if len(sizes) > 1 else 0, small=sum(1 for s in sizes if s <= 3), loose=loose)


def medir(path):
    d = json.load(open(path, encoding="utf-8"))
    r = analyse([p for _, p in pieces_of(d)])
    print(f"{path}: {r['pieces']} road pieces, {r['groups']} connected groups (biggest {r['biggest']}, next {r['second']}), "
          f"{r['small']} groups of 3 or fewer, {len(r['loose'])} loose ends")
    return r


def unir(src, dst):
    """1. a piece of the road file that the lane roads already cover goes (the lane roads are in the file, joined by the game's own links);
    2. an end within 6 m of another piece's line is moved onto it (a T gets a vertex on the other piece), two ends within 4 m meet."""
    d = json.load(open(src, encoding="utf-8"))
    items = pieces_of(d)
    pcs = [p for _, p in items]
    # snap loose ends to the nearest line of another piece
    for rounds in range(2):
        r = analyse(pcs)
        pts, owner, seg = [], [], []
        for k, p in enumerate(pcs):
            for i, ((ax, ay), (bx, by)) in enumerate(zip(p, p[1:])):
                n = max(1, int(math.hypot(bx - ax, by - ay) / 1.0))
                for j in range(n + 1):
                    pts.append((ax + (bx - ax) * j / n, ay + (by - ay) * j / n))
                    owner.append(k)
                    seg.append(i)
        tree = cKDTree(np.array(pts))
        owner = np.array(owner)
        moved = 0
        inserts = collections.defaultdict(list)       # piece -> [(segment index, point)] to insert (T joints)
        for k, end in r["loose"]:
            dist, idx = tree.query(end, k=12, distance_upper_bound=6.0)
            best = None
            for di, ii in zip(np.atleast_1d(dist), np.atleast_1d(idx)):
                if not np.isfinite(di):
                    continue
                if owner[int(ii)] != k:
                    best = (int(ii), float(di))
                    break
            if not best:
                continue
            ii, di = best
            tgt = pts[ii]
            p = pcs[k]
            # which end?
            if math.hypot(p[0][0] - end[0], p[0][1] - end[1]) < 1e-6:
                p[0] = tgt
            else:
                p[-1] = tgt
            o = int(owner[ii])
            q = pcs[o]
            # a T onto the side of o: a vertex at the joint, unless it is at one of o's vertices already
            if min(math.hypot(tgt[0] - a, tgt[1] - b) for a, b in q) > 0.8:
                inserts[o].append((seg[ii], tgt))
            moved += 1
        for o, lst in inserts.items():
            q = pcs[o]
            for i, pt in sorted(set((i, p) for i, p in lst), key=lambda t: -t[0]):
                q.insert(i + 1, pt)
        print(f"  round {rounds + 1}: {moved} loose ends moved onto a neighbour, {sum(len(v) for v in inserts.values())} T vertices")
    for (k, _), p in zip(items, pcs):
        d["vias"][k]["p"] = [round(c, 1) for pt in p for c in pt]
    json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    r = analyse(pcs)
    print(f"after: {r['pieces']} pieces, {r['groups']} groups (biggest {r['biggest']}), {r['small']} small groups, {len(r['loose'])} loose ends")




def ligar(src, dst, reach=45.0, cone=40.0):
    """A road that stops short of the road it meets (loose ends facing each other within `reach` m, neither end turned away more than
    `cone` degrees from the other): a straight connector, with the street's name and the narrower width."""
    d = json.load(open(src, encoding="utf-8"))
    items = pieces_of(d)
    pcs = [p for _, p in items]
    r = analyse(pcs)
    loose = r["loose"]

    def heading(k, e):
        p = pcs[k]
        a, b = (p[0], p[1]) if math.hypot(p[0][0] - e[0], p[0][1] - e[1]) < 1e-6 else (p[-1], p[-2])
        return math.atan2(a[1] - b[1], a[0] - b[0])

    pts = np.array([e for _, e in loose])
    tree = cKDTree(pts)
    used, added = set(), []
    nomes = d["nomes"]
    for i, (k, e) in enumerate(loose):
        if i in used:
            continue
        best = None
        for j in tree.query_ball_point(e, reach):
            if j == i or j in used:
                continue
            m, f = loose[j]
            if m == k:
                continue
            ang = math.atan2(f[1] - e[1], f[0] - e[0])
            d1 = abs((heading(k, e) - ang + math.pi) % (2 * math.pi) - math.pi)
            d2 = abs((heading(m, f) - (ang + math.pi) + math.pi) % (2 * math.pi) - math.pi)
            if d1 > math.radians(cone) or d2 > math.radians(cone):
                continue
            va, vb = d["vias"][items[k][0]], d["vias"][items[m][0]]
            na, nb = va.get("n") or 0, vb.get("n") or 0
            if na and nb and nomes[na] != nomes[nb]:
                continue
            dist = math.hypot(f[0] - e[0], f[1] - e[1])
            if dist < 1.0:
                continue
            if best is None or dist < best[0]:
                best = (dist, j, m, f, va, vb)
        if best:
            dist, j, m, f, va, vb = best
            used.update((i, j))
            ref = va if (va.get("n") or 0) else vb
            added.append({"h": 0, "w": min(va.get("w") or 6.0, vb.get("w") or 6.0), "z": va.get("z", 0.0), "n": ref.get("n") or 0, "c": ref["c"], "o": 0,
                          "p": [round(e[0], 1), round(e[1], 1), round(f[0], 1), round(f[1], 1)]})
    d["vias"] += added
    json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    pcs2 = [p for _, p in pieces_of(d)]
    r2 = analyse(pcs2)
    print(f"{len(added)} connectors added (reach {reach:.0f} m); now {r2['pieces']} pieces, {r2['groups']} groups (biggest {r2['biggest']}), {len(r2['loose'])} loose ends")


def comprimento(p):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(p, p[1:]))


def limpar(src, dst, curto=3.5, jun=1.0, cone=25.0):
    """Cleans a road set for DRAWING: (1) a piece shorter than `curto` m goes (a bridge of two lanes, a stub: with rounded ends and the width of
    a road it draws a blob; its neighbours are joined again by `unir`); (2) two pieces that meet end to end alone at one point, with the same
    name and class, nearly the same width and a straight continuation (within `cone` degrees), become one piece."""
    d = json.load(open(src, encoding="utf-8"))
    items = pieces_of(d)
    vias = d["vias"]
    pcs = {k: p for k, p in items}
    short = [k for k, p in pcs.items() if comprimento(p) < curto]
    for k in short:
        del pcs[k]
    print(f"  {len(short)} pieces under {curto} m taken out")
    merged = 0
    while True:
        ends = collections.defaultdict(list)             # rounded point -> [(piece, 0|1)]
        for k, p in pcs.items():
            ends[(round(p[0][0] / jun), round(p[0][1] / jun))].append((k, 0))
            ends[(round(p[-1][0] / jun), round(p[-1][1] / jun))].append((k, 1))
        allv = cKDTree(np.array([q for p in pcs.values() for q in p]))
        done = set()
        count = 0
        for key, lst in ends.items():
            if len(lst) != 2 or lst[0][0] == lst[1][0]:
                continue
            (a, ea), (b, eb) = lst
            if a in done or b in done:
                continue
            va, vb = vias[a], vias[b]
            if (va.get("n") or 0) != (vb.get("n") or 0) or va["c"] != vb["c"] or abs((va.get("w") or 0) - (vb.get("w") or 0)) > 1.0:
                continue
            pa, pb = pcs[a], pcs[b]
            pa = pa if ea == 1 else pa[::-1]             # a ends at the joint
            pb = pb if eb == 0 else pb[::-1]             # b starts at the joint
            if len(pa) < 2 or len(pb) < 2:
                continue
            h1 = math.atan2(pa[-1][1] - pa[-2][1], pa[-1][0] - pa[-2][0])
            h2 = math.atan2(pb[1][1] - pb[0][1], pb[1][0] - pb[0][0])
            if abs((h1 - h2 + math.pi) % (2 * math.pi) - math.pi) > math.radians(cone):
                continue
            # nothing else touches the joint (a third road ending or passing within 2 m)
            jx, jy = pa[-1]
            if sum(1 for _ in allv.query_ball_point((jx, jy), 2.0)) > 6:
                continue
            pcs[a] = pa + pb[1:]
            del pcs[b]
            done.update((a, b))
            count += 1
        merged += count
        if not count:
            break
    print(f"  {merged} joints merged into longer pieces")
    for k, p in items:
        if k in pcs:
            vias[k]["p"] = [round(c, 1) for pt in pcs[k] for c in pt]
    gone = set(k for k, _ in items) - set(pcs)
    d["vias"] = [v for k, v in enumerate(vias) if k not in gone]
    json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    r = analyse([p for _, p in pieces_of(d)])
    print(f"{len(pcs)} pieces, {r['groups']} groups (biggest {r['biggest']}), {len(r['loose'])} loose ends")


def ligar_grupos(src, dst, reach=30.0, cone=45.0, small=6):
    """A small group of roads (a stretch with `small` pieces or fewer) that does not touch the big network: each of its loose ends that points at
    a road of another group within `reach` m is joined to it (a connector, and a vertex on the road it meets)."""
    d = json.load(open(src, encoding="utf-8"))
    items = pieces_of(d)
    pcs = [p for _, p in items]
    n = len(pcs)
    pts, own = [], []
    for k, p in enumerate(pcs):
        for q in dense(p, 1.5):
            pts.append(q)
            own.append(k)
    tree = cKDTree(np.array(pts))
    own = np.array(own)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for k, p in enumerate(pcs):
        for e in (p[0], p[-1]):
            for j in tree.query_ball_point(e, TOL):
                if own[j] != k:
                    parent[find(k)] = find(int(own[j]))
    size = collections.Counter(find(k) for k in range(n))
    r = analyse(pcs)
    added = []
    inserts = collections.defaultdict(list)
    for k, e in r["loose"]:
        g = find(k)
        if size[g] > small:
            continue
        p = pcs[k]
        a, b = (p[0], p[1]) if math.hypot(p[0][0] - e[0], p[0][1] - e[1]) < 1e-6 else (p[-1], p[-2])
        head = math.atan2(a[1] - b[1], a[0] - b[0])
        best = None
        for j in tree.query_ball_point(e, reach):
            o = int(own[j])
            if find(o) == g:
                continue
            q = pts[j]
            ang = math.atan2(q[1] - e[1], q[0] - e[0])
            if abs((head - ang + math.pi) % (2 * math.pi) - math.pi) > math.radians(cone):
                continue
            dist = math.hypot(q[0] - e[0], q[1] - e[1])
            if best is None or dist < best[0]:
                best = (dist, o, q)
        if not best:
            continue
        dist, o, q = best
        va = d["vias"][items[k][0]]
        added.append({"h": 0, "w": min(va.get("w") or 6.0, d["vias"][items[o][0]].get("w") or 6.0), "z": va.get("z", 0.0), "n": va.get("n") or 0, "c": va["c"], "o": 0,
                      "p": [round(e[0], 1), round(e[1], 1), round(q[0], 1), round(q[1], 1)]})
    d["vias"] += added
    json.dump(d, open(dst, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    r2 = analyse([p for _, p in pieces_of(d)])
    print(f"{len(added)} connectors from small groups to the network; now {r2['groups']} groups (biggest {r2['biggest']}), {r2['small']} small groups, {len(r2['loose'])} loose ends")


if __name__ == "__main__":
    {"grupos": lambda: ligar_grupos(sys.argv[2], sys.argv[3]), "limpar": lambda: limpar(sys.argv[2], sys.argv[3]), "medir": lambda: medir(sys.argv[2]), "unir": lambda: unir(sys.argv[2], sys.argv[3]), "ligar": lambda: ligar(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
