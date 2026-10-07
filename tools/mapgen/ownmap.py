#!/usr/bin/env python3
"""ownmap.py - a package made from the map's OWN tiles alone: no OpenStreetMap, no network, no place on the Earth.

For a fictional map, or when the author does not want real data, the map itself is measured. Its tiles say, in metres of
their own grid, where every spline (road, rail, water course) runs, where every object stands (a tree, a house, a stadium,
a pond) and how high the ground is. This module turns that into the same files a real-data package has, so that the city
map has a surface under the roads that the game does not draw on its own:

  forest    where the TREE objects are dense        (Trees_MC, firs, forest backdrops, shrubs ...)
  built     where the BUILDING objects stand        (houses, blocks, halls, churches ...)
  water     where WATER objects or water courses lie
  sport     where pitches and stadiums stand
  rails     the splines that are RAILS and TRAMS    (class 1, drawn)
  rivers    the splines that are WATER COURSES      (class 0, drawn)
  relief    contour lines of the map's own ground   (--relief; heights as the editor has them, `terrain_offset` in the manifest
            moves them to sea level when the author knows the offset)

What is what is decided by the NAME of the file (the .sco of an object, the .sli of a spline): the patterns below are the
whole "knowledge" of this module. Edit them for the content of your map; an object that matches none is left out.
Roads are not drawn by the surface (the game draws its own lanes); what the package adds for them is the lines, stops and
timetables (omsimap.py) and, if you give them, street names (`--street-names`, see mapgen.py).
"""
import glob
import math
import os
import re

import numpy as np
from scipy import ndimage

import omsimap
import surfacefile
from geom import rdp

CHUNK = 2000.0
ORIGIN = [0.0, 0.0]      # the surface's origin (set per run): geometry is stored relative to it

# --- what is what: patterns on the lower-case path of the .sco / .sli file --------------------------------------------
TREES = r"tree|baum|bäume|arbor|fir_|fichte|pine|kiefer|shrub|busch|bush|hedge|hecke|forest|wald|drzew|laub|birke|eiche|palm|conifer"
BUILDINGS = r"haus|house|gebaeude|gebäude|building|\bbud|blok|block|kamien|halle|\bhall|shop|store|garage|fabr|factory|church|kirche|kosci|tower|hochhaus|apartment|wohn|villa|\bdom\b|dom_|warehouse|magazyn|school|szko|hotel|mall|terminal|dworzec|bahnhof|cottage|bungalow|plattenbau|office|biuro|depot|hangar"
NOT_BUILDINGS = r"fence|zaun|pole|mast|sign|schild|light|lamp|bus_stop|haltestelle|bench|bank_|trash|müll|car_park|people|human|tree|baum|traffic|signal|wall|mauer|kabel|wire|garden_|hedge"
WATER = r"wasser|water|woda|rzek|river|lake|teich|pond|jezior|\bsee\b|meer\b|\bsea\b|fountain"
SPORT = r"stadion|stadium|boisko|pitch|tennis|spielplatz|playground|sport|fussball|football|basketball"
RAIL_SPLINE = r"rail|gleis|tram|szyn|schiene|\btor\b|track"
NOT_RAIL = r"odciag|catenary|oberleitung|fahrdraht|wire|mast|sleeper|bed|schotter|ballast"
WATER_SPLINE = r"river|fluss|bach\b|rzek|canal|kanal|woda|water|wasser|stream"

# --- how objects become areas: cell size (m), reach of one object (m), smallest area kept (cells) ---------------------
AREAS = {
    #  name     class  pattern            cell  reach  min_cells  dilate/close (cells)
    "forest": (4, TREES, 14.0, 22.0, 20, 2),
    "built": (2, BUILDINGS, 8.0, 14.0, 4, 1),
    "water": (0, WATER, 10.0, 25.0, 4, 1),
    "sport": (5, SPORT, 10.0, 25.0, 3, 1),
}


def scan(map_dir, grid):
    """Splines and objects of every tile: ([(sli, [(x, y)])], [(sco, x, y)]) in metres of the map's grid."""
    splines, objects = [], []
    for f in sorted(glob.glob(os.path.join(map_dir, "tile_*.map"))):
        m = re.search(r"tile_(-?\d+)_(-?\d+)", f)
        ox, oy = int(m.group(1)) * grid, int(m.group(2)) * grid
        t = omsimap.rows(f)
        for i, l in enumerate(t):
            if l in ("[spline]", "[spline_h]"):
                try:
                    x, y, h, L, r = (float(t[i + k]) for k in (6, 8, 9, 10, 11))
                except (ValueError, IndexError):
                    continue
                splines.append((t[i + 2].strip().lower().replace("\\", "/"), omsimap.curve(x, y, h, L, r, ox, oy)))
            elif l == "[object]":
                try:
                    a, b = float(t[i + 4]), float(t[i + 5])
                except (ValueError, IndexError):
                    continue
                objects.append((t[i + 2].strip().lower().replace("\\", "/"), ox + a, oy + b))
    return splines, objects


def kinds_report(splines, objects, top=12):
    """What the map holds, by name, and what each pattern took: so that an author sees what to add to the patterns."""
    out = []
    from collections import Counter
    oc = Counter(o[0] for o in objects)
    for name, (cls, pat, *_r) in AREAS.items():
        taken = sum(n for s, n in oc.items() if re.search(pat, s) and not (name == "built" and re.search(NOT_BUILDINGS, s)))
        out.append(f"{name}: {taken} of {len(objects)} objects")
    left = Counter({s: n for s, n in oc.items() if not any(re.search(p[1], s) for p in AREAS.values())})
    out.append("objects no pattern took (most frequent): " + ", ".join(f"{os.path.basename(s)} x{n}" for s, n in left.most_common(top)))
    sc = Counter(s[0] for s in splines)
    rails = sum(n for s, n in sc.items() if re.search(RAIL_SPLINE, s) and not re.search(NOT_RAIL, s))
    water = sum(n for s, n in sc.items() if re.search(WATER_SPLINE, s))
    out.append(f"rail splines: {rails}, water splines: {water} of {len(splines)}")
    return out


def _runs_to_tris(mask, x0, y0, cell, tris_by_chunk, cls):
    """A boolean raster as triangles (two per run of cells in a row), filed by the chunk of their centre."""
    H, W = mask.shape
    for j in range(H):
        row = mask[j]
        if not row.any():
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        for a, b in zip(edges[::2], edges[1::2]):
            xa, xb, ya, yb = x0 + a * cell - ORIGIN[0], x0 + b * cell - ORIGIN[0], y0 + j * cell - ORIGIN[1], y0 + (j + 1) * cell - ORIGIN[1]
            for tri in ((xa, ya, xb, ya, xb, yb), (xa, ya, xb, yb, xa, yb)):
                k = (math.floor((tri[0] + tri[2] + tri[4]) / 3 / CHUNK), math.floor((tri[1] + tri[3] + tri[5]) / 3 / CHUNK))
                tris_by_chunk.setdefault(k, {}).setdefault(cls, []).extend(tri)


def area_of(points, cell, reach, min_cells, grow, box):
    """Object positions -> a raster of where they are dense enough to be an area."""
    x0, y0, x1, y1 = box
    W, H = int((x1 - x0) / cell) + 3, int((y1 - y0) / cell) + 3
    m = np.zeros((H, W), bool)
    for (x, y) in points:
        m[int((y - y0) / cell) + 1, int((x - x0) / cell) + 1] = True
    r = max(1, int(round(reach / cell)))
    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    m = ndimage.binary_dilation(m, structure=(xx * xx + yy * yy) <= r * r)
    if grow:
        m = ndimage.binary_closing(m, structure=np.ones((2 * grow + 1, 2 * grow + 1), bool))
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        for k, s in enumerate(sizes, 1):
            if s < min_cells * 9:
                m[lab == k] = False
    return m, x0 - cell, y0 - cell


def build_own_surface(map_dir, grid, tiles, out_dir, relief=0.0, log=print):
    """Writes surface.oms from the map's own tiles. Returns a summary."""
    splines, objects = scan(map_dir, grid)
    for l in kinds_report(splines, objects):
        log("  " + l)
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    ox, oy = min(xs) * grid, min(ys) * grid
    ORIGIN[0], ORIGIN[1] = ox, oy
    box = (ox - grid, oy - grid, (max(xs) + 2) * grid, (max(ys) + 2) * grid)
    fills = {}
    for name, (cls, pat, cell, reach, min_cells, grow) in AREAS.items():
        pts = [(x, y) for s, x, y in objects if re.search(pat, s) and not (name == "built" and re.search(NOT_BUILDINGS, s))]
        if not pts:
            continue
        m, mx, my = area_of(pts, cell, reach, min_cells, grow, box)
        _runs_to_tris(m, mx, my, cell, fills, cls)
        log(f"  {name}: {len(pts)} objects -> {int(m.sum() * cell * cell / 1e4)} ha")
    # lines: rails and water courses, from the splines
    lines = {}

    def put(cls, width, pts):
        pts = rdp([(x - ORIGIN[0], y - ORIGIN[1]) for x, y in pts], 1.0)
        cur, key = [pts[0]], None
        for p, q in zip(pts, pts[1:]):
            k = (math.floor((p[0] + q[0]) / 2 / CHUNK), math.floor((p[1] + q[1]) / 2 / CHUNK))
            if key is None:
                key = k
            if k != key:
                lines.setdefault(key, []).append((cls, 0, width, 0xFFFFFFFF, cur))
                cur, key = [p], k
            cur.append(q)
        lines.setdefault(key if key is not None else (0, 0), []).append((cls, 0, width, 0xFFFFFFFF, cur))

    n_rail = n_water = 0
    for sli, pts in splines:
        if len(pts) < 2:
            continue
        if re.search(RAIL_SPLINE, sli) and not re.search(NOT_RAIL, sli):
            put(1, 4.0, pts)
            n_rail += 1
        elif re.search(WATER_SPLINE, sli):
            put(0, 6.0, pts)
            n_water += 1
    log(f"  lines: {n_rail} rail pieces, {n_water} water-course pieces")
    n_c = 0
    if relief > 0:
        import terrain
        for height, index, pts in terrain.contours(map_dir, grid, relief, set(tiles), simplify=2.0):
            put(6 if index else 5, float(height), pts)
            n_c += 1
        log(f"  relief: {n_c} contour pieces every {relief:g} m")

    surf = dict(ver=1, origin=(ox, oy), chunk=CHUNK, names=[], chunks={})
    for k in set(fills) | set(lines):
        surf["chunks"][k] = (fills.get(k, {}), [(c, fl, w, nm, [v for p in pts for v in p]) for c, fl, w, nm, pts in lines.get(k, [])], [])
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "surface.oms")
    surfacefile.write_surface(surf, path)
    return dict(bytes=os.path.getsize(path), chunks=len(surf["chunks"]), objects=len(objects), splines=len(splines), contours=n_c)
