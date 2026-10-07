#!/usr/bin/env python3
"""addrails.py - put the map's OWN railway into a package that has none (or has OpenStreetMap's), and make it stand out.

The railway of an OMSI 2 map is made of splines whose file carries RAIL lanes (kind 2 of a [path]): they are not roads and are
not drawn as roads. A package that leaves them out shows the map's roads and nothing where the tracks run; one that draws them
as an ordinary line lets them pass for streets. This adds them as the railway class of surface.oms (the city map draws it as a
railway) and gives the manifest rail colours that stand out from the roads (amber on the dark map, brown on the light one).

  python addrails.py --omsi "<OMSI 2>" --map Projekt_Szczecin --package path/to/openomsi-realmap [--replace]

--replace drops the rail lines the package had (OpenStreetMap's, which follow the real railway, not the map's).
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ownmap

COLOURS = [("rail", "#f2b84b"), ("rail_edge", "#2b2208"), ("light_rail", "#8a5a00"), ("light_rail_edge", "#fff3d1")]


def set_colours(manifest):
    s = open(manifest, encoding="utf-8").read()
    have = {m.group(1) for m in re.finditer(r"^\s*([a-z_]+)\s*=", s, re.M)}
    add = [f"{k:<15s} = {v}" for k, v in COLOURS if k not in have]
    if add:
        s = s.rstrip("\n") + "\n\n# the railway stands out from the roads: amber on the dark map, brown on the light one\n" + "\n".join(add) + "\n"
        open(manifest, "w", encoding="utf-8", newline="\n").write(s)
    return len(add)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--omsi", required=True)
    ap.add_argument("--map")
    ap.add_argument("--map-dir")
    ap.add_argument("--package", required=True, help="the openomsi-realmap folder")
    ap.add_argument("--replace", action="store_true")
    a = ap.parse_args()
    map_dir = a.map_dir or os.path.join(a.omsi, "Maps", a.map or "")
    manifest = os.path.join(a.package, "manifest.cfg")
    m = re.search(r"^grid\s*=\s*([0-9.]+)", open(manifest, encoding="utf-8").read(), re.M)
    grid = float(m.group(1))
    n = ownmap.add_rails(os.path.join(a.package, "surface.oms"), a.omsi, map_dir, grid, replace=a.replace)
    print(f"{n} pieces of railway; {set_colours(manifest)} colour keys added to the manifest")


if __name__ == "__main__":
    main()
