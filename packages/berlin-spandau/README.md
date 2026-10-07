# Berlin-Spandau

Package for the stock map **Berlin-Spandau** of OMSI 2, which every owner has.

## What it adds

- **From OpenStreetMap:** water, green areas, woods, sports grounds, built-up land, rivers, rail (drawn in rail colours that stand out from the roads) and district borders (the surface), the
  districts' names (11 districts, shown as a faint watermark), named streets with their speed limits (looked up to say which street
  you are on and what limit it has), stations (9 markers), and the relief as contour lines every metre (real terrain, heights above
  sea level).
- **From the map's own timetable (not from OpenStreetMap):** 48 lines in 58 forms (55 bus, 1 metro, 2 rail), with their eras (the map
  runs from 1989 and has the changes of 1990-94), ways, stops, itineraries and times. Which vehicles are metro and which are
  trains comes from the map's own AI groups (`manifest.cfg`).

## Files

`openomsi-realmap/` holds `manifest.cfg`, `surface.oms`, `regions.cfg`, `markers.cfg`, `lines.lin` and `icons/` (three plain station
pictograms). The format is in [docs/MAP_PACKAGE.md](../../docs/MAP_PACKAGE.md).

## Made with

The scripts that became [tools/mapgen](../../tools/mapgen/) (October 2026), for a map on `[worldcoordinates]`: the tile index puts
the map on the real city (its roads fall on the real streets to a median of 6 m), so everything real is shown as it is
(`--mode exact`). To make it again with the generator: `python mapgen.py --omsi "<OMSI 2>" --map Berlin-Spandau --relief 1 --out out`.

## Licence and credit

OpenStreetMap data (c) OpenStreetMap contributors, ODbL 1.0, see [LICENSE-DATA.md](../../LICENSE-DATA.md). The map Berlin-Spandau is part
of OMSI 2; the lines are worked out from its timetable and nothing of the map's files is included.
