# openomsi-map-packages

Map packages for [openOMSI](https://github.com/openOMSI-Project/openOMSI): the pre-built picture and the lines of a map, so that
the navigator and the city map show more than the lane network, and the generator that makes them.

A package is one folder, `openomsi-realmap`, next to a map's files. OMSI 2 itself (Omsi.exe) does not read it and ignores it, so
a map made for both games loses nothing. The format is described in [docs/MAP_PACKAGE.md](docs/MAP_PACKAGE.md).

## Packages

| Package | Map | What it adds | Data |
|---|---|---|---|
| [berlin-spandau](packages/berlin-spandau/) | Berlin-Spandau (stock map of OMSI 2) | water, green areas, woods, rivers, rail, district borders and names, streets with their speed limits, stations, relief (1 m contour lines), and the lines of every era the map has (bus, metro, rail) with timetables | OpenStreetMap (ODbL) + the map's own timetable |
| [projekt-szczecin](packages/projekt-szczecin/) | Projekt Szczecin 4.0.1 | the shore (the water of the real Szczecin set by north and position; the map itself is not aligned with reality) and the lines of the map (bus and tram) with timetables, on the map's own roads | OpenStreetMap (ODbL) + the map's own timetable |

## Using a package

1. Copy the package's `openomsi-realmap` folder to `Maps/<Map>/openomsi-realmap/` in openOMSI's content folder (the folder next to
   `openomsi.exe`, where mods go). The OMSI 2 installation is never written to. Putting it in the installation's own
   `Maps/<Map>/` works as well.
2. Start the map and press Shift+M. `nav_surface=0` in the settings turns a package off.

## Making a package

[tools/mapgen](tools/mapgen/) makes a package for any OMSI 2 map in one run: the map's own lines from its timetables and eras, the
place of the map found by comparing stop, street and neighbourhood names and bus routes with OpenStreetMap, and, as far as the map
fits the real city, its water, green areas, streets and relief; or only the shore when it does not; or the map's own tiles alone
when it is a made-up place. See its [README](tools/mapgen/README.md).

The packages here were made with the scripts that became that generator (the exact version of each is in its README).

## Licences

Code and documentation: MIT ([LICENSE](LICENSE)). The OpenStreetMap data inside the packages: ODbL 1.0
([LICENSE-DATA.md](LICENSE-DATA.md)). Credit the maps and their authors when you share a package.
