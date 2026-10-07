#!/usr/bin/env python3
"""locate.py - find where a map is on the real Earth, by comparing it with OpenStreetMap. Automatic.

What the map offers to be compared: the NAMES and places of its stops (Busstops.cfg), its ROADS (every spline of its
tiles), the WAYS of its bus lines. What OpenStreetMap offers: stops, named streets, neighbourhood names, bus routes.
The steps, each one a function that can be read and changed on its own:

  1. a first place:   - a map with [worldcoordinates]: given by its tile index (nothing to compare);
                      - any other map: the stops that have the same name in both (a name used all over the city is
                        thrown out by RANSAC) give a similarity (scale, turn, shift). The search starts at a point the
                        person gives (--at lat,lon) or at the middle of a place they name (--place "city, state, country").
  2. the roads:       the map's roads laid on OpenStreetMap's named streets (iterative closest points, from a wide reach
                      down to a narrow one) correct the similarity: a small error of turn or scale grows with the distance.
  3. the landmarks:   where the map is hundreds of metres or kilometres off, the roads say nothing; the NAMES do:
                        - a stop with the name of a real stop,
                        - a stop named after a street (the stop must lie on that street),
                        - a stop named after a neighbourhood (it must lie near that neighbourhood),
                        - the ways of the map's bus lines on the real routes of the same number.
                      Each is a pair "here on the map / there in the world".
  4. the field:       a smooth local correction (thin-plate spline) through the landmarks and through the offsets the roads
                      still show cell by cell. The whole thing is the calibration: a dict with a, b, tx, ty, lat0, lon0
                      and `field`.
  5. the verdict:     how far the real world had to be bent to meet the map (`bend`), and how well the roads and the
                      streets agree. It decides what the package may carry (see mapgen.py, `choose_mode`).
"""
import math
import re

import numpy as np
from scipy.spatial import cKDTree

import osm
from placement import Field, M_LAT, en_of, m_lon, sim, sim_inv, WorldPlacement
import random


def _log(*a):
    print("  ", *a, flush=True)


# ---------------------------------------------------------------------------------------------------- 1. a first place
def similarity_from_world(wp, tiles, grid):
    """For a map on [worldcoordinates]: the similarity that best matches its tile index to the globe near its middle."""
    xs = [t[0] for t in tiles]
    ys = [t[1] for t in tiles]
    x0, x1 = min(xs) * grid, (max(xs) + 1) * grid
    y0, y1 = min(ys) * grid, (max(ys) + 1) * grid
    pts = [(x, y) for x in np.linspace(x0, x1, 7) for y in np.linspace(y0, y1, 7)]
    ll = [wp.latlon_xy(x, y) for x, y in pts]
    lat0 = sum(p[0] for p in ll) / len(ll)
    lon0 = sum(p[1] for p in ll) / len(ll)
    ml = m_lon(lat0)
    A, B = [], []
    for (x, y), (la, lo) in zip(pts, ll):
        e, n = (lo - lon0) * ml, (la - lat0) * M_LAT
        A += [[x, -y, 1, 0], [y, x, 0, 1]]
        B += [e, n]
    sol, *_ = np.linalg.lstsq(np.array(A, float), np.array(B, float), rcond=None)
    return dict(a=float(sol[0]), b=float(sol[1]), tx=float(sol[2]), ty=float(sol[3]), lat0=lat0, lon0=lon0)


def real_stops(lat, lon, radius_km, cache, box=None):
    """name -> [(lat, lon)] of OpenStreetMap's named stops (bus, tram, platforms, stations) round a point or in a box."""
    s, w, n, e = box or osm.box_around(lat, lon, radius_km)
    out = {}
    for q in (osm.stops_query(s, w, n, e), osm.tram_stops_query(s, w, n, e)):
        for el in osm.overpass(q, cache, pause=3.0).get("elements", []):
            if "lat" in el and el.get("tags", {}).get("name"):
                out.setdefault(osm.norm(el["tags"]["name"]), []).append((el["lat"], el["lon"]))
    return out


def real_places(lat, lon, radius_km, cache, box=None):
    """name -> [(lat, lon)] of OpenStreetMap's neighbourhoods, suburbs, villages."""
    s, w, n, e = box or osm.box_around(lat, lon, radius_km)
    out = {}
    for el in osm.overpass(osm.places_query(s, w, n, e), cache, pause=3.0).get("elements", []):
        if "lat" in el and el.get("tags", {}).get("name"):
            out.setdefault(osm.norm(el["tags"]["name"]), []).append((el["lat"], el["lon"]))
    return out


def _lstsq_sim(pairs):
    A, B = [], []
    for (x, y), (e, n) in pairs:
        A += [[x, -y, 1, 0], [y, x, 0, 1]]
        B += [e, n]
    sol, *_ = np.linalg.lstsq(np.array(A, float), np.array(B, float), rcond=None)
    return sol


def similarity_from_stops(stops, real, lat0, lon0, log=_log):
    """The map's stops against the real ones of the same name: RANSAC similarity, then stop by stop with the nearest real
    stop of the name. `stops`: name -> [(x, y)] (map metres), `real`: name -> [(lat, lon)]."""
    ml = m_lon(lat0)
    mine = {osm.norm(k): v for k, v in stops.items()}
    pairs = []
    for k, ps in mine.items():
        if k in real:
            cx = sum(p[0] for p in ps) / len(ps)
            cy = sum(p[1] for p in ps) / len(ps)
            rl = real[k]
            pairs.append(((cx, cy), (sum((lo - lon0) * ml for _, lo in rl) / len(rl), sum((la - lat0) * M_LAT for la, _ in rl) / len(rl))))
    log(f"{len(mine)} stop names on the map, {len(real)} in OpenStreetMap, {len(pairs)} in both")
    if len(pairs) < 8:
        raise SystemExit("Too few stop names in common to place the map: check --at / --place, or the stops' names")

    def resid(sol, pr):
        (x, y), (e, n) = pr
        return math.hypot(sol[0] * x - sol[1] * y + sol[2] - e, sol[1] * x + sol[0] * y + sol[3] - n)

    best, rnd = None, random.Random(1)
    for _ in range(3000):
        sol = _lstsq_sim(rnd.sample(pairs, 2))
        if not 0.9 < math.hypot(sol[0], sol[1]) < 1.1:        # the map is in metres: the scale is about 1
            continue
        inl = [p for p in pairs if resid(sol, p) < 40.0]
        if best is None or len(inl) > len(best[1]):
            best = (sol, inl)
    sol, inl = best
    for _ in range(4):
        sol = _lstsq_sim(inl)
        inl = [p for p in pairs if resid(sol, p) < 40.0]
    for _ in range(4):                  # stop by stop: each map stop with the nearest real stop of its name, within 70 m
        pr = []
        for k, ps in mine.items():
            for (x, y) in ps:
                e = sol[0] * x - sol[1] * y + sol[2]
                n = sol[1] * x + sol[0] * y + sol[3]
                cand = None
                for la, lo in real.get(k, []):
                    re_, rn = (lo - lon0) * ml, (la - lat0) * M_LAT
                    d = math.hypot(re_ - e, rn - n)
                    if d < 70 and (cand is None or d < cand[0]):
                        cand = (d, re_, rn)
                if cand:
                    pr.append(((x, y), (cand[1], cand[2])))
        if len(pr) < 8:
            break
        sol = _lstsq_sim(pr)
        inl = pr
    res = sorted(resid(sol, p) for p in inl)
    log(f"similarity from {len(inl)} stop pairs: scale {math.hypot(sol[0], sol[1]):.4f}, turn {math.degrees(math.atan2(sol[1], sol[0])):.2f} deg, "
        f"median residual {res[len(res) // 2]:.1f} m, 90% {res[int(len(res) * 0.9)]:.1f} m")
    return dict(a=float(sol[0]), b=float(sol[1]), tx=float(sol[2]), ty=float(sol[3]), lat0=lat0, lon0=lon0, pairs=len(inl))


# ---------------------------------------------------------------------------------------------------- 2. roads on streets
def fetch_streets(cal, game, cache, margin=1800.0, log=_log, sample=None):
    """OpenStreetMap's named streets round the map, as polylines of east/north metres from (lat0, lon0). With `sample` = n only
    the n squares (0.02 degrees) nearest the middle of the map are asked: enough to say how well map and city agree, and light
    on the free servers (a dense city makes a big square too heavy for them)."""
    lo_, hi_ = game.min(0), game.max(0)
    cs = [sim(cal, x, y) for x in (lo_[0], hi_[0]) for y in (lo_[1], hi_[1])]
    ml = m_lon(cal["lat0"])
    s = cal["lat0"] + (min(c[1] for c in cs) - margin) / M_LAT
    n = cal["lat0"] + (max(c[1] for c in cs) + margin) / M_LAT
    w = cal["lon0"] + (min(c[0] for c in cs) - margin) / ml
    e = cal["lon0"] + (max(c[0] for c in cs) + margin) / ml
    streets = []
    size = 0.02 if sample else 0.04
    squares = [(la, lo) for la in np.arange(math.floor(s / size) * size, n, size) for lo in np.arange(math.floor(w / size) * size, e, size)]
    if sample:                                                      # the squares nearest the middle of the map
        ce, cn = sim(cal, *game.mean(0))
        mid_lat, mid_lon = cal["lat0"] + cn / M_LAT, cal["lon0"] + ce / ml
        squares.sort(key=lambda q: (q[0] + size / 2 - mid_lat) ** 2 + ((q[1] + size / 2 - mid_lon) * 0.6) ** 2)
        squares = squares[:sample]
    for la, lo in squares:                                          # squares on a fixed grid: the answers are kept
        q = osm.streets_query(la, lo, la + size, lo + size)
        for el in osm.overpass(q, cache, pause=4.0, fatal=not sample).get("elements", []):
            g = el.get("geometry") or []
            if len(g) >= 2:
                streets.append((osm.norm(el.get("tags", {}).get("name", "")), [((p["lon"] - cal["lon0"]) * ml, (p["lat"] - cal["lat0"]) * M_LAT) for p in g]))
    log(f"{len(streets)} named streets" + (f" (a sample of {len(squares)} squares)" if sample else ""))
    return streets, (s, w, n, e)


def densify(polylines, step):
    out = []
    for st in polylines:
        for (ax, ay), (bx, by) in zip(st, st[1:]):
            k = max(1, int(math.hypot(bx - ax, by - ay) / step))
            for j in range(k):
                out.append((ax + (bx - ax) * j / k, ay + (by - ay) * j / k))
    return np.array(out)


def icp(cal, game, dense, log=_log):
    """The similarity corrected by the whole road network: map roads to the nearest street, fit, narrow the reach."""
    tree = cKDTree(dense)
    for reach in (400.0, 250.0, 160.0, 100.0, 70.0, 50.0, 40.0, 40.0):
        q = en_of(cal, game)
        d, i = tree.query(q, k=1, distance_upper_bound=reach)
        ok = np.isfinite(d)
        if ok.sum() < 200:
            break
        z = q[ok, 0] + 1j * q[ok, 1]
        w = dense[i[ok], 0] + 1j * dense[i[ok], 1]
        zc, wc = z.mean(), w.mean()
        c = np.sum(np.conj(z - zc) * (w - wc)) / np.sum(np.abs(z - zc) ** 2)
        dd = wc - c * zc
        A = (cal["a"] + 1j * cal["b"]) * c
        T = (cal["tx"] + 1j * cal["ty"]) * c + dd
        cal.update(a=float(A.real), b=float(A.imag), tx=float(T.real), ty=float(T.imag))
    d, _ = tree.query(en_of(cal, game), k=1, distance_upper_bound=60.0)
    ok = np.isfinite(d)
    log(f"roads on streets (similarity only): median {np.median(d[ok]):.1f} m, {ok.mean() * 100:.0f}% of the road points within 60 m of a street")
    return cal


# ---------------------------------------------------------------------------------------------------- 3. landmarks
def _segments_nearest(poly_en, e0, n0):
    """The nearest point of a polyline to (e0, n0) -> (distance, e, n)."""
    best = None
    for (ax, ay), (bx, by) in zip(poly_en, poly_en[1:]):
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        u = 0.0 if d2 == 0 else max(0.0, min(1.0, ((e0 - ax) * dx + (n0 - ay) * dy) / d2))
        px, py = ax + u * dx, ay + u * dy
        d = math.hypot(px - e0, py - n0)
        if best is None or d < best[0]:
            best = (d, px, py)
    return best



def _street_polys(by_street, k):
    """The ways of the streets a stop name can mean: the street with exactly that name, else the streets whose name ENDS with
    it ("Niemcewicza" for "Juliana Ursyna Niemcewicza"), as long as they are one street (not another one that shares the end)."""
    if k in by_street:
        return by_street[k]
    names = [n for n in by_street if n.endswith(" " + k)]
    return [p for n in names for p in by_street[n]] if 0 < len(names) <= 2 else []


def _spread(polys):
    """How far apart the ways of a street lie (m): a name used in two parts of a city is no landmark."""
    pts = np.array([p[0] for p in polys])
    return float(np.hypot(*(pts.max(0) - pts.min(0)))) if len(pts) > 1 else 0.0


def landmarks(cal, stops, real, places, streets, log=_log):
    """[[x, y, dx, dy]]: where a stop is on the map and how far (map metres) it must move to be where its name says."""
    ml = m_lon(cal["lat0"])
    marks = []
    by_street = {}
    for name, poly in streets:
        by_street.setdefault(name, []).append(poly)
    n_stop = n_street = n_place = 0
    for name, ps in stops.items():
        k = osm.norm(name)
        for (x, y) in ps:
            e0, n0 = sim(cal, x, y)
            best = None
            for la, lo in real.get(k, []):                                  # a stop of the same name
                re_, rn = (lo - cal["lon0"]) * ml, (la - cal["lat0"]) * M_LAT
                dd = math.hypot(re_ - e0, rn - n0)
                if dd < 7000 and (best is None or dd < best[0]):
                    best = (dd, re_, rn)
            if best:
                n_stop += 1
            elif len(k) >= 5 and _street_polys(by_street, k):                  # a stop named after a street
                polys = _street_polys(by_street, k)
                cand = [c for c in (_segments_nearest(p, e0, n0) for p in polys) if c]
                if cand and _spread(polys) < 8000:
                    c = min(cand)
                    if c[0] < 2500:
                        best = c
                        n_street += 1
            else:                                                            # a stop named after a neighbourhood
                for pn, pl in places.items():
                    if len(pn) >= 5 and len(pl) <= 2 and re.search(rf"\b{re.escape(pn)}\b", k):
                        re_, rn = (pl[0][1] - cal["lon0"]) * ml, (pl[0][0] - cal["lat0"]) * M_LAT
                        dd = math.hypot(re_ - e0, rn - n0)
                        if dd < 3000:
                            best = (dd, re_, rn)
                            n_place += 1
                            break
            if best:
                tx_, ty_ = sim_inv(cal, best[1], best[2])
                marks.append([x, y, tx_ - x, ty_ - y])
    marks = np.array(marks).reshape(-1, 4)
    if len(marks) >= 6:       # a mark that disagrees with its neighbours by more than 400 m is a name used elsewhere
        keep = []
        for k, m in enumerate(marks):
            dist = np.hypot(marks[:, 0] - m[0], marks[:, 1] - m[1])
            near = np.argsort(dist)[1:6]
            med = np.median(marks[near, 2:], axis=0)
            if np.hypot(*(m[2:] - med)) < 400:
                keep.append(k)
        marks = marks[keep]
    log(f"landmarks: {n_stop} stops by name, {n_street} by street name, {n_place} by neighbourhood; {len(marks)} kept")
    return marks


def route_landmarks(cal, ways, pre_marks, bbox, cache, log=_log):
    """The ways of the map's bus lines against OpenStreetMap's routes of the same number: a mark every 60 m."""
    refs = sorted({n for n, _ in ways})
    if not refs:
        return np.zeros((0, 4))
    ml = m_lon(cal["lat0"])
    rel = osm.overpass(osm.routes_query(refs, *bbox), cache, pause=4.0).get("elements", [])
    route_pts = {}
    for el in rel:
        rref = el.get("tags", {}).get("ref", "")
        for m in el.get("members", []):
            g = m.get("geometry") or []
            for p1, p2 in zip(g, g[1:]):
                ax, ay = (p1["lon"] - cal["lon0"]) * ml, (p1["lat"] - cal["lat0"]) * M_LAT
                bx, by = (p2["lon"] - cal["lon0"]) * ml, (p2["lat"] - cal["lat0"]) * M_LAT
                k = max(1, int(math.hypot(bx - ax, by - ay) / 15.0))
                for j in range(k):
                    route_pts.setdefault(rref, []).append((ax + (bx - ax) * j / k, ay + (by - ay) * j / k))
    pre = Field(pre_marks) if len(pre_marks) >= 4 else None
    extra = []
    for number, v in ways:
        if number not in route_pts:
            continue
        rt = cKDTree(np.array(route_pts[number]))
        dv = densify([v], 60.0)
        if len(dv) == 0:
            continue
        dx, dy = pre(dv[:, 0], dv[:, 1]) if pre else (np.zeros(len(dv)), np.zeros(len(dv)))
        e_, n_ = sim(cal, dv[:, 0] + dx, dv[:, 1] + dy)
        dist, idx = rt.query(np.column_stack([e_, n_]), distance_upper_bound=700.0)
        for k2 in np.where(np.isfinite(dist))[0]:
            qe, qn = route_pts[number][idx[k2]]
            tx_, ty_ = sim_inv(cal, qe, qn)
            extra.append([dv[k2, 0], dv[k2, 1], tx_ - dv[k2, 0], ty_ - dv[k2, 1]])
    log(f"{len(rel)} real bus routes; {len(extra)} marks along the map's lines")
    return np.array(extra).reshape(-1, 4)


# ---------------------------------------------------------------------------------------------------- 4. the field
def fit_field(cal, game, dense, marks, cell=400.0, min_pts=25, rounds=4, log=_log):
    """The smooth local correction. Each round: lay the map's roads on the streets with the field so far, take the median
    offset still left in each cell, and rebuild the field through those and the landmarks far from every cell."""
    # the streets in the map's frame (the similarity undone)
    z = dense[:, 0] + 1j * dense[:, 1]
    det = cal["a"] ** 2 + cal["b"] ** 2
    zz = z - (cal["tx"] + 1j * cal["ty"])
    w = zz * np.conj(cal["a"] + 1j * cal["b"]) / det
    ref = np.column_stack([w.real, w.imag])
    tree = cKDTree(ref)

    def residual(field):
        dx, dy = field(game[:, 0], game[:, 1])
        p = game + np.column_stack([dx, dy])
        d, i = tree.query(p, k=1, distance_upper_bound=60.0)
        return p, d, i, np.isfinite(d)

    # one mark for each 250 m cell
    cells = {}
    for m in marks:
        cells.setdefault((int(m[0] // 250), int(m[1] // 250)), []).append(m)
    marks = np.array([np.median(v, axis=0) for v in cells.values()]).reshape(-1, 4)
    pts_field = [list(m) for m in marks]
    field = Field(pts_field)
    for rnd in range(rounds):
        p, d, i, ok = residual(field)
        off = ref[i[ok]] - p[ok]
        cl = np.floor(game[ok] / cell).astype(int)
        buckets = {}
        for k, c in enumerate(map(tuple, cl)):
            buckets.setdefault(c, []).append(k)
        new = []
        for c, ks in buckets.items():
            if len(ks) < min_pts:
                continue
            m = np.median(off[ks], axis=0)
            centre = game[ok][ks].mean(0)
            dx, dy = field(np.array([centre[0]]), np.array([centre[1]]))
            new.append([centre[0], centre[1], float(dx[0] + m[0]), float(dy[0] + m[1])])
        if not new:
            break
        cell_xy = np.array([[c[0], c[1]] for c in new])
        for m in marks:                     # landmarks far from every cell stay as they are
            if np.min(np.hypot(cell_xy[:, 0] - m[0], cell_xy[:, 1] - m[1])) > 500.0:
                new.append(list(m))
        field = Field(new)
        pts_field = new
    p, d, i, ok = residual(field)
    if ok.any():
        log(f"field of {len(pts_field)} control points: roads within 60 m of a street {ok.mean() * 100:.0f}%, median {np.median(d[ok]):.1f} m, 90% {np.percentile(d[ok], 90):.1f} m")
    cal["field"] = [[round(float(v), 2) for v in r] for r in pts_field]
    return cal


def bend(cal, game):
    """How far the field moves the road points (metres): [median, 90%, max]."""
    if not cal.get("field"):
        return [0.0, 0.0, 0.0]
    dx, dy = Field(cal["field"])(game[:, 0], game[:, 1])
    m = np.hypot(dx, dy)
    return [float(np.median(m)), float(np.percentile(m, 90)), float(m.max())]


def street_agreement(cal, game, dense, with_field=True):
    """Roads against streets: (median distance of the points within 60 m, share of points within 60 m, 90% distance)."""
    g = game
    if with_field and cal.get("field"):
        dx, dy = Field(cal["field"])(game[:, 0], game[:, 1])
        g = game + np.column_stack([dx, dy])
    d, _ = cKDTree(dense).query(en_of(cal, g), k=1, distance_upper_bound=60.0)
    ok = np.isfinite(d)
    if not ok.any():
        return 999.0, 0.0, 999.0
    return float(np.median(d[ok])), float(ok.mean()), float(np.percentile(d[ok], 90))


# ---------------------------------------------------------------------------------------------------- the whole step
def locate(stops, game, ways, cache, world=None, hint=None, refine=True, log=_log, early_exact=None):
    """Returns (calibration dict, report dict).

    stops: name -> [(x, y)];  game: array of the map's road points;  ways: [(line number, array of way points)];
    world: (WorldPlacement, tiles, grid) for a map with [worldcoordinates];  hint: dict(lat, lon, box, radius_km) otherwise."""
    if world:
        wp, tiles, grid = world
        cal = similarity_from_world(wp, tiles, grid)
        log(f"[worldcoordinates]: the map's place is given; middle at {cal['lat0']:.4f}, {cal['lon0']:.4f}")
        box = None
        radius = 26.0
    else:
        if not hint:
            raise SystemExit("This map has no [worldcoordinates]: say where it is with --at LAT,LON (a point in the region) or --place \"city, state, country\"")
        radius = hint.get("radius_km", 22.0)
        box = hint.get("box")
        real0 = real_stops(hint["lat"], hint["lon"], radius, cache, box)
        cal = similarity_from_stops(stops, real0, hint["lat"], hint["lon"], log)
    report = dict(world=bool(world))
    if world and early_exact:
        # a map on [worldcoordinates] that already fits needs no more than a sample of the streets to say so
        streets, bbox = fetch_streets(cal, game, cache, log=log, sample=6)
        if len(streets) >= 50:
            dense = densify([p for _, p in streets], 8.0)
            med, cover, p90 = street_agreement(cal, game, dense, with_field=False)
            log(f"sample: roads on streets with the tile index alone: median {med:.1f} m, 90% {p90:.1f} m, {cover * 100:.0f}% within 60 m")
            if early_exact(med, p90, cover):
                report.update(similarity_median=med, similarity_cover=cover, similarity_p90=p90, stop_pairs=0)
                report["streets"] = (streets, dense, bbox)
                return cal, report
    real = real_stops(cal["lat0"], cal["lon0"], 26.0, cache)
    streets, bbox = fetch_streets(cal, game, cache, log=log)
    dense = densify([p for _, p in streets], 8.0)
    cal = icp(cal, game, dense, log)
    med, cover, p90 = street_agreement(cal, game, dense, with_field=False)
    report.update(similarity_median=med, similarity_cover=cover, similarity_p90=p90, stop_pairs=cal.get("pairs", 0))
    if refine:
        places = real_places(cal["lat0"], cal["lon0"], 26.0, cache)
        marks = landmarks(cal, stops, real, places, streets, log)
        extra = route_landmarks(cal, ways, marks, bbox, cache, log)
        if len(extra):
            marks = np.vstack([marks, extra]) if len(marks) else extra
        cal = fit_field(cal, game, dense, marks, log=log)
        report["bend"] = bend(cal, game)
        report["landmarks"] = len(marks)
        med2, cover2, p902 = street_agreement(cal, game, dense, with_field=True)
        report.update(field_median=med2, field_cover=cover2, field_p90=p902)
        log(f"the real world had to be bent by {report['bend'][0]:.0f} m (median), {report['bend'][1]:.0f} m (90%), {report['bend'][2]:.0f} m (most)")
    report["streets"] = (streets, dense, bbox)
    return cal, report
