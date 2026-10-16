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

import footprints
import omsimap
import patterns
import surfacefile
from geom import rdp, triangulate

CHUNK = 2000.0
ORIGIN = [0.0, 0.0]      # the surface's origin (set per run): geometry is stored relative to it
OMSI = [None]            # the OMSI 2 folder, to read the .sli files of the splines (what lanes a spline carries)

# --- what is what: the words of the path of the .sco / .sli file (patterns.py: en, de, pl, pt, es, fr) ---------------------
RAIL_SPLINE = patterns.RAIL_WORDS
NOT_RAIL = patterns.NOT_RAIL_WORDS
WATER_SPLINE = patterns.WATER_SPLINE_WORDS

# --- how objects become areas: cell size (m), reach of one object (m), smallest area kept (cells) ---------------------
AREAS = {
    #  category  class  cell  reach  min_cells  dilate/close (cells)
    "forest": (4, 14.0, 22.0, 20, 2),
    "grass": (3, 14.0, 24.0, 20, 2),
    "farm": (6, 14.0, 26.0, 10, 2),
    "built": (2, 8.0, 14.0, 4, 1),
    "water": (0, 10.0, 25.0, 4, 1),
    "sport": (5, 10.0, 25.0, 3, 1),
}


def scan(map_dir, grid, headings=False, attachments=True):
    """Splines and objects of every tile: ([(sli, [(x, y)])], [(sco, x, y)]) in metres of the map's grid;
    with `headings`, each object is (sco, x, y, heading in degrees clockwise from north). With `attachments`, the objects of the
    [splineAttachement] rows (houses, trees, lamps along a street) are objects too, standing where the game puts them, except
    the kinds that are mere street furniture (patterns.py: 'other'), which would be many thousands."""
    splines, objects = [], []
    for f in sorted(glob.glob(os.path.join(map_dir, "tile_*.map"))):
        m = re.search(r"tile_(-?\d+)_(-?\d+)", f)
        ox, oy = int(m.group(1)) * grid, int(m.group(2)) * grid
        t = omsimap.rows(f)
        order = []                     # every spline of the tile in file order: an attachment names its spline by that index
        rows_at = []
        for i, l in enumerate(t):
            if l in ("[spline]", "[spline_h]"):
                try:
                    x, y, h, L, r = (float(t[i + k]) for k in (6, 8, 9, 10, 11))
                except (ValueError, IndexError):
                    order.append(None)
                    continue
                order.append((x, y, h, L, r))
                splines.append((t[i + 2].strip().lower().replace("\\", "/"), omsimap.curve(x, y, h, L, r, ox, oy)))
            elif l == "[object]":
                try:
                    a, b = float(t[i + 4]), float(t[i + 5])
                except (ValueError, IndexError):
                    continue
                if headings:
                    try:
                        hd = float(t[i + 7])
                    except (ValueError, IndexError):
                        hd = 0.0
                    objects.append((t[i + 2].strip().lower().replace("\\", "/"), ox + a, oy + b, hd))
                else:
                    objects.append((t[i + 2].strip().lower().replace("\\", "/"), ox + a, oy + b))
            elif l == "[splineAttachement]" and attachments:
                rows_at.append(i)
        for i in rows_at:
            sco = t[i + 2].strip().lower().replace("\\", "/")
            if patterns.classify(sco) == "other":
                continue
            try:
                k = int(t[i + 4])
                lateral, d0 = float(t[i + 5]), float(t[i + 7])
                rot0, interval, rng = float(t[i + 8]), float(t[i + 11]), float(t[i + 12])
            except (ValueError, IndexError):
                continue
            if not (0 <= k < len(order)) or not order[k]:
                continue
            n = 1 if interval <= 0 else min(int(rng / interval) + 1, 600)
            for j in range(n):
                kk, d = k, d0 + j * max(interval, 0.0)
                while kk + 1 < len(order) and order[kk] and order[kk + 1] and d > order[kk][3]:
                    d -= order[kk][3]
                    kk += 1
                if not order[kk]:
                    break
                x, y, h, L, r = order[kk]
                if d > L + 0.5 and kk + 1 >= len(order):
                    break
                s = max(0.0, min(d, L))
                px, py = omsimap.curve(x, y, h, s, r, 0.0, 0.0)[-1] if s > 0 else (x, y)
                hs = h + (math.degrees(s / r) if abs(r) > 1e-6 else 0.0)
                c, sn = math.cos(math.radians(hs)), math.sin(math.radians(hs))
                wx, wy = ox + px + lateral * c, oy + py - lateral * sn
                objects.append((sco, wx, wy, hs + rot0) if headings else (sco, wx, wy))
    return splines, objects


def kinds_report(splines, objects, top=12):
    """What the map holds, by name, and what each category took: so that an author sees what to add to patterns.py."""
    out = []
    from collections import Counter
    oc = Counter(o[0] for o in objects)
    cat = Counter()
    for s, n in oc.items():
        cat[patterns.classify(s)] += n
    out.append("objects by kind (by the words of their paths): " + ", ".join(f"{k or 'unknown'} {cat[k]}" for k in AREAS) + f", other things {cat['other']}, unknown {cat['']} of {len(objects)}")
    left = Counter({s: n for s, n in oc.items() if not patterns.classify(s)})
    out.append("objects no word took (most frequent): " + ", ".join(f"{os.path.basename(s)} x{n}" for s, n in left.most_common(top)))
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
        r, c = int((y - y0) / cell) + 1, int((x - x0) / cell) + 1
        if 0 <= r < H and 0 <= c < W:
            m[r, c] = True
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


def build_own_surface(map_dir, grid, tiles, out_dir, relief=0.0, log=print, omsi=None):
    """Writes surface.oms from the map's own tiles. Returns a summary."""
    OMSI[0] = omsi
    splines, objects = scan(map_dir, grid, headings=True)
    for l in kinds_report(splines, [o[:3] for o in objects]):
        log("  " + l)
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    ox, oy = min(xs) * grid, min(ys) * grid
    ORIGIN[0], ORIGIN[1] = ox, oy
    box = (ox - grid, oy - grid, (max(xs) + 2) * grid, (max(ys) + 2) * grid)
    # a stray object or spline far outside the map's tiles (a broken position in a tile file) must not stretch or break the raster
    n_o, n_s = len(objects), len(splines)
    objects = [o for o in objects if box[0] <= o[1] <= box[2] and box[1] <= o[2] <= box[3]]
    splines = [s for s in splines if all(box[0] <= x <= box[2] and box[1] <= y <= box[3] for x, y in s[1])]
    if len(objects) < n_o or len(splines) < n_s:
        log(f"  ignored {n_o - len(objects)} objects and {n_s - len(splines)} splines lying outside the map's tiles")
    fills = {}
    # buildings with a mesh get their own outline, placed as the game places the object; the rest of the buildings stay in the raster
    outlined = set()
    if OMSI[0]:
        fp = footprints.Footprints(OMSI[0])
        for n, (s, x, y, hd) in enumerate(objects):
            kind = patterns.classify(s)
            if kind in ("other", "water", "sport", "farm", "forest", "grass"):
                continue
            loc = fp.local(s)
            if loc and (kind == "built" or loc[2]):
                poly = fp.place(s, x, y, hd)
                for tri in triangulate([(px - ORIGIN[0], py - ORIGIN[1]) for px, py in poly]):
                    k = (math.floor((tri[0] + tri[2] + tri[4]) / 3 / CHUNK), math.floor((tri[1] + tri[3] + tri[5]) / 3 / CHUNK))
                    fills.setdefault(k, {}).setdefault(2, []).extend(tri)
                outlined.add(n)
        log(f"  built: {len(outlined)} buildings drawn with their own outline (from their meshes)")
    for name, (cls, cell, reach, min_cells, grow) in AREAS.items():
        pts = [(x, y) for n, (s, x, y, hd) in enumerate(objects) if n not in outlined and patterns.classify(s) == name]
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

    n_rail = n_water = n_street = 0
    for sli, pts in splines:
        if len(pts) < 2:
            continue
        if is_rail(OMSI[0], sli):
            put(1, 4.0, pts)
            n_rail += 1
        elif OMSI[0] and is_street(OMSI[0], sli):
            put(3, 0.0, pts)                    # a street: the very spline the game's roads run on
            n_street += 1
        elif re.search(WATER_SPLINE, sli):
            put(0, 6.0, pts)
            n_water += 1
    log(f"  lines: {n_street} street splines (the map's own), {n_rail} rail pieces, {n_water} water-course pieces")
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


# ---------------------------------------------------------------------------------------------------- the railway
_KINDS = {}


def path_kinds(omsi, sli):
    """{'0': n, '1': n, '2': n, '3': n}: how many lanes of each kind a spline file carries (0 street, 1 sidewalk, 2 RAIL, 3 air)."""
    if sli in _KINDS:
        return _KINDS[sli]
    k = {}
    f = os.path.join(omsi, sli.replace("/", os.sep)) if omsi else ""
    if f and os.path.isfile(f):
        t = [x.strip() for x in omsimap.rd(f).split("\n")]
        for i, l in enumerate(t):
            if l == "[path]" and i + 1 < len(t) and t[i + 1] in ("0", "1", "2", "3"):
                k[t[i + 1]] = k.get(t[i + 1], 0) + 1
    _KINDS[sli] = k
    return k


def is_rail(omsi, sli):
    """A spline of the railway or the tramway: it carries RAIL lanes (kind 2) and no street lane, or, with no lane at all, has the
    name of a rail. A street with tram tracks in it is a street; a catenary wire is no rail."""
    if re.search(NOT_RAIL, sli):
        return False
    k = path_kinds(omsi, sli)
    if k.get("0"):
        return False
    return bool(k.get("2")) or bool(re.search(RAIL_SPLINE, sli))


def is_street(omsi, sli):
    """A spline of a street: it carries a street lane ([path] 0 of its .sli) and is no rail. A spline whose .sli is not on this
    machine cannot be told, and is left out: that is a gap of the map's own files, not something to guess."""
    return bool(path_kinds(omsi, sli).get("0")) and not is_rail(omsi, sli)


def add_rails(surface_path, omsi, map_dir, grid, replace=False, log=print):
    """Puts the map's OWN rails (class 1, the class the city map draws as a railway) into an existing surface.oms, in its own frame.
    With replace=True the rail lines the surface had (OpenStreetMap's, bent to the map) go. Returns the number of pieces."""
    surf = surfacefile.read_surface(surface_path)
    ox, oy = surf["origin"]
    OMSI[0] = omsi
    splines, _ = scan(map_dir, grid)
    if replace:
        for k, (f, ls, lb) in surf["chunks"].items():
            surf["chunks"][k] = (f, [l for l in ls if l[0] != 1], lb)
    n = 0
    chunk = surf["chunk"]
    for sli, pts in splines:
        if len(pts) < 2 or not is_rail(omsi, sli):
            continue
        rel = rdp([(x - ox, y - oy) for x, y in pts], 1.0)
        cur, key = [rel[0]], None
        pieces = []
        for p, q in zip(rel, rel[1:]):
            kk = (math.floor((p[0] + q[0]) / 2 / chunk), math.floor((p[1] + q[1]) / 2 / chunk))
            if key is None:
                key = kk
            if kk != key:
                pieces.append((key, cur))
                cur, key = [p], kk
            cur.append(q)
        pieces.append((key, cur))
        for k, c in pieces:
            if len(c) < 2:
                continue
            f, ls, lb = surf["chunks"].get(k, ({}, [], []))
            ls.append((1, 0, 4.0, 0xFFFFFFFF, [v for p in c for v in p]))
            surf["chunks"][k] = (f, ls, lb)
        n += 1
    surfacefile.write_surface(surf, surface_path)
    log(f"  the map's own rails: {n} pieces put in {surface_path}")
    return n


# ---------------------------------------------------------------------------------------------------- the streets
def add_streets(surface_path, omsi, map_dir, grid, log=print, name_reach=40.0):
    """Puts the map's OWN streets (the splines that carry a street lane: the very ones the game's roads run on) into an existing
    surface.oms as street lines (class 3, or 4 with a limit), in its own frame, and takes the streets the surface had before
    (OpenStreetMap's, drawn where OpenStreetMap has them, not where the map does) out. Each own street keeps the NAME, and the
    speed limit, of the nearest street of the old ones within `name_reach` metres, so that names still come from the real
    city while the geometry is the map's. Returns (streets, named)."""
    from scipy.spatial import cKDTree
    surf = surfacefile.read_surface(surface_path)
    ox, oy = surf["origin"]
    OMSI[0] = omsi
    chunk = surf["chunk"]
    old_pts, old_info = [], []
    for k, (f, ls, lb) in surf["chunks"].items():
        keep = []
        for ln in ls:
            cls, fl, w, nm, pts = ln
            if cls in (3, 4):
                xy = list(zip(pts[0::2], pts[1::2]))
                for a, b in zip(xy, xy[1:]):
                    n = max(1, int(math.dist(a, b) / 12))
                    for j in range(n + 1):
                        old_pts.append((a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n))
                        old_info.append((cls, fl, w, nm))
            else:
                keep.append(ln)
        surf["chunks"][k] = (f, keep, lb)
    tree = cKDTree(old_pts) if old_pts else None
    splines, _ = scan(map_dir, grid, attachments=False)
    n = named = 0
    for sli, pts in splines:
        if len(pts) < 2 or not is_street(omsi, sli):
            continue
        rel = rdp([(x - ox, y - oy) for x, y in pts], 1.0)
        info = (3, 0, 0.0, 0xFFFFFFFF)
        if tree is not None:
            samples = [rel[i] for i in range(len(rel))] + [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(rel, rel[1:])]
            dist, idx = tree.query(samples)
            votes = {}
            for dd, ii in zip(dist, idx):
                if dd <= name_reach and old_info[ii][3] != 0xFFFFFFFF:
                    votes[old_info[ii]] = votes.get(old_info[ii], 0) + 1
            if votes:
                info = max(votes, key=votes.get)
                named += 1
        cls, fl, w, nm = info
        cur, key, pieces = [rel[0]], None, []
        for p, q in zip(rel, rel[1:]):
            kk = (math.floor((p[0] + q[0]) / 2 / chunk), math.floor((p[1] + q[1]) / 2 / chunk))
            if key is None:
                key = kk
            if kk != key:
                pieces.append((key, cur))
                cur, key = [p], kk
            cur.append(q)
        pieces.append((key, cur))
        for k, c in pieces:
            if len(c) >= 2:
                f, ls, lb = surf["chunks"].get(k, ({}, [], []))
                ls.append((cls, fl, w, nm, [v for p in c for v in p]))
                surf["chunks"][k] = (f, ls, lb)
        n += 1
    surfacefile.write_surface(surf, surface_path)
    log(f"  the map's own streets: {n} splines put in the package, {named} named from the real streets nearby")
    return n, named
