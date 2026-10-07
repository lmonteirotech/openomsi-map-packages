# Projekt Szczecin

Package for the map **Projekt Szczecin 4.0.1**, a community map for OMSI 2 (credit to its authors: see the readme that comes with
the map).

## What it adds

- **The shore, from OpenStreetMap:** the large water areas (2 ha or more) and the rivers and canals of the real Szczecin, placed by
  **north** (172.2 degrees: the map is drawn turned) and position. The map is not aligned with reality (to meet it the real city would
  have to be bent by kilometres in places), so the package does **not** carry the real streets, blocks, districts or relief: only
  the shore, set so that **no road of the map lies in the water** (checked against every road of the map).
- **The railway, from the map itself:** the map's own rail splines (the ones that carry rail lanes: 613 pieces, tram and railway) are in the surface as the railway, which the city map draws as a railway and not as a road, in rail colours that stand out from the roads (amber on the dark map, brown on the light one; see `manifest.cfg`).
- **From the map's own timetable (not from OpenStreetMap):** 28 lines (22 bus, 6 tram, the tram network from the map's own `_tram`
  timetable files) with their ways on the map's own roads, stops with their names, itineraries and times. The stops and the roads are
  the map's, whatever the real city looks like.

## Files

`openomsi-realmap/` holds `manifest.cfg` (north, `alignment = fitted`, the tram vehicle kind, the rail colours), `surface.oms` (44 KB: the shore and the railway) and `lines.lin`.
The format is in [docs/MAP_PACKAGE.md](../../docs/MAP_PACKAGE.md).

## Made with

The scripts that became [tools/mapgen](../../tools/mapgen/) (October 2026), for a map without `[worldcoordinates]`: the place of the map
was found by comparing the names of its stops and streets and its bus routes with OpenStreetMap, and the generator chose the shore-only
profile (`--mode shore`) because the real city had to be bent by 3.3 km (90% of the roads) to meet the map. To make it again:
`python mapgen.py --omsi "<OMSI 2>" --map Projekt_Szczecin --at 53.43,14.55 --timetables "<the unpacked tram timetable folder>" --out out`.

## Licence and credit

Shore data (c) OpenStreetMap contributors, ODbL 1.0, see [LICENSE-DATA.md](../../LICENSE-DATA.md). The map Projekt Szczecin and its
timetables belong to the map's authors: the lines in `lines.lin` are worked out from the map's timetable and nothing of the map's
files (tiles, textures, models, scripts) is included. Credit the map and its authors when you share this package.
