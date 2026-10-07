#!/usr/bin/env python3
"""check.py - what a finished package must satisfy, checked by the generator itself and written to REPORT.md.

  - NO ROAD IN WATER: not one road of the map (every spline of its tiles, sampled every 12 m) may lie in the water of the
    surface or within `margin` metres of it. `carve_water` repairs a surface that breaks the rule by removing the water
    triangles that touch a road (the shore then follows the roads there).
  - The lines' ways are one piece (no jump over 300 m between two stretches), the stops have a place on the map.
"""
import numpy as np
from scipy import ndimage
from PIL import Image, ImageDraw

import surfacefile

WATER = 0
CELL = 4.0


def _water_triangles(surf):
    ox, oy = surf["origin"]
    tris = []
    for fills, _, _ in surf["chunks"].values():
        t = fills.get(WATER)
        if t:
            tris += [np.array(t[i:i + 6]).reshape(3, 2) + (ox, oy) for i in range(0, len(t), 6)]
    return tris


def _water_distance(surf, roads, margin):
    """Distance (m) from every road point to the nearest water cell; None if the surface has no water."""
    tris = _water_triangles(surf)
    if not tris:
        return None
    lo, hi = roads.min(0) - 300, roads.max(0) + 300
    W, H = int((hi[0] - lo[0]) / CELL) + 1, int((hi[1] - lo[1]) / CELL) + 1
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for t in tris:
        d.polygon([((p[0] - lo[0]) / CELL, (p[1] - lo[1]) / CELL) for p in t], fill=1)
    water = np.array(im, dtype=bool)
    if not water.any():
        return None
    dist = ndimage.distance_transform_edt(~water) * CELL
    ix = np.clip(((roads[:, 0] - lo[0]) / CELL).astype(int), 0, W - 1)
    iy = np.clip(((roads[:, 1] - lo[1]) / CELL).astype(int), 0, H - 1)
    return dist[iy, ix]


def roads_vs_water(surface_path, roads, margin=16.0):
    """(road points in water, road points within `margin` m of water, total)."""
    surf = surfacefile.read_surface(surface_path)
    d = _water_distance(surf, roads, margin)
    if d is None:
        return 0, 0, len(roads)
    return int((d <= 0.5 * CELL).sum()), int((d <= margin).sum()), len(roads)


def carve_water(surface_path, roads, margin=16.0):
    """Removes the water triangles within `margin` m of a road point. Returns how many were removed."""
    surf = surfacefile.read_surface(surface_path)
    ox, oy = surf["origin"]
    lo, hi = roads.min(0) - 300, roads.max(0) + 300
    W, H = int((hi[0] - lo[0]) / CELL) + 1, int((hi[1] - lo[1]) / CELL) + 1
    road = np.zeros((H, W), dtype=bool)
    ix = np.clip(((roads[:, 0] - lo[0]) / CELL).astype(int), 0, W - 1)
    iy = np.clip(((roads[:, 1] - lo[1]) / CELL).astype(int), 0, H - 1)
    road[iy, ix] = True
    near = ndimage.distance_transform_edt(~road) * CELL <= margin
    removed = 0
    for key, (fills, lines, labels) in surf["chunks"].items():
        t = fills.get(WATER)
        if not t:
            continue
        keep = []
        for i in range(0, len(t), 6):
            tri = np.array(t[i:i + 6]).reshape(3, 2) + (ox, oy)
            samples = [tri[0], tri[1], tri[2], tri.mean(0), (tri[0] + tri[1]) / 2, (tri[1] + tri[2]) / 2, (tri[2] + tri[0]) / 2]
            hit = False
            for p in samples:
                jx, jy = int((p[0] - lo[0]) / CELL), int((p[1] - lo[1]) / CELL)
                if 0 <= jx < W and 0 <= jy < H and near[jy, jx]:
                    hit = True
                    break
            if hit:
                removed += 1
            else:
                keep += t[i:i + 6]
        if keep:
            fills[WATER] = keep
        else:
            del fills[WATER]
    surfacefile.write_surface(surf, surface_path)
    return removed


def report_text(info):
    """REPORT.md: what was done, what it is based on, and whether the rules hold."""
    L = [f"# mapgen report: {info['name']}", ""]
    L += [f"- mode: **{info['mode']}**" + (f" ({info['why']})" if info.get("why") else ""), f"- grid: {info['grid']:.3f} m, north: {info['north']:.1f} degrees"]
    if info.get("placement"):
        L.append(f"- placement: {info['placement']}")
    if info.get("locate"):
        r = info["locate"]
        L += ["", "## Where the map is (compared with OpenStreetMap)", ""]
        L.append(f"- stop names in common (first similarity): {r.get('stop_pairs', 0)}")
        L.append(f"- roads on streets, similarity only: median {r.get('similarity_median', 0):.1f} m, 90% {r.get('similarity_p90', 0):.1f} m, {r.get('similarity_cover', 0) * 100:.0f}% of the road points within 60 m of a street")
        if "bend" in r:
            L.append(f"- landmarks (stops by name, by street, by neighbourhood, bus routes): {r.get('landmarks', 0)}")
            L.append(f"- the real world was bent to the map by {r['bend'][0]:.0f} m (median), {r['bend'][1]:.0f} m (90%), {r['bend'][2]:.0f} m (most)")
            L.append(f"- roads on streets after the field: median {r.get('field_median', 0):.1f} m, 90% {r.get('field_p90', 0):.1f} m, {r.get('field_cover', 0) * 100:.0f}% within 60 m")
    L += ["", "## Lines", ""]
    if info.get("lines"):
        ln = info["lines"]
        L.append(f"- {ln['lines']} lines in {ln['forms']} forms {ln['by_modal']}; {ln['stations']} stations of the map's railways")
        L.append(f"- jumps over 300 m inside a way: {len(ln['jumps'])}" + ("" if not ln["jumps"] else " (" + ", ".join(f"{n} {m} m" for n, m in ln["jumps"][:8]) + ")"))
    L += ["", "## Rules", ""]
    if info.get("water"):
        i, n, t = info["water"]
        if info["mode"] == "shore":
            L.append(f"- no road in water: {'**OK**' if i == 0 and n == 0 else '**BROKEN**'} ({i} road points in water, {n} within 16 m of it, of {t})")
        else:     # a map that is the city has its bridges: the rule is for the shore-only package
            L.append(f"- road points over water (bridges, ferries; the rule \"no road in water\" is for the shore-only package): {i} in water, {n} within 16 m of it, of {t}")
        if info.get("carved"):
            L.append(f"- the water was trimmed where it touched a road ({info['carved']} triangles removed)")
    return "\n".join(L) + "\n"
