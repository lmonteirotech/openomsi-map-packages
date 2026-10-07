#!/usr/bin/env python3
"""mapgen.py - makes an openOMSI map package (docs/MAP_PACKAGE.md) for ANY OMSI 2 map, in one run.

    python mapgen.py --omsi "C:/Games/OMSI 2" --map "Projekt_Szczecin" --at 53.43,14.55 --out ./out

You point at the OMSI 2 folder and the map; if the map has no [worldcoordinates] you say where it is (a point of the region
with --at LAT,LON, or the place with --place "city, state, country"); more timetables can be added (--timetables). The rest
is automatic, in this order (each step is a function you can read and change):

  1. read the map              its tiles, its grid, whether it is on [worldcoordinates]
  2. the map's own lines       from its timetables and eras: stops, ways, itineraries, times   (omsimap.py)
  3. locate the map            by comparing stop names, street names, neighbourhood names and bus routes with
                               OpenStreetMap, and the map's roads with its streets             (locate.py)
  4. choose how far to go      --mode auto decides from how well the map and the real city agree:
                                 exact    the map IS the city (a [worldcoordinates] map that fits): all real layers, as they are
                                 fitted   the map is the city, a little bent: all real layers, bent to the map's own roads
                                 shore    the map is not the city (out of proportion): only north and the SHORE (water areas,
                                          rivers); every road, stop, line and time is the map's own; no road in water
                                 own      no OpenStreetMap at all (a fictional map, or by choice): the map's own tiles are
                                          measured - woods, buildings, water, sports grounds, rails, relief (ownmap.py)
  5. the real layers           from OpenStreetMap, laid on the map                             (surface.py, relief.py)
  6. check and write           manifest, icons, REPORT.md; the rules are checked                (check.py)

Everything it downloads is kept in --cache (a second run asks for nothing). Needs Python 3.9+, numpy, scipy, Pillow
(and contourpy with --relief).  pip install numpy scipy pillow contourpy
Data from OpenStreetMap (c) its contributors, ODbL: the credit goes in the manifest.
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check
import icons
import locate
import omsimap
import osm
import ownmap
import placement
import surface

# --- what "agree" means: edit here -------------------------------------------------------------------------------
EXACT_MEDIAN = 15.0     # metres: roads on streets with the tile index alone (similarity), median ...
EXACT_P90 = 50.0        # ... and 90%
MIN_COVER = 0.6         # share of road points that have a street within 60 m
FITTED_BEND_P90 = 120.0  # metres: the real world may be bent this much (90% of the roads) and still be shown whole
WATER_MARGIN = 16.0     # metres: no road nearer to water than this in a shore package


def step(n, text):
    print(f"\n[{n}/6] {text}", flush=True)


def read_ways(lines_path):
    """[(line number, array of way points)] of the bus lines of a lines.lin (map metres)."""
    org = np.zeros(2)
    number, ways = None, []
    for l in open(lines_path, encoding="utf-8").read().split("\n"):
        f = l.split("\t")
        if f[0] == "ORIGEM":
            org = np.array([float(f[1]), float(f[2])])
        elif f[0] == "L":
            number = f[1].strip() if len(f) > 4 and f[4] == "bus" else None
        elif f[0] == "P" and number and len(f) > 1:
            ways.append((number, np.array([float(t) for t in f[1].split()]).reshape(-1, 2) + org))
    return ways


def choose_mode(world, rep):
    """exact | fitted | shore, and why."""
    if world and rep["similarity_median"] <= EXACT_MEDIAN and rep["similarity_p90"] <= EXACT_P90 and rep["similarity_cover"] >= MIN_COVER:
        return "exact", f"the tile index alone puts the roads on the streets (median {rep['similarity_median']:.0f} m)"
    bend = rep.get("bend", [0, 0, 0])
    if rep.get("field_cover", 0) >= MIN_COVER and bend[1] <= FITTED_BEND_P90:
        return "fitted", f"a smooth correction of {bend[1]:.0f} m (90%) puts the roads on the streets"
    return "shore", f"the real city had to be bent by {bend[1]:.0f} m (90%), up to {bend[2]:.0f} m: only north and shore can be trusted"


def write_manifest(path, name, grid, mode, north, credit_extra):
    credit = {"own": "made from the map's own data", "exact": "(c) OpenStreetMap contributors (ODbL)",
              "fitted": "(c) OpenStreetMap contributors (ODbL) - the real world is fitted to this map, not exact",
              "shore": "(c) OpenStreetMap contributors (ODbL) - only the shore and the rivers are real, placed by north and position: not exact"}[mode]
    lines = ["# openOMSI map package (docs/MAP_PACKAGE.md), made by mapgen", "format    = 1", f"name      = {name}",
             "# the tile size of the map in metres", f"grid      = {grid:.3f}", f"credit    = {credit}", ""]
    if mode not in ("exact", "own"):
        lines += ["# the map is not aligned with reality: " + ("the real layers are bent to the map's own roads" if mode == "fitted" else
                  "the roads, stops, routes and timetables are the map's own; only the main water is real, set by north, scale and position"),
                  "alignment   = fitted"]
    lines += ["", "# the railway stands out from the roads: amber on the dark map, brown on the light one", "rail            = #f2b84b", "rail_edge       = #2b2208",
              "light_rail      = #8a5a00", "light_rail_edge = #fff3d1"]
    lines += ["", "player      = triangle", "# real north lies this many degrees clockwise from the map's own up (the map is turned in the editor)",
              f"north       = {north:.1f}", "player_free = #ffffff", "player_line = #5588c7", "player_brt  = #1e7b34"]
    if credit_extra:
        lines += [credit_extra]
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--omsi", required=True, help="the OMSI 2 folder (the one with Maps, Vehicles, ...)")
    ap.add_argument("--map", help="the map's folder name under Maps (e.g. Projekt_Szczecin)")
    ap.add_argument("--map-dir", help="or the map's folder itself")
    ap.add_argument("--out", required=True, help="where the package goes (it becomes the openomsi-realmap folder)")
    ap.add_argument("--timetables", action="append", default=[], help="a folder of more timetable files of the map (repeat for several), e.g. an unpacked tram network")
    ap.add_argument("--at", help="LAT,LON of a point in the map's region (a map without [worldcoordinates])")
    ap.add_argument("--place", help='the place, written as a person would: "Szczecin, West Pomeranian, Poland"')
    ap.add_argument("--radius", type=float, default=22.0, help="km round --at / --place where the stops are looked for")
    ap.add_argument("--mode", default="auto", choices=["auto", "exact", "fitted", "shore", "own"])
    ap.add_argument("--relief", type=float, default=0.0, help="contour lines of the real terrain every this many metres (fitted/exact only); 0: none")
    ap.add_argument("--north", type=float, default=0.0, help="mode own: degrees clockwise from the map's up to real north (0 for a fictional map)")
    ap.add_argument("--terrain-offset", type=float, default=0.0, help="mode own: metres to add to the map's heights to get heights above sea level")
    ap.add_argument("--grid", type=float, help="the map's tile size in metres (default: from [worldcoordinates], else 300)")
    ap.add_argument("--min-splines", type=int, help="a tile counts as the map with this many splines (default 3 on a world map, else 1)")
    ap.add_argument("--no-eras", action="store_true", help="ignore the Chrono folders (eras) of the map")
    ap.add_argument("--name", help="the map's name for the manifest")
    ap.add_argument("--cache", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache"), help="where downloads are kept")
    a = ap.parse_args()
    t0 = time.time()

    # 1 ---------------------------------------------------------------------------------------------------
    step(1, "reading the map")
    map_dir = a.map_dir or os.path.join(a.omsi, "Maps", a.map or "")
    if not os.path.isfile(os.path.join(map_dir, "global.cfg")):
        raise SystemExit(f"No global.cfg in {map_dir}: check --omsi and --map")
    all_tiles, world = placement.read_global(os.path.join(map_dir, "global.cfg"))
    grid = a.grid or (placement.tile_size([t[1] for t in all_tiles]) if world else 300.0)
    name = a.name or os.path.basename(os.path.normpath(map_dir)).replace("_", " ")
    print(f"  {name}: {len(all_tiles)} tiles, grid {grid:.3f} m, {'[worldcoordinates]' if world else 'no [worldcoordinates]'}")

    def count_splines(t):
        f = os.path.join(map_dir, f"tile_{t[0]}_{t[1]}.map")
        try:
            raw = open(f, "rb").read()
        except OSError:
            return 0
        txt = raw.decode("utf-16", "replace") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("cp1252", "replace")
        return txt.count("[spline]") + txt.count("[spline_h]")
    need = a.min_splines if a.min_splines is not None else (3 if world else 1)
    tiles = [t for t in all_tiles if count_splines(t) >= need]
    print(f"  {len(tiles)} of {len(all_tiles)} tiles have {need} splines or more: those are the map")

    # 2 ---------------------------------------------------------------------------------------------------
    step(2, "the map's own lines (timetables, eras, ways)")
    os.makedirs(a.out, exist_ok=True)
    layers, chronos = omsimap.read_timetables(map_dir, a.timetables, not a.no_eras)
    geo = omsimap.all_geometry(a.omsi, map_dir, grid)
    manifest_tmp = os.path.join(a.out, "manifest.cfg")
    write_manifest(manifest_tmp, name, grid, "exact", 0.0, "")          # (rewritten at the end: the vehicle keys go in it now)
    ln = omsimap.build_lines(a.omsi, map_dir, grid, a.out, manifest=manifest_tmp, geo=geo, layers=layers, chronos=chronos)
    print(f"  {ln['lines']} lines in {ln['forms']} forms {ln['by_modal']}, {ln['stations']} stations; jumps over 300 m: {len(ln['jumps'])}")
    stops = omsimap.stop_positions(layers + chronos, geo)
    game = np.array(omsimap.road_samples(geo, 12.0))
    print(f"  {len(stops)} stop names, {len(game)} road points")
    ways = read_ways(os.path.join(a.out, "lines.lin"))

    # 3 ---------------------------------------------------------------------------------------------------
    step(3, "locating the map on the Earth (OpenStreetMap)")
    hint = None
    own = a.mode == "own" or (a.mode == "auto" and not world and not (a.at or a.place))
    if own:
        print("  skipped: " + ("--mode own" if a.mode == "own" else "no --at / --place given for a map without [worldcoordinates]") + ": the package is made from the map's own tiles")
    if a.at:
        lat, lon = (float(v) for v in a.at.split(","))
        hint = dict(lat=lat, lon=lon, radius_km=a.radius)
    elif a.place:
        lat, lon, box, shown = osm.geocode(a.place, a.cache)
        print(f"  {a.place!r} is {shown} ({lat:.4f}, {lon:.4f})")
        hint = dict(lat=lat, lon=lon, radius_km=a.radius)
    wp = placement.WorldPlacement(tiles, all_tiles) if world else None
    if own:
        cal, rep = {}, {}
    else:
        early = (lambda m, p, c: m <= EXACT_MEDIAN and p <= EXACT_P90 and c >= MIN_COVER) if a.mode == "auto" else None
        if a.mode == "exact" and world:       # asked for: nothing to compare
            cal, rep = locate.similarity_from_world(wp, tiles, grid), dict(similarity_median=0.0, similarity_p90=0.0, similarity_cover=1.0, stop_pairs=0)
        else:
            cal, rep = locate.locate(stops, game, ways, a.cache, world=(wp, tiles, grid) if world else None, hint=hint, early_exact=early)
            rep.pop("streets")

    # 4 ---------------------------------------------------------------------------------------------------
    step(4, "choosing how far to go")
    if own:
        mode, why = "own", "no OpenStreetMap: the map's own tiles are measured"
    elif a.mode == "auto":
        mode, why = choose_mode(world, rep)
    else:
        mode, why = a.mode, "asked for"
        if mode == "exact" and not world:
            raise SystemExit("--mode exact needs a map with [worldcoordinates]")
    print(f"  mode: {mode} ({why})")
    if mode == "own":
        g, north = None, a.north
    elif mode == "exact":
        g = wp
        north = 0.0
    else:
        g = placement.FittedPlacement(set(tiles), grid, cal)
        north = math.degrees(math.atan2(cal["b"], cal["a"])) % 360.0

    # 5 ---------------------------------------------------------------------------------------------------
    step(5, "the map's own tiles" if mode == "own" else "the real layers from OpenStreetMap" + (" (shore only)" if mode == "shore" else ""))
    if mode == "own":
        surf = ownmap.build_own_surface(map_dir, grid, tiles, a.out, relief=a.relief, omsi=a.omsi)
    else:
        surf = surface.build_surface(g, tiles, a.out, a.cache, profile="shore" if mode == "shore" else "full",
                                     contours=0.0 if mode == "shore" else a.relief)
    if mode in ("shore", "fitted"):
        # the railway is the map's own: its splines carry rail lanes. Drawn as a railway (class 1), not left to look like a road
        ownmap.add_rails(os.path.join(a.out, "surface.oms"), a.omsi, map_dir, grid, replace=True)
    print(f"  surface.oms: {os.path.getsize(os.path.join(a.out, 'surface.oms')) / 1e6:.2f} MB")

    # 6 ---------------------------------------------------------------------------------------------------
    step(6, "checking and writing")
    spath = os.path.join(a.out, "surface.oms")
    wat = check.roads_vs_water(spath, game, WATER_MARGIN)
    carved = 0
    if mode == "shore" and (wat[0] or wat[1]):
        carved = check.carve_water(spath, game, WATER_MARGIN)
        wat = check.roads_vs_water(spath, game, WATER_MARGIN)
    print(f"  roads in water: {wat[0]}, within {WATER_MARGIN:.0f} m of it: {wat[1]} (of {wat[2]} road points)" + (f"; water trimmed ({carved} triangles)" if carved else ""))
    extra = f"terrain_offset = {a.terrain_offset:g}" if mode == "own" and a.terrain_offset else ""
    write_manifest(manifest_tmp, name, grid, mode, north, extra)
    omsimap.set_manifest_keys(manifest_tmp, {"tram_vehicles": ln["vehicles"]["tram"], "metro_vehicles": ln["vehicles"]["metro"], "rail_vehicles": ln["vehicles"]["rail"]})
    if os.path.isfile(os.path.join(a.out, "markers.cfg")):
        icons.make_icons(os.path.join(a.out, "icons"))
    info = dict(name=name, mode=mode, why=why, grid=grid, north=north, lines=ln, water=wat, carved=carved,
                placement="the map's own metres (no place on the Earth)" if mode == "own" else "[worldcoordinates]" if mode == "exact" else f"similarity + local field of {len(cal.get('field', []))} points, middle at {cal['lat0']:.4f}, {cal['lon0']:.4f}",
                locate=rep)
    open(os.path.join(a.out, "REPORT.md"), "w", encoding="utf-8", newline="\n").write(check.report_text(info))
    ok = (mode != "shore") or (wat[0] == 0 and wat[1] == 0)
    print(f"\nDone in {time.time() - t0:.0f} s: {a.out}  ({'rules OK' if ok else 'RULE BROKEN: see REPORT.md'})")
    print("Copy the folder to <OMSI 2 or openOMSI content folder>/Maps/<map>/openomsi-realmap/")


if __name__ == "__main__":
    main()
