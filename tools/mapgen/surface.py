#!/usr/bin/env python3
"""surface.py - the real-world layers of a package: surface.oms (and, for the full profile, regions.cfg and markers.cfg).

Two profiles, the second one for a map that is not aligned with reality:

  full    water, green, woods, built-up land, rivers, rail, district borders, place names, named streets with their
          speed limits, the districts (regions.cfg) and the stations (markers.cfg); relief if asked.
  shore   only the large water areas and the rivers and canals: the SHORE. Nothing else of the real world: the map's own
          roads, stops, lines and timetables are the truth. (Areas under 2 ha and streams are left out.)

The data comes from OpenStreetMap (osm.py), laid on the map by a placement (placement.py): the tile index for a map with
[worldcoordinates], a calibration (locate.py) otherwise. Positions are written as metres of the author's grid, relative
to an origin, in the binary OMSF v1 of docs/MAP_PACKAGE.md (2 km chunks of fills, lines and labels).
"""
import json
import math
import os
import re
import struct
import sys
import types

import numpy as np

import osm
from geom import (area2, clip_rect, edge_dist, inside, in_tri, label_box, rdp, rdp_ring, stitch, triangulate)
from placement import FittedPlacement, WorldPlacement

CHUNK = 2000.0          # metres, the chunk edge of surface.oms
BLOCK = 8               # tiles on a side of the blocks the map is downloaded in


def route_query(area):
    return f"""[out:json][timeout:240];
area["name"="{area}"]["boundary"="administrative"]->.a;
relation["route"="bus"](area.a);
out geom;"""


# ---------------------------------------------------------------------------- classes

FILL_WATER, FILL_GREEN, FILL_BUILT, FILL_GRASS, FILL_FOREST, FILL_SPORT, FILL_FARM = 0, 1, 2, 3, 4, 5, 6
LINE_RIVER, LINE_RAIL, LINE_BORDER, LINE_STREET, LINE_STREET_LIMITS, LINE_CONTOUR, LINE_CONTOUR_INDEX = 0, 1, 2, 3, 4, 5, 6


def fill_class(tags):
    n, l, lu = tags.get("natural"), tags.get("leisure"), tags.get("landuse")
    if n in ("water", "wetland") or lu in ("reservoir", "basin"):
        return FILL_WATER
    if n in ("wood",) or lu == "forest":
        return FILL_FOREST
    if n in ("scrub", "grassland", "heath") or lu in ("grass", "meadow", "allotments"):
        return FILL_GRASS
    if l in ("pitch", "stadium", "playground", "golf_course"):
        return FILL_SPORT
    if lu in ("farmland", "orchard"):
        return FILL_FARM
    if l in ("park", "garden", "recreation_ground") or lu in ("recreation_ground", "cemetery"):
        return FILL_GREEN
    if lu in ("industrial", "commercial", "retail", "residential"):
        return FILL_BUILT
    return None


RANK = {"motorway": 0, "motorway_link": 5, "trunk": 1, "trunk_link": 5, "primary": 1, "primary_link": 5, "secondary": 2,
        "secondary_link": 5, "tertiary": 3, "tertiary_link": 5, "unclassified": 4, "residential": 4, "living_street": 4}
SPEEDS = {"walk": 7, "de:living_street": 7, "de:urban": 50, "de:zone30": 30, "de:zone:30": 30, "de:rural": 100,
          "br:urban": 60, "br:rural": 80}


def parse_speed(v):
    """A maxspeed tag in km/h (0: none or not a number): "50", "30 mph", "walk", "DE:urban", "30;50" (the first)."""
    if not v:
        return 0
    first = v.split(";")[0].strip().lower()
    if first in SPEEDS:
        return SPEEDS[first]
    m = re.match(r"(\d+)\s*(mph)?$", first)
    if not m:
        return 0
    n = int(m.group(1))
    return min(255, round(n * 1.609) if m.group(2) else n)


PLACE_RANK = {"city": 255, "town": 200, "quarter": 140, "suburb": 120, "neighbourhood": 100, "village": 160}



def build_surface(g, tiles, out_dir, cache, profile="full", contours=0.0, district_level=10, area_name=None, icons=None):
    """Downloads the real world's layers for the tiles of the map and writes the package's surface files into `out_dir`.
    `g`: a placement; `tiles`: the tiles that count as the map; `profile`: "full" or "shore"."""
    a = types.SimpleNamespace(minimal=(profile == "shore"), contours=contours, cache=cache, out=out_dir, district_level=district_level,
                              area_name=area_name, icons=icons)
    xs, ys = [t[0] for t in tiles], [t[1] for t in tiles]
    def box(tx0, ty0, tx1, ty1):
        """South, west, north, east of the rectangle of tiles (a calibrated map may be turned: all four corners)."""
        cs = [g.latlon(tx, ty, 0, 0) for tx in (tx0, tx1) for ty in (ty0, ty1)]
        s_, w_, n_, e_ = min(c[0] for c in cs), min(c[1] for c in cs), max(c[0] for c in cs), max(c[1] for c in cs)
        if isinstance(g, FittedPlacement):
            s_, w_ = math.floor(s_ * 100) / 100, math.floor(w_ * 100) / 100
            n_, e_ = math.ceil(n_ * 100) / 100, math.ceil(e_ * 100) / 100
        return s_, w_, n_, e_

    south, west, north, east = box(min(xs) - 1, min(ys) - 1, max(xs) + 2, max(ys) + 2)
    origin = (min(xs) * g.ts, min(ys) * g.ts)

    def au(lat, lon):          # author-grid metres, relative to the origin
        x, y = g.to_author(lat, lon)
        return x - origin[0], y - origin[1]

    # --- 1. the blocks that have a tile
    blocks = sorted({(tx // BLOCK, ty // BLOCK) for tx, ty in tiles})
    elements = {}
    block_q = osm.water_block_query if a.minimal else osm.block_query
    boxes = [box(bx * BLOCK - 1, by * BLOCK - 1, (bx + 1) * BLOCK + 1, (by + 1) * BLOCK + 1) for bx, by in blocks]
    osm.plan([block_q(*bb) for bb in boxes], a.cache)           # how many are still to ask, and how long it will take
    for n, (s, w, nn, e) in enumerate(boxes, 1):
        print(f"block {n}/{len(blocks)} ...", flush=True)
        for el in osm.overpass(block_q(s, w, nn, e), a.cache).get("elements", []):
            elements[(el["type"], el["id"])] = el
    print(len(elements), "elements")

    fills = {}                      # chunk -> class -> flat triangle list
    lines = {}                      # chunk -> list of (class, flags, width, name, pts)
    labels, markers = {}, []
    names, name_ix = [], {}

    def nid(s):
        if not s:
            return 0xFFFFFFFF
        if s not in name_ix:
            name_ix[s] = len(names)
            names.append(s)
        return name_ix[s]

    def chunk(x, y):
        return (math.floor(x / CHUNK), math.floor(y / CHUNK))

    def cut(pts):
        """Split a polyline (author metres) into pieces by chunk; each keeps the joint point of the next."""
        out, cur, k = [], [pts[0]], None
        for p, q in zip(pts, pts[1:]):
            kk = chunk((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            if k is None:
                k = kk
            if kk != k:
                out.append((k, cur))
                cur, k = [p], kk
            cur.append(q)
        out.append((k if k is not None else chunk(*pts[0]), cur))
        return [(k, c) for k, c in out if len(c) >= 2]

    cov = lambda p: g.covered(p[0] + origin[0], p[1] + origin[1], 2)   # within two tiles of the map's own

    def runs_in_map(pts):
        out, cur = [], []
        for p in pts:
            if cov(p):
                cur.append(p)
            elif cur:
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    def add_polygon(cls, ring):
        pts = rdp_ring([au(la, lo) for la, lo in ring], 3.0)
        if len(pts) > 700:
            pts = rdp_ring(pts, 8.0)
        if not any(cov(p) for p in pts):
            return
        if a.minimal and abs(area2(pts)) / 2 < 20000.0:
            return                 # a pond is not a shore
        for t in triangulate(pts):
            fills.setdefault(chunk((t[0] + t[2] + t[4]) / 3, (t[1] + t[3] + t[5]) / 3), {}).setdefault(cls, []).extend(t)

    def add_line(cls, flags, width, name, ring):
        pts = rdp([au(la, lo) for la, lo in ring], 2.0)
        for run in runs_in_map(pts):
            if len(run) >= 2:
                for k, c in cut(run):
                    lines.setdefault(k, []).append((cls, flags, width, nid(name), c))

    geom = lambda el: [(p["lat"], p["lon"]) for p in el.get("geometry", [])]
    for (typ, _), el in elements.items():
        t = el.get("tags", {})
        if typ == "node":
            if a.minimal:
                continue
            p = (el["lat"], el["lon"])
            if t.get("place") and t.get("name"):
                x, y = au(*p)
                labels.setdefault(chunk(x, y), []).append((0, PLACE_RANK.get(t["place"], 100), nid(t["name"]), x, y))
            elif t.get("railway") == "station" and t.get("name"):
                x, y = au(*p)
                if g.covered(x + origin[0], y + origin[1], 0):
                    markers.append((t["name"], x + origin[0], y + origin[1]))
                    labels.setdefault(chunk(x, y), []).append((1, 220, nid(t["name"]), x, y))
            continue
        cls = fill_class(t)
        if typ == "way":
            pts = geom(el)
            if len(pts) < 2:
                continue
            if t.get("waterway"):
                if a.minimal and t["waterway"] not in ("river", "canal"):
                    continue       # a stream or a ditch is no limit worth drawing where the real world is only a shore
                add_line(LINE_RIVER, 0, 6.0 if t["waterway"] in ("river", "canal") else 3.0, None, pts)
            elif a.minimal:
                if cls == FILL_WATER and t.get("natural") != "wetland" and pts[0] == pts[-1] and len(pts) >= 4:
                    add_polygon(cls, pts)
            elif t.get("railway"):
                add_line(LINE_RAIL, 0, 4.0, None, pts)
            elif t.get("highway"):
                speed, heavy = parse_speed(t.get("maxspeed")), parse_speed(t.get("maxspeed:hgv"))
                if speed or heavy:      # a street that says its limits (docs/MAP_PACKAGE.md): flags = heavy, width = the limit
                    add_line(LINE_STREET_LIMITS, heavy, float(speed), t.get("name"), pts)
                else:
                    add_line(LINE_STREET, RANK.get(t["highway"], 4), 0.0, t.get("name"), pts)
            elif cls is not None and pts[0] == pts[-1] and len(pts) >= 4:
                add_polygon(cls, pts)
        elif typ == "relation" and t.get("natural") == "water" and cls == FILL_WATER:
            rings, _ = stitch([geom(m) for m in el.get("members", []) if m.get("type") == "way" and m.get("role") == "outer"])
            for r in rings:
                add_polygon(FILL_WATER, r)

    # --- the terrain's contour lines (an option of the package: the city map has a button for them)
    if a.contours > 0:
        import numpy as np
        import relief as real_contours
        n_c = 0
        # the REAL relief of the map's area (heights above sea level), over the rectangle of the map's tiles with two
        # tiles of margin: everywhere in it, whether a tile has splines or streets or not
        bx0, bx1 = (min(xs) - 2) * g.ts, (max(xs) + 3) * g.ts
        by0, by1 = (min(ys) - 2) * g.ts, (max(ys) + 3) * g.ts

        def latlon_world(x, y):
            if hasattr(g, "latlon_arr"):
                return g.latlon_arr(np.asarray(x, float), np.asarray(y, float))
            la, lo = np.empty(len(x)), np.empty(len(x))
            for i, (u, v) in enumerate(zip(x, y)):
                la[i], lo[i] = g.latlon_xy(u, v)
            return la, lo

        for height, index, cpts in real_contours.contours((bx0, bx1, by0, by1), latlon_world, a.contours, step=50.0, cache=os.path.join(a.cache, "dem")):
            rel = [(x - origin[0], y - origin[1]) for x, y in cpts]
            for k, c in cut(rel):
                lines.setdefault(k, []).append((LINE_CONTOUR_INDEX if index else LINE_CONTOUR, 0, float(height), 0xFFFFFFFF, c))
                n_c += 1
        print(n_c, "contour pieces")

    # --- 2. districts: outline, border lines, the box of the name
    regions, border_seen = [], set()
    dist = [] if a.minimal else osm.overpass(osm.region_query(south, west, north, east, a.district_level), a.cache).get("elements", [])
    for el in dist:
        nm = el.get("tags", {}).get("name")
        outer = [[(p["lat"], p["lon"]) for p in m.get("geometry", [])] for m in el.get("members", []) if m.get("type") == "way" and m.get("role") == "outer"]
        rings, rest = stitch(outer)
        for w in outer + rest:
            k = (round(w[0][0], 6), round(w[0][1], 6), round(w[-1][0], 6), round(w[-1][1], 6)) if w else None
            if k and k not in border_seen and len(w) >= 2:
                border_seen.add(k)
                add_line(LINE_BORDER, 0, 3.0, None, w)
        if nm and rings:
            ring = max(rings, key=lambda r: abs(area2([au(*p) for p in r])))
            poly = rdp_ring([au(la, lo) for la, lo in ring], 8.0)
            # the name goes in the part of the district the map's tiles cover
            vis = clip_rect(poly, 0, 0, (max(xs) + 1 - min(xs)) * g.ts, (max(ys) + 1 - min(ys)) * g.ts)
            box = label_box(vis, nm) if len(vis) >= 3 else None
            if box and not g.covered(box[0] + origin[0], box[1] + origin[1], 3):
                box = None          # no tile of the map there: no name in the void
            regions.append((nm, poly, box))
    print(len(regions), "regions")

    # --- 3. bus routes
    routes = {}
    if a.area_name and not a.minimal:
        for el in osm.overpass(route_query(a.area_name), a.cache).get("elements", []):
            t = el.get("tags", {})
            ref = t.get("ref")
            if not ref:
                continue
            ways = [[(p["lat"], p["lon"]) for p in m.get("geometry", [])] for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
            chain = []
            for w in ways:
                if not chain:
                    chain = list(w)
                    continue
                d_end = (w[0][0] - chain[-1][0]) ** 2 + (w[0][1] - chain[-1][1]) ** 2
                d_rev = (w[-1][0] - chain[-1][0]) ** 2 + (w[-1][1] - chain[-1][1]) ** 2
                chain += (w if d_end <= d_rev else w[::-1])
            stops = [(m["lat"], m["lon"]) for m in el.get("members", []) if m.get("type") == "node" and str(m.get("role", "")).startswith("stop") and "lat" in m]
            way = [au(*p) for p in chain]
            # keep the longest run inside the map's tiles
            runs, cur = [], []
            for p in way:
                if g.covered(p[0] + origin[0], p[1] + origin[1], 1):
                    cur.append(p)
                elif cur:
                    runs.append(cur)
                    cur = []
            if cur:
                runs.append(cur)
            if not runs:
                continue
            run = rdp(max(runs, key=len), 2.0)
            km = sum(math.hypot(b[0] - a_[0], b[1] - a_[1]) for a_, b in zip(run, run[1:])) / 1000
            if km < 1.0:
                continue
            st = [au(*p) for p in stops]
            st = [p for p in st if g.covered(p[0] + origin[0], p[1] + origin[1], 1)]
            routes.setdefault(ref, []).append(dict(km=km, stops=st, way=run, name=t.get("name", ""), frm=t.get("from", ""), to=t.get("to", ""), op=t.get("operator", "")))
    print(len(routes), "bus lines")

    # --- 4. write the package
    os.makedirs(a.out, exist_ok=True)
    ox, oy = origin
    bodies = {}
    for k in sorted(set(fills) | set(lines) | set(labels)):
        b = bytearray()
        f = fills.get(k, {})
        b += struct.pack("<I", len(f))
        for cls, tri in sorted(f.items()):
            b += struct.pack("<BI", cls, len(tri) // 6) + struct.pack("<%df" % len(tri), *tri)
        ls = lines.get(k, [])
        b += struct.pack("<I", len(ls))
        for cls, flags, width, name, pts in ls:
            flat = [v for p in pts for v in p]
            b += struct.pack("<BBfII", cls, flags, width, name, len(pts)) + struct.pack("<%df" % len(flat), *flat)
        lb = labels.get(k, [])
        b += struct.pack("<I", len(lb))
        for kind, rank, name, x, y in lb:
            b += struct.pack("<BBIff", kind, rank, name, x, y)
        bodies[k] = bytes(b)
    head = bytearray(b"OMSF") + struct.pack("<I", 1) + struct.pack("<dd", ox, oy)
    allx = [k[0] for k in bodies]
    ally = [k[1] for k in bodies]
    head += struct.pack("<ffff", min(allx) * CHUNK, (max(allx) + 1) * CHUNK, min(ally) * CHUNK, (max(ally) + 1) * CHUNK) + struct.pack("<f", CHUNK)
    head += struct.pack("<I", len(names))
    for n in names:
        e = n.encode("utf-8")
        head += struct.pack("<H", len(e)) + e
    order = sorted(bodies)
    head += struct.pack("<I", len(order))
    pos, idx = len(head) + 20 * len(order), bytearray()
    for k in order:
        idx += struct.pack("<iiQI", k[0], k[1], pos, len(bodies[k]))
        pos += len(bodies[k])
    open(os.path.join(a.out, "surface.oms"), "wb").write(bytes(head) + bytes(idx) + b"".join(bodies[k] for k in order))

    if regions:
        reg = ["# region = name | label x | label y | label box width m | label box height m | polygon x,y x,y ...  (metres of the author's grid)"]
        for nm, poly, box in regions:
            cx, cy, bw, bh = (box[0] + ox, box[1] + oy, box[2], box[3]) if box else (0.0, 0.0, 0.0, 0.0)
            reg.append("region = %s | %.1f | %.1f | %.1f | %.1f | %s" % (nm, cx, cy, bw, bh, " ".join("%.1f,%.1f" % (p[0] + ox, p[1] + oy) for p in poly)))
        open(os.path.join(a.out, "regions.cfg"), "w", encoding="utf-8", newline=chr(10)).write(chr(10).join(reg) + chr(10))
    size = os.path.getsize(os.path.join(a.out, "surface.oms"))
    return dict(chunks=len(bodies), bytes=size, names=len(names), regions=len(regions), origin=(ox, oy))
