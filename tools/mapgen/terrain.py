#!/usr/bin/env python3
"""Contour lines of a map's terrain, from the map's own height files (`tile_<x>_<y>.map.terrain`).

Each file is the number of cells (60), then (cells + 1)^2 float32 heights in metres, row by row (the row is the
position in the tile along y, the column along x); a tile's edge samples are its neighbours' too. The tiles are laid
side by side on one grid, in metres of the author's tile grid (tile column * grid + position in the tile), and the
contour lines are traced on it. The writers of surface.oms (osm_to_package.py, exportar_openomsi_realmap.py) put them
in the package as line class 5, `width` = the height in metres, and class 6 for the index lines (every fifth), which
the maps draw heavier. It is an option of the generators: --contours <interval in metres>.

  python terrain_contours.py --map-dir "<OMSI 2>/Maps/RMG Leste" --grid 585.795 --interval 5
"""
import argparse
import glob
import math
import os
import re
import struct

import numpy as np
import contourpy


def read_terrain(path):
    b = open(path, "rb").read()
    if len(b) < 4:
        return None
    cells = struct.unpack("<I", b[:4])[0]
    n = (cells + 1) ** 2
    if cells == 0 or len(b) < 4 + 4 * n:
        return None
    return cells, np.frombuffer(b[4:4 + 4 * n], dtype="<f4").reshape(cells + 1, cells + 1)


def contours(map_dir, grid, interval=5.0, tiles=None, simplify=2.0):
    """[(height, is_index, [(x, y), ...])] in metres of the author's grid. `tiles`: only these (tx, ty), if given."""
    found = {}
    for f in glob.glob(os.path.join(map_dir, "tile_*.map.terrain")):
        m = re.search(r"tile_(-?\d+)_(-?\d+)\.map\.terrain$", f)
        tx, ty = int(m.group(1)), int(m.group(2))
        if tiles is not None and (tx, ty) not in tiles:
            continue
        t = read_terrain(f)
        if t:
            found[(tx, ty)] = t
    if not found:
        return []
    cells = next(iter(found.values()))[0]
    txs, tys = [k[0] for k in found], [k[1] for k in found]
    tx0, ty0 = min(txs), min(tys)
    W, H = (max(txs) - tx0 + 1) * cells + 1, (max(tys) - ty0 + 1) * cells + 1
    z = np.full((H, W), np.nan, dtype=np.float32)
    for (tx, ty), (c, h) in found.items():
        z[(ty - ty0) * cells:(ty - ty0) * cells + c + 1, (tx - tx0) * cells:(tx - tx0) * cells + c + 1] = h
    zm = np.ma.masked_invalid(z)
    step = grid / cells
    xs = (tx0 * grid) + np.arange(W) * step
    ys = (ty0 * grid) + np.arange(H) * step
    gen = contourpy.contour_generator(xs, ys, zm, line_type=contourpy.LineType.Separate)
    lo, hi = float(np.nanmin(z)), float(np.nanmax(z))
    out = []
    for k in range(int(math.floor(lo / interval)), int(math.ceil(hi / interval)) + 1):
        level = k * interval
        if level < lo or level > hi:
            continue
        index = k % 5 == 0
        for line in gen.lines(level):
            pts = [(float(x), float(y)) for x, y in line]
            if simplify and len(pts) > 2:
                pts = rdp(pts, simplify)
            if len(pts) >= 2:
                out.append((level, index, pts))
    return out


def rdp(pts, eps):
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        best, bi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if d2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
                d = math.hypot(px - ax - u * dx, py - ay - u * dy)
            if d > best:
                best, bi = d, i
        if best > eps and bi >= 0:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map-dir", required=True)
    ap.add_argument("--grid", type=float, required=True)
    ap.add_argument("--interval", type=float, default=5.0)
    a = ap.parse_args()
    c = contours(a.map_dir, a.grid, a.interval)
    heights = sorted({h for h, _, _ in c})
    print(f"{len(c)} lines, {sum(len(p) for _, _, p in c)} points, heights {heights[0]:.0f}..{heights[-1]:.0f} m" if c else "no terrain")
