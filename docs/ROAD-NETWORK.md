# The road network of a map: what goes wrong, how to find it, how to mend it

A road file (`{"vias":[{"c":"via","p":[x,y,x,y,...],"w":width,"n":name,"z":height}]}`, metres) is what a route function walks on
(next stop, waypoint) and what a map draws. Taking it from an OMSI 2 map has two traps, found while checking a large city map
(about 10,000 road pieces) against OpenStreetMap. The scripts are in `tools/mapgen/`.

## 1. Where the errors come from

- **Centre line instead of lanes.** A road spline of the game is one centre line, but a 4-lane road with a median is ONE spline: its line falls in the
  median and is drawn as one wide road, while at junctions the objects bring the real lanes, so the road "opens" into four lanes and closes again.
  The game itself builds roads from the **lanes** (the `[path]`s of the profile, each at its lateral place) and keeps two carriageways apart. A road file should
  hold **one piece per carriageway**, taken from the lanes.
- **Pieces that do not touch.** Splines and objects are joined by the game's own `next` links, not by their ends meeting. Cut loose from the links the pieces do
  not touch: groups that the route functions cannot reach.

## 2. The audit (`audit.py <roads.json> [--csv out.csv]`)

| Error | How it is found | How it is mended | Measured (big city map) |
|---|---|---|---|
| tiny piece (a blob when drawn with the road's width) | length under 3.5 m | `connect.py limpar` | 0 left |
| duplicate (the same road twice) | 80% of a piece within 1.5 m of another | `dedupe.py`, **then re-join** | 265 found |
| split (one road in two pieces) | two ends alone at a joint, same name, width and a straight continuation (25 degrees) | `connect.py limpar` (merge) | 57 → 1 |
| spike (a piece that turns back) | turn of more than 150 degrees | `dedupe.py` | 13 → 0 |
| separate group | ends joined at 2.5 m; groups of 6 pieces or fewer | `connect.py unir`, `ligar`, `grupos` | 2,085 → 71 groups, main group 96.7% |
| loose end near a road | end within 6 m of another piece's line | `connect.py unir` (snap, a T gets a vertex) | 1 left |
| gap | two loose ends facing each other within 45 m, same street | `connect.py ligar` | 0 left |
| wide centre line left in a median | a piece 10 m or wider with another road alongside within 14 m | **not removed**: those pieces were connectors; removing them left more groups (71 → 123). Review by hand | 110 found |
| crossing without a node | two segments cross at the same height (2 m), no vertex within 2.5 m | report only | 3 found |
| loose end | any other | report only (most are the end of the modelled map) | about 1,300 |

Order that works: lanes → `unir` → `ligar` → `limpar` → `grupos` → `audit.py` (repeat if a number is worse).
**Removing duplicates makes the picture cleaner but can cut a bridge** (71 → 86 groups in the case measured): run `dedupe.py` first and re-join after it.

## 3. Checking against the real streets

A real dual carriageway is two one-way ways of the same name 8–45 m apart in OpenStreetMap; the map must have a road within 12 m under each.
Where the map has only one, the cause is one of: the end of the modelled map (the real road goes on), a partial roundabout (the game
draws an arc), a shift of position (12–30 m), or the road is really missing. In the case measured, a single centre line per avenue left 8.1 km
of avenue with one carriageway where the real road has two; lanes brought it to 4.2 km (almost all of it the other three causes).

## 4. Still to do in the generator

- `roads` step in Python that reads the lanes of the splines and objects from the tiles (the numbers above were taken with a dump of a game that
  already builds them);
- the road layer in the package format, so every reader uses the same network;
- the validation against OpenStreetMap as a step of `check.py`.
