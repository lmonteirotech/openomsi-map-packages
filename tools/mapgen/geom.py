#!/usr/bin/env python3
"""geom.py - small plane-geometry helpers used by the surface writer: polygon stitching, simplification (RDP),
clipping, ear-clipping triangulation, point-in-polygon, and the box a name fits in. Pure Python, no dependencies."""
import math


def stitch(ways):
    """Chain ways (lists of (lat, lon)) end to end by their end points: closed rings, and what stays open."""
    key = lambda p: (round(p[0], 7), round(p[1], 7))
    pool = [list(w) for w in ways if len(w) >= 2]
    rings, open_ = [], []
    while pool:
        cur = pool.pop()
        grown = True
        while grown and key(cur[0]) != key(cur[-1]):
            grown = False
            for i, w in enumerate(pool):
                if key(w[0]) == key(cur[-1]):
                    cur += w[1:]
                elif key(w[-1]) == key(cur[-1]):
                    cur += w[::-1][1:]
                elif key(w[-1]) == key(cur[0]):
                    cur = w + cur[1:]
                elif key(w[0]) == key(cur[0]):
                    cur = w[::-1] + cur[1:]
                else:
                    continue
                pool.pop(i)
                grown = True
                break
        (rings if key(cur[0]) == key(cur[-1]) and len(cur) >= 4 else open_).append(cur)
    return rings, open_


def rdp(pts, tol):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        l = math.hypot(dx, dy) or 1e-9
        worst, wi = 0.0, 0
        for k in range(a + 1, b):
            d = abs((pts[k][0] - ax) * dy - (pts[k][1] - ay) * dx) / l
            if d > worst:
                worst, wi = d, k
        if worst > tol:
            keep[wi] = True
            stack += [(a, wi), (wi, b)]
    return [p for p, k in zip(pts, keep) if k]


def rdp_ring(pts, tol):
    """Douglas-Peucker for a closed ring. It is cut in two at the point farthest from the first one: the plain version
    takes the two (equal) ends for a segment of no length and would drop the whole ring."""
    ring = pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else list(pts)
    if len(ring) < 4:
        return ring + ring[:1]
    m = max(range(1, len(ring)), key=lambda k: (ring[k][0] - ring[0][0]) ** 2 + (ring[k][1] - ring[0][1]) ** 2)
    return rdp(ring[:m + 1], tol)[:-1] + rdp(ring[m:] + [ring[0]], tol)


def clip_rect(poly, x0, y0, x1, y1):
    """Sutherland-Hodgman: the part of a polygon inside a rectangle."""
    def step(pts, inside_, cross):
        out = []
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if inside_(p):
                if not inside_(q):
                    out.append(cross(q, p))
                out.append(p)
            elif inside_(q):
                out.append(cross(q, p))
        return out
    cx = lambda xv: (lambda a, b: (xv, a[1] + (b[1] - a[1]) * (xv - a[0]) / (b[0] - a[0])))
    cy = lambda yv: (lambda a, b: (a[0] + (b[0] - a[0]) * (yv - a[1]) / (b[1] - a[1]), yv))
    pts = list(poly)
    for inside_, cross in ((lambda p: p[0] >= x0, cx(x0)), (lambda p: p[0] <= x1, cx(x1)), (lambda p: p[1] >= y0, cy(y0)), (lambda p: p[1] <= y1, cy(y1))):
        if not pts:
            break
        pts = step(pts, inside_, cross)
    return pts


def area2(p):
    return sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))


def in_tri(a, b, c, p):
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def triangulate(poly):
    """Ear clipping of a simple polygon (no holes): a list of triangles (x0,y0,x1,y1,x2,y2), counter-clockwise."""
    p = list(poly)
    if len(p) > 1 and p[0] == p[-1]:
        p.pop()
    q = [p[0]] if p else []
    for v in p[1:]:
        if v != q[-1]:
            q.append(v)
    p = q
    if len(p) < 3:
        return []
    if area2(p) < 0:
        p.reverse()
    idx, tris, guard = list(range(len(p))), [], 0
    while len(idx) > 3 and guard < 100000:
        guard += 1
        n, found = len(idx), False
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = p[i0], p[i1], p[i2]
            if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) <= 1e-9:
                continue
            if any(in_tri(a, b, c, p[j]) for j in idx if j not in (i0, i1, i2) and p[j] not in (a, b, c)):
                continue
            tris.append((a[0], a[1], b[0], b[1], c[0], c[1]))
            idx.pop(k)
            found = True
            break
        if not found:
            idx.pop(0)       # not a simple polygon: drop its worst vertex rather than stall
    if len(idx) == 3:
        a, b, c = (p[i] for i in idx)
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 1e-9:
            tris.append((a[0], a[1], b[0], b[1], c[0], c[1]))
    return tris


def inside(poly, x, y):
    ins, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            ins = not ins
        j = i
    return ins


def edge_dist(poly, x, y):
    d, j = 1e30, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        dx, dy = xj - xi, yj - yi
        l2 = dx * dx + dy * dy
        t = max(0.0, min(1.0, ((x - xi) * dx + (y - yi) * dy) / l2)) if l2 > 1e-9 else 0.0
        d = min(d, (xi + t * dx - x) ** 2 + (yi + t * dy - y) ** 2)
        j = i
    return math.sqrt(d)


def label_box(poly, name):
    """Centre and size of the box the district's name fits in: the largest letters whose box lies inside the outline,
    around the point farthest from the edge (the pole of inaccessibility). Letter widths are approximated (0.72 of the
    letter size for capitals, with a little spacing), as the game scales the text to the box anyway."""
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cel = max(x1 - x0, y1 - y0) / 48
    best = None
    for gy in range(49):
        for gx in range(49):
            x, y = x0 + (gx + 0.5) * cel, y0 + (gy + 0.5) * cel
            if x <= x1 and y <= y1 and inside(poly, x, y):
                d = edge_dist(poly, x, y)
                if best is None or d > best[2]:
                    best = [x, y, d]
    if not best:
        return None
    step = cel * 0.5
    for _ in range(40):
        if step <= 0.5:
            break
        moved = False
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if (dx or dy):
                    x, y = best[0] + dx * step, best[1] + dy * step
                    if inside(poly, x, y) and edge_dist(poly, x, y) > best[2]:
                        best = [x, y, edge_dist(poly, x, y)]
                        moved = True
        if not moved:
            step *= 0.5
    w1 = len(name) * 0.72 * 1.05

    def fits(cx, cy, w, h):
        hw, hh = w / 2, h / 2
        pts = []
        for k in range(13):
            t = -1 + 2 * k / 12
            pts += [(cx + t * hw, cy - hh), (cx + t * hw, cy + hh), (cx - hw, cy + t * hh), (cx + hw, cy + t * hh)]
        return all(inside(poly, x, y) for x, y in pts)

    lo, hi = 0.0, min(2.4 * best[2] / w1, best[2] * 2)
    for _ in range(24):
        s = (lo + hi) / 2
        if s > 1 and fits(best[0], best[1], w1 * s * 1.28, s * 1.28):
            lo = s
        else:
            hi = s
    return (best[0], best[1], w1 * lo, lo) if lo > 1 else None


