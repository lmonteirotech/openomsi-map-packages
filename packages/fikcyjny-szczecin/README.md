# Fikcyjny Szczecin

Package for the map **Fikcyjny Szczecin** (Fictional Szczecin, version 2.50.02, 18.07.2016) by **MrYanke$**, a community map for OMSI 2 that is
**made up**: it follows no real place, so nothing here comes from OpenStreetMap.

## What it adds

- **Made from the map's own tiles** (mode `own`, no OpenStreetMap): woods (70,425 objects, 2,030 ha), grassland, farmland, built-up land
  (2,118 buildings drawn with their own outline, taken from their meshes), sports grounds, the map's own water courses and its railway
  (1,784 rail pieces), and 4,590 street splines as the street lines.
- **Relief:** contour lines every 5 m, from the map's own ground (1,157 pieces). The ground of the map is mostly flat, so the lines are few
  and the heights are the map's own (0 m is its base level), not heights above the real sea level.
- **From the map's own timetable:** 40 bus lines with their ways on the map's own roads, stops with their names, itineraries and times.

## Files

`openomsi-realmap/` holds `manifest.cfg`, `surface.oms` (1.3 MB) and `lines.lin`. The format is in [docs/MAP_PACKAGE.md](../../docs/MAP_PACKAGE.md).
`REPORT.md` is what the generator wrote about the run (what was found, the mode, the checks).

## Made with

[tools/mapgen](../../tools/mapgen/), mode `own` with the relief on. To make it again:
`python mapgen.py --omsi "<folder with Maps and Vehicles>" --map-dir "<...>/Maps/Fikcyjny Szczecin" --mode own --relief 5 --name "Fikcyjny Szczecin" --out out`.

![Fikcyjny Szczecin in the city map of openOMSI](../../docs/images/fikcyjny-szczecin/city-map.jpg)

![Fikcyjny Szczecin with the relief on](../../docs/images/fikcyjny-szczecin/relief.jpg)

## Licence and credit

No data from OpenStreetMap is in this package. The map Fikcyjny Szczecin and its timetables belong to **MrYanke$** (MrYankess) and to
the people he thanks; the lines in `lines.lin` are worked out from the map's timetable and **nothing of the map's files** (tiles, textures,
models, scripts) is included, so the map itself is not modified. Credit the map and its authors when you share this package: see
[CREDITS.md](../../CREDITS.md). The map's own readme allows it to be published on www.Strefa-OMSI.pl and www.omnibussimulator.de.
