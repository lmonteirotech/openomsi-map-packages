# mapgen: a map package for any OMSI 2 map, in one run

`mapgen` makes the `openomsi-realmap` folder of [docs/MAP_PACKAGE.md](../../docs/MAP_PACKAGE.md) (read by openOMSI; OMSI 2 itself does not read it) from three things: **the map** (its tiles, timetables and eras), **where the map is**
(a point or a place name, when the map does not say) and **OpenStreetMap**. It is plain Python, meant to be read and edited: it is a
base generator, not a closed product.

```
pip install numpy scipy pillow contourpy

python mapgen.py --omsi "C:/Games/OMSI 2" --map "Projekt_Szczecin" --at 53.43,14.55 --out ./out/szczecin
python mapgen.py --omsi "C:/Games/OMSI 2" --map "Projekt_Szczecin" --place "Szczecin, West Pomeranian, Poland" --out ./out/szczecin
python mapgen.py --omsi "C:/Games/OMSI 2" --map "Berlin-Spandau" --out ./out/spandau            # [worldcoordinates]: no hint needed
python mapgen.py ... --timetables "C:/tmp/tram-unpacked"       # more timetable files of the map (repeat for several)
python mapgen.py ... --mode shore | fitted | exact | auto      # auto is the default
python mapgen.py ... --relief 5                                # contour lines every 5 m (the real terrain; in mode own the map's own ground)
python mapgen.py --omsi "C:/Games/OMSI 2" --map "My_Fictional_Map" --mode own --relief 5 --out ./out/mine   # no OpenStreetMap at all
```

Then copy the output folder to `<OMSI 2 or openOMSI content folder>/Maps/<Map>/openomsi-realmap/`. `REPORT.md` in the output says
what was found and whether the rules hold.

## What it does (the six steps are the six blocks of `main()` in `mapgen.py`)

| # | Step | File | In plain words |
|---|---|---|---|
| 1 | read the map | `placement.py` (`read_global`) | tiles, tile size, is it on `[worldcoordinates]` |
| 2 | the map's own lines | `omsimap.py` | stops, ways, itineraries, times, eras (Chrono) from the map's TTData; no real-world data involved |
| 3 | locate the map | `locate.py`, `osm.py` | compare with OpenStreetMap by **stop names**, **street names**, **neighbourhood names**, **bus routes**, and the map's **roads** against the real streets |
| 4 | choose how far to go | `mapgen.py` (`choose_mode`) | `exact`, `fitted` or `shore` (below) |
| 5 | the real layers | `surface.py`, `relief.py`, `geom.py`; or `ownmap.py`, `terrain.py` | water, green, built-up land, rivers, rail, districts, streets with limits, relief; or only the shore; or (mode own) what the map's own tiles hold |
| 6 | check and write | `check.py`, `icons.py` | manifest, icons, `REPORT.md`; **no road in water** is verified |

## The four modes

| Mode | When (auto) | Carries |
|---|---|---|
| `exact` | the map is on `[worldcoordinates]` and the tile index alone puts its roads on the real streets (median ≤ 15 m, 90% ≤ 50 m) | all real layers, as they are (Berlin-Spandau) |
| `fitted` | the real city must be bent by at most 120 m (90% of the roads) to meet the map | all real layers, bent to the map's own roads (RMG Leste) |
| `shore` | the map is out of proportion with the city (the real city would have to be bent by more) | **north and shore only**: water areas of 2 ha or more, rivers and canals; every road, stop, line and time is the map's own; the water is checked so that no road lies in it (Projekt Szczecin) |
| `own` | `--mode own`, or a map without `[worldcoordinates]` and without `--at` / `--place` (a fictional map; no OpenStreetMap, no network) | the map's **own tiles measured**: woods (where tree objects are dense), buildings, water, sports grounds, rails, water courses, and the relief of its own ground (`--relief`); plus the lines, stops and timetables. What is what comes from the NAME of the object / spline file: the patterns at the top of `ownmap.py`, to be edited for the content of the map |

The limits are constants at the top of `mapgen.py` (`EXACT_MEDIAN`, `EXACT_P90`, `MIN_COVER`, `FITTED_BEND_P90`, `WATER_MARGIN`);
`--mode` overrides the choice.

## How the map is located (`locate.py`)

1. **A first place.** `[worldcoordinates]`: given. Otherwise the stops that have the same name in the map and in OpenStreetMap
   give a similarity (scale, turn, shift) by RANSAC; the search starts at `--at` or at the middle of `--place` (geocoded by Nominatim).
2. **The roads.** Every spline of the map's tiles is laid on OpenStreetMap's named streets (iterative closest points, wide reach to narrow).
3. **The landmarks.** Where the map is far off the roads say nothing, the names do: a stop with the name of a real stop; a stop named after a
   street (it must lie on it); a stop named after a neighbourhood (near it); the ways of the map's bus lines on the real routes of the same number.
4. **The field.** A smooth local correction (thin-plate spline) through the landmarks and the offsets the roads still show cell by cell.
5. **The verdict.** How far the real world had to be bent, and how well roads and streets agree: it feeds `choose_mode`.

## Files

```
mapgen.py       the entry: the six steps, the modes, the manifest
omsimap.py      the OMSI side: tiles, splines, objects, TTData, eras, lines.lin, station markers
placement.py    where a map lies on the globe: WorldPlacement, FittedPlacement (similarity + field)
locate.py       the comparison with OpenStreetMap
osm.py          Overpass, Nominatim, the cache, name spelling
surface.py      OpenStreetMap -> surface.oms (full or shore), regions.cfg
relief.py       the real terrain's contour lines (public elevation tiles)
geom.py         polygons: stitching, simplifying, triangulating, name boxes
ownmap.py       mode own: woods, buildings, water, sports grounds, rails, rivers measured from the map's own tiles
terrain.py      the map's own ground (.terrain files) as contour lines
surfacefile.py  reads and writes surface.oms in memory
check.py        the rules (no road in water, no jump in a way) and REPORT.md
icons.py        plain pictograms for the railway stations
```

## Notes

- Downloads (Overpass, Nominatim, elevation tiles) are kept in `--cache`; the free servers sometimes answer slowly (HTTP 504): it waits and retries.
- If the map has timetables the game does not load (an unpacked archive an author left in TTData), point `--timetables` at the folder.
- A line a map shows in few stops is the map's own doing: the data only has those stops.
- Nothing from the real world is used for lines: a map set in 1989 gets the lines of 1989 and of the changes after it.
- Data (c) OpenStreetMap contributors, ODbL: keep the credit; the manifest carries it.
