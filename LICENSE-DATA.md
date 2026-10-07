# Licence of the data in `packages/`

This repository has two licences, and each file is under exactly one of them.

| What | Licence |
|---|---|
| Everything outside `packages/`: the generator (`tools/`), the documentation (`docs/`, the READMEs), the scripts | **MIT**, see [LICENSE](LICENSE) |
| The files inside `packages/*/openomsi-realmap/` that carry map data from OpenStreetMap: `surface.oms`, `regions.cfg`, `markers.cfg` | **ODbL 1.0** (below) |
| The other files inside `packages/*/openomsi-realmap/`: `manifest.cfg`, `lines.lin`, `icons/` | the lines (`lines.lin`) and the manifest are written by this project from the timetable of the map they are made for (stop names and places, ways, times): they are shared together with the data above, and the credit of the map and its authors goes with them (see each package's README). The icons are drawn by this project's generator and are MIT. |

## OpenStreetMap (ODbL)

The surface (water, rivers, green areas, rail, borders), the districts and the stations of the packages are derived from
**OpenStreetMap**:

> (c) OpenStreetMap contributors. Available under the Open Database Licence (ODbL) 1.0:
> <https://opendatacommons.org/licenses/odbl/1-0/> - <https://www.openstreetmap.org/copyright>

That is: the data may be used, shared and adapted **with this attribution**, and a database derived from it must be offered
under the same licence. The credit is also written in each package's `manifest.cfg` (`credit`), and openOMSI shows it on the
city map.

A package made with the generator in `tools/mapgen/` from OpenStreetMap data is under the ODbL too; the generator itself is MIT.
A package made from a map's own tiles only (`--mode own`) contains no OpenStreetMap data.

## What is not here

Nothing from OMSI 2 and nothing from the maps' own files (tiles, textures, models, scripts): a package only carries what was
worked out from them (names and places of stops, the ways and times of lines), in the format of
[docs/MAP_PACKAGE.md](docs/MAP_PACKAGE.md).
