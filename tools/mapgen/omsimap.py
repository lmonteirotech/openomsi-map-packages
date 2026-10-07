#!/usr/bin/env python3
"""omsimap.py - reads an OMSI 2 map (its tiles, its timetable, its eras) and works out its LINES.

Nothing here comes from the real world. A map set in 1989 gets the lines of 1989 and of the changes of 1990-94, as the
game itself runs them (the same rules as `TimetableData::load_with_chrono`):

 1. TTData of the map and of every Chrono folder is read: bus stops, links between stops (with the splines and object
    paths they run over), trips (.ttp), tracks (.ttr) and lines (.ttl). Other folders of timetable files can be added
    (`extra`: an archive the author left unpacked, a tram network the game does not load).
 2. The map's tiles (and the Chrono folders') are read once for the splines and objects those use.
 3. Every date a Chrono folder starts or ends on cuts the calendar. For each stretch the folders in force are laid over
    the map's own data (a later folder replaces a trip, a link or a line; `[deactivate_lines]` takes a line off) and each
    line is worked out. Stretches in which a line is the same are joined: a line has one record per distinct form.
 4. A line's two main trips (most departures) are its Route 1 and Route 2: the way (links joined, or the .ttr), the stops,
    the length, the trip time, the days, the itinerary.

Positions are metres of the map's tile grid (tile * grid + place in the tile).
"""
import collections
import datetime
import glob
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# the tour group (the vehicles of a tour) says what kind of line it is; the first rule that matches wins.
# "skip": not a line a passenger takes (aircraft).
MODAL_RULES = [
    (r"pan am|mi-8|aircraft|flug", "skip"),
    (r"gz_|g_z|güter|gueter|freight|ohe|kolej|pkp", "skip"),     # freight is no line a passenger takes
    (r"u-bahn|metro|subway", "metro"),
    (r"s-bahn|regio|fernzug|zug|train|rail", "rail"),
    (r"tram|strassenbahn|straßenbahn|vlt", "tram"),
]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def rd(path):
    b = open(path, "rb").read()
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        t = b.decode("utf-16", "replace")
    else:
        t = b.decode("cp1252", "replace")
    return t.replace("\r", "")


def rows(path):
    return [l.strip() for l in rd(path).split("\n")]


def num(s, d=0.0):
    try:
        return float(s)
    except (ValueError, TypeError):
        return d


def ival(s, d=0):
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return d


# ---------------------------------------------------------------------------------------------------- TTData
class Layer:
    """What one folder (the map's or a Chrono's) brings to the timetable."""

    def __init__(self, name):
        self.name = name
        self.busstops = {}     # object id -> name
        self.links = {}        # (from, to) -> (length, [(id, k)])
        self.trips = {}        # trip name (lower) -> dict
        self.tracks = {}       # trip name (lower) -> [(id, k)]
        self.lines = {}        # line file stem (lower) -> [tour]
        self.start, self.end, self.off = 0, 99999999, []


def read_layer(name, folder, ttdir):
    L = Layer(name)
    cfg = os.path.join(folder, "Chrono.cfg")
    if name != "base" and os.path.isfile(cfg):
        t = rows(cfg)
        for i, l in enumerate(t):
            if l == "[startdate]":
                L.start = ival(t[i + 1], 0)
            elif l == "[enddate]":
                L.end = ival(t[i + 1], 99999999)
            elif l == "[deactivate_lines]":
                n = ival(t[i + 1])
                L.off = [x.strip() for x in t[i + 2:i + 2 + n]]
    if not os.path.isdir(ttdir):
        return L
    p = os.path.join(ttdir, "Busstops.cfg")
    if os.path.isfile(p):
        t = rows(p)
        for i, l in enumerate(t):
            if l == "[busstop]":
                L.busstops.setdefault(ival(t[i + 3]), t[i + 1])
    p = os.path.join(ttdir, "StnLinks.cfg")
    if os.path.isfile(p):
        t = rows(p)
        cur = None
        for i, l in enumerate(t):
            if l == "[StnLink]":
                cur = (ival(t[i + 2]), ival(t[i + 3]))
                L.links[cur] = [num(t[i + 1]), []]
            elif l == "[StnLink_entry]" and cur is not None:
                L.links[cur][1].append((ival(t[i + 1]), ival(t[i + 2])))
    for f in sorted(glob.glob(os.path.join(ttdir, "*"))):
        stem, ext = os.path.splitext(os.path.basename(f))
        ext = ext.lower()
        if ext == ".ttp":
            L.trips[stem.lower()] = parse_trip(f, stem)
        elif ext == ".ttr":
            t = rows(f)
            L.tracks[stem.lower()] = [(ival(t[i + 1]), ival(t[i + 2])) for i, l in enumerate(t) if l == "[track_entry]"]
        elif ext == ".ttl":
            L.lines[stem.lower()] = parse_ttl(f)
    return L


def parse_trip(f, stem):
    t = rows(f)
    d = dict(name=stem, line="", terminus="", stations=[], names={}, factor=0.0)
    if "[trip]" in t:
        i = t.index("[trip]")
        d["terminus"], d["line"] = t[i + 2], t[i + 3].strip()
    for i, l in enumerate(t):
        if l == "[station_typ2]":
            d["stations"].append(ival(t[i + 1]))
        elif l == "[station]":
            sid = ival(t[i + 1])
            d["stations"].append(sid)
            d["names"][sid] = t[i + 3]
        elif l == "[profile]" and not d["factor"]:
            d["factor"] = num(t[i + 2])
    return d


def parse_ttl(f):
    t = rows(f)
    tours, cur = [], None
    for i, l in enumerate(t):
        if l == "[newtour]":
            cur = dict(number=t[i + 1], group=t[i + 2], mask=ival(t[i + 3], 1023), trips=[])
            tours.append(cur)
        elif l == "[addtrip]" and cur is not None:
            cur["trips"].append((t[i + 1].strip(), ival(t[i + 2]), num(t[i + 3])))
    return tours


def effective(layers, active):
    """The timetable of a stretch of the calendar: the map's data with the Chrono folders in force laid over it,
    in the folders' order (the game's `load_with_chrono`)."""
    seq = [layers[0]] + active
    E = dict(busstops={}, links={}, trips={}, tracks={}, lines=[])
    for L in seq:
        for k, v in L.busstops.items():
            E["busstops"].setdefault(k, v)
        E["links"].update(L.links)
        E["trips"].update(L.trips)
        E["tracks"].update(L.tracks)
    for k in range(len(seq) - 1, -1, -1):
        for stem, tours in seq[k].lines.items():
            if any(x == stem for x, _ in E["lines"]):
                continue
            if any(stem == o.lower() for later in seq[k + 1:] for o in later.off):
                continue
            E["lines"].append((stem, tours))
    return E


# ---------------------------------------------------------------------------------------------------- geometry
def curve(x, y, h, L, r, ox, oy):
    n = 1 if abs(r) < 1e-6 else max(2, int(abs(L / r) / 0.15) + 1)
    p = []
    for k in range(n + 1):
        s = L * k / n
        if abs(r) < 1e-6:
            hh = math.radians(h)
            px, py = x + math.sin(hh) * s, y + math.cos(hh) * s
        else:
            h0 = math.radians(h)
            dh = s / r
            px = x + r * (math.cos(h0) - math.cos(h0 + dh))
            py = y + r * (math.sin(h0 + dh) - math.sin(h0))
        p.append((ox + px, oy + py))
    return p


class Geo:
    """The splines and objects (with their paths) the timetable runs over, and where the stops stand."""

    def __init__(self, omsi, map_dir, grid, need):
        self.omsi, self.grid, self.need = omsi, grid, need
        self.sp, self.ob = {}, {}
        self.sp_all, self.ob_all = collections.defaultdict(list), collections.defaultdict(list)   # every one of an id (ids repeat across tiles and eras)
        self.pos = {}          # objects hung on a spline ([splineAttachement]): where they stand
        self._sco = {}
        files = glob.glob(os.path.join(map_dir, "tile_*.map")) + glob.glob(os.path.join(map_dir, "Chrono", "*", "tile_*.map"))
        for i, f in enumerate(sorted(files)):
            self.scan(f)
        print(f"geometry: {len(self.sp)} splines and {len(self.ob)} objects of {len(files)} tiles")

    def scan(self, f):
        m = re.search(r"tile_(-?\d+)_(-?\d+)", f)
        tx, ty = int(m.group(1)), int(m.group(2))
        ox, oy = tx * self.grid, ty * self.grid
        t = rows(f)
        order = []             # every spline of the tile, in file order (an attachment names its spline by that index)
        for i, l in enumerate(t):
            if l in ("[spline]", "[spline_h]"):
                try:
                    order.append(tuple(float(t[i + k]) for k in (6, 8, 9, 10, 11)))
                except (ValueError, IndexError):
                    order.append(None)
                try:
                    sid = int(t[i + 3])          # (then the ids of the previous and the next spline)
                    if self.need is not None and sid not in self.need:
                        continue
                    x, y, h, L, r = (float(t[i + k]) for k in (6, 8, 9, 10, 11))
                except (ValueError, IndexError):
                    continue
                self.sp[sid] = curve(x, y, h, L, r, ox, oy)
                self.sp_all[sid].append(self.sp[sid])
            elif l == "[object]":
                try:
                    oid = int(t[i + 3])
                    if self.need is not None and oid not in self.need:
                        continue
                    a, b, rot = float(t[i + 4]), float(t[i + 5]), float(t[i + 7])
                except (ValueError, IndexError):
                    continue
                self.ob[oid] = dict(ox=ox, oy=oy, a=a, b=b, rot=rot, sco=t[i + 2])
                self.ob_all[oid].append(self.ob[oid])
            elif l == "[splineAttachement]":
                # 0, file, id, the spline's index in the tile, lateral offset, height, distance along the chain
                try:
                    oid, k, d = int(t[i + 3]), int(t[i + 4]), float(t[i + 7])
                except (ValueError, IndexError):
                    continue
                if (self.need is not None and oid not in self.need) or not (0 <= k < len(order)):
                    continue
                while k + 1 < len(order) and order[k] and order[k + 1] and d > order[k][3]:
                    d -= order[k][3]
                    k += 1
                if order[k]:
                    x, y, h, L, r = order[k]
                    s_ = max(0.0, min(d, L))
                    px, py = curve(x, y, h, s_, r, ox, oy)[-1] if s_ > 0 else (ox + x, oy + y)
                    self.pos[oid] = (px, py)

    def paths(self, sco):
        if sco in self._sco:
            return self._sco[sco]
        r = []
        fp = os.path.join(self.omsi, sco.replace("\\", os.sep))
        if os.path.isfile(fp):
            t = rows(fp)
            for i, l in enumerate(t):
                if re.fullmatch(r"\[path(_\d+)?\]", l):          # [path] and the newer [path_2]: x, y, z, heading, radius, length, ...
                    try:
                        r.append([float(v) for v in t[i + 1:i + 7]])
                    except ValueError:
                        pass
        self._sco[sco] = r
        return r

    def candidates(self, eid, k):
        """The ways an entry (id, k) can be read: a spline of that id, an object's path of that id. The map's ids are not
        unique across the two (Szczecin has an object and a spline with the same number), so both are offered and
        the route picks the one that carries on from where it is."""
        out = list(self.sp_all.get(eid, []))
        for o in self.ob_all.get(eid, []):
            e = self.entry_object(eid, k, o)
            if e:
                out.append(e)
        return out

    def entry(self, eid, k):
        if eid in self.sp:
            return self.sp[eid]
        return self.entry_object(eid, k)

    def entry_object(self, eid, k, o=None):
        o = o or self.ob.get(eid)
        if not o:
            return []
        ps = self.paths(o["sco"])
        if not (0 <= k < len(ps)):
            return []
        px, py, pz, h, rad, L = ps[k]
        if L <= 0:
            return []
        th = math.radians(o["rot"])
        gx = o["a"] + px * math.cos(th) + py * math.sin(th)
        gy = o["b"] - px * math.sin(th) + py * math.cos(th)
        return curve(gx, gy, h + o["rot"], L, rad, o["ox"], o["oy"])

    def stop(self, sid):
        if sid in self.pos:
            return self.pos[sid]
        o = self.ob.get(sid)
        return (o["ox"] + o["a"], o["oy"] + o["b"]) if o else None


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        best, bi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if d2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
                d = math.hypot(px - ax - u * dx, py - ay - u * dy)
            if d > best:
                best, bi = d, i
        if best > eps and bi >= 0:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


# ---------------------------------------------------------------------------------------------------- lines
def modal_of(groups):
    g = " ".join(groups).lower()
    for pat, m in MODAL_RULES:
        if re.search(pat, g):
            return m
    return "bus"


def days_text(mask):
    wk = [d for d in range(7) if mask & (1 << d)]
    if len(wk) == 7:
        return "Every day"
    parts, i = [], 0
    while i < len(wk):
        j = i
        while j + 1 < len(wk) and wk[j + 1] == wk[j] + 1:
            j += 1
        parts.append(DAYS[wk[i]] if i == j else f"{DAYS[wk[i]]}–{DAYS[wk[j]]}")
        i = j + 1
    return ", ".join(parts) if parts else "—"


def clean(name, line):
    n = name.replace("#", " ").strip()
    if line and n.startswith(line) and not n[len(line):len(line) + 1].isdigit():
        n = n[len(line):].strip() or n
    return n


def pick_entries(geo, entries):
    """For every entry the geometry that makes the route one piece: where an id is both a spline and an object, the
    reading with the least total gap between one entry and the next (Viterbi over the two candidates)."""
    cands = [geo.candidates(eid, k) or [None] for eid, k in entries]

    def gap(u, v):
        if not u or not v:
            return 0.0
        return min(math.dist(u[i], v[j]) for i in (0, -1) for j in (0, -1))

    best = [[0.0] * len(c) for c in cands]
    back = [[0] * len(c) for c in cands]
    for i in range(1, len(cands)):
        for j, v in enumerate(cands[i]):
            costs = [best[i - 1][m] + gap(u, v) for m, u in enumerate(cands[i - 1])]
            m = min(range(len(costs)), key=costs.__getitem__)
            best[i][j], back[i][j] = costs[m], m
    if not cands:
        return []
    j = min(range(len(cands[-1])), key=best[-1].__getitem__)
    out = [None] * len(cands)
    for i in range(len(cands) - 1, -1, -1):
        out[i] = cands[i][j]
        j = back[i][j]
    return out


def route_of(E, trip, deps, geo, cache):
    """One route of a line: its facts and its way (a key that says whether two stretches have the same)."""
    st = trip["stations"]
    key = (trip["name"].lower(), tuple(st))
    names = lambda sid: clean(E["busstops"].get(sid) or trip["names"].get(sid) or str(sid), trip["line"])
    km, entries = 0.0, []
    tr = E["tracks"].get(trip["name"].lower())
    if tr:
        entries = list(tr)
    else:
        for a, b in zip(st, st[1:]):
            link = E["links"].get((a, b))
            if link:
                km += link[0] / 1000.0
                entries += link[1]
    key += (tuple(entries),)
    mask = 0
    for m in deps:
        mask |= m
    return dict(key=key, trip=trip, km=km, entries=entries, mask=mask, stops=[(sid, names(sid)) for sid in st], itin=f"{names(st[0])} – {names(st[-1])}" if st else "",
                first=names(st[0]) if st else "", last=names(st[-1]) if st else "", n=len(st))


def lines_of(E, geo_ids=None):
    """number -> dict(modal, routes[...]) of an effective timetable."""
    per = collections.defaultdict(lambda: dict(trips=collections.Counter(), masks=collections.defaultdict(list), groups=set()))
    for stem, tours in E["lines"]:
        stem_name = stem.upper() if len(stem) <= 4 else stem
        for t in tours:
            for name, prof, dep in t["trips"]:
                tr = E["trips"].get(name.lower())
                if not tr or len(tr["stations"]) < 2:
                    continue
                if not tr["line"]:
                    tr = dict(tr, line=stem_name)      # a train's trips carry no line: the line's file names it
                if re.match(r"(bf\b|bf[ _])|\(bf\)", tr["name"].lower()):
                    continue
                d = per[tr["line"]]
                d["trips"][tr["name"].lower()] += 1
                d["masks"][tr["name"].lower()].append(t["mask"])
                d["groups"].add(t["group"])
    out = {}
    for number, d in per.items():
        modal = modal_of(d["groups"])
        if modal == "skip" or sum(d["trips"].values()) < 3:    # (fewer: a stray trip of an older line left in a tour)
            continue
        ranked = [n for n, _ in d["trips"].most_common()]
        r1 = ranked[0]
        t1 = E["trips"][r1]
        back = [n for n in ranked[1:] if E["trips"][n]["stations"][0] == t1["stations"][-1] or E["trips"][n]["stations"][-1] == t1["stations"][0]]
        r2 = (back or ranked[1:2] or [None])[0]
        routes = [r1] + ([r2] if r2 else [])
        out[number] = dict(modal=modal, routes=[(E["trips"][n], d["masks"][n]) for n in routes])
    return out


def rail_vehicles(omsi, map_dir, dirs):
    """From the map's AI lists: the vehicle folders of the metro and of the railway, as parts of a vehicle file's
    path ("vehicles/a3/"), by the kind of the group (MODAL_RULES). Aircraft are left out."""
    kinds = {"metro": set(), "rail": set(), "tram": set()}
    files = [os.path.join(map_dir, "ailists.cfg")] + [os.path.join(d, f) for d in dirs for f in os.listdir(d) if f.lower().startswith("ailists")]
    for f in files:
        if not os.path.isfile(f):
            continue
        t = rows(f)
        for i, l in enumerate(t):
            if not l.lower().startswith("[aigroup_2]"):
                continue
            modal = modal_of([t[i + 1]])
            if modal == "skip" and re.search(r"gz_|g_z|güter|gueter|freight|ohe", t[i + 1].lower()):
                modal = "rail"            # freight trains are trains on the map, if no line of theirs
            if modal not in kinds:
                continue
            j = i + 2
            while j < len(t) and t[j].lower() != "[end]":
                e = t[j].replace("\\", "/")
                if e.lower().endswith(".zug"):
                    z = os.path.join(omsi, e)
                    if os.path.isfile(z):
                        for v in rows(z):
                            if v.lower().endswith((".ovh", ".bus")):
                                kinds[modal].add("/".join(v.replace("\\", "/").lower().split("/")[:-1]) + "/")
                elif e.lower().endswith((".ovh", ".bus")):
                    kinds[modal].add("/".join(e.lower().split("/")[:-1]) + "/")
                j += 1
    return kinds




# ---------------------------------------------------------------------------------------------------- the map's roads
def all_geometry(omsi, map_dir, grid):
    """Every spline and object of the map's tiles (the roads, rails and kerbs), not only those a timetable uses."""
    return Geo(omsi, map_dir, grid, None)


def road_samples(geo, step=12.0):
    """Points along every spline's centre line, `step` metres apart: [(x, y)] of the map's grid."""
    out = []
    for curves in geo.sp_all.values():
        for p in curves:
            for (ax, ay), (bx, by) in zip(p, p[1:]):
                n = max(1, int(math.hypot(bx - ax, by - ay) / step))
                for k in range(n):
                    out.append((ax + (bx - ax) * k / n, ay + (by - ay) * k / n))
    return out


def stop_positions(layers, geo):
    """name -> [(x, y)] of every stop of the map that has a place on it (all eras)."""
    out = {}
    done = set()
    for L in layers:
        for oid, n in L.busstops.items():
            if oid in done:
                continue
            done.add(oid)
            p = geo.stop(oid)
            if p:
                out.setdefault(n, []).append(p)
    return out


# ---------------------------------------------------------------------------------------------------- the whole job
def read_timetables(map_dir, extra=(), eras=True):
    """[base layer, extra folders merged into it], and the Chrono layers."""
    layers = [read_layer("base", map_dir, os.path.join(map_dir, "TTData"))]
    base = layers[0]
    for folder in extra:
        ex = read_layer("extra", os.path.dirname(folder), folder)
        for k, v in ex.busstops.items():
            base.busstops.setdefault(k, v)
        base.links.update(ex.links)
        base.trips.update(ex.trips)
        base.tracks.update(ex.tracks)
        base.lines.update(ex.lines)
        print(f"  {len(ex.lines)} lines and {len(ex.trips)} trips added from {folder}")
    chronos = []
    chrono_dir = os.path.join(map_dir, "Chrono")
    if eras and os.path.isdir(chrono_dir):
        for d in sorted(os.listdir(chrono_dir)):
            f = os.path.join(chrono_dir, d)
            if os.path.isdir(f):
                chronos.append(read_layer(d, f, os.path.join(f, "TTData")))
    return layers, chronos


def build_lines(omsi, map_dir, grid, out_dir, extra=(), eras=True, manifest=None, geo=None, layers=None, chronos=None):
    """Writes lines.lin and markers.cfg (the stations of the map's own railway and metro) into `out_dir`; with `manifest`,
    the tram / metro / rail vehicle keys are put in it. Returns a short summary and the loaded pieces."""
    if layers is None:
        layers, chronos = read_timetables(map_dir, extra, eras)
    print(f"  {len(layers[0].trips)} trips, {len(layers[0].lines)} lines, {len(chronos)} eras")
    if geo is None:
        need = set()
        for L in layers + chronos:
            for _, es in L.links.values():
                need.update(i for i, _ in es)
            for es in L.tracks.values():
                need.update(i for i, _ in es)
            for t in L.trips.values():
                need.update(t["stations"])
            need.update(L.busstops)
        geo = Geo(omsi, map_dir, grid, need)

    # the calendar cut at every date an era starts or ends
    day = lambda n: datetime.date(n // 10000, n // 100 % 100, n % 100)
    cuts = {0}
    for c in chronos:
        cuts.add(c.start)
        if c.end < 99999999:
            cuts.add(int((day(c.end) + datetime.timedelta(days=1)).strftime("%Y%m%d")))
    cuts = sorted(cuts)
    spans = [(cuts[i], (cuts[i + 1] - 1) if i + 1 < len(cuts) else 0) for i in range(len(cuts))]
    variants = collections.defaultdict(list)   # number -> [dict(from, to, key, modal, routes)]
    for lo, hi in spans:
        active = [c for c in chronos if c.start <= lo <= c.end]
        E = effective(layers, active)
        for number, d in lines_of(E).items():
            routes = [route_of(E, t, ms, geo, None) for t, ms in d["routes"]]
            key = (d["modal"], tuple(r["key"] for r in routes))
            vs = variants[number]
            if vs and vs[-1]["key"] == key and vs[-1]["to"] == lo - 1:
                vs[-1]["to"] = hi
            else:
                vs.append(dict(key=key, frm=lo, to=hi, modal=d["modal"], routes=routes))

    # the ways, worked out once per distinct route
    way_cache = {}
    jumps = []

    def way(r):
        if r["key"] in way_cache:
            return way_cache[r["key"]]
        pts = []
        st = r["trip"]["stations"]
        if r["entries"]:
            chosen = pick_entries(geo, r["entries"])
            for (eid, k), e in zip(r["entries"], chosen):
                if not e:
                    continue
                # an entry is a lane: it may run against the spline's own direction, so it is laid the way
                # that carries on from where the route is
                if pts and math.dist(pts[-1], e[-1]) < math.dist(pts[-1], e[0]):
                    e = e[::-1]
                if pts and math.dist(pts[-1], e[0]) > 300:
                    jumps.append((r["trip"]["name"], round(math.dist(pts[-1], e[0]))))
                pts += e
        stops = [p for p in (geo.stop(s) for s in st) if p]
        if len(pts) < 2:
            pts = stops[:]
        way_cache[r["key"]] = (rdp(pts, 1.0), stops)
        return way_cache[r["key"]]

    allp = []
    for vs in variants.values():
        for v in vs:
            for r in v["routes"]:
                allp += way(r)[0][:1]
    ox = math.floor(min(p[0] for p in allp) / 1000) * 1000 if allp else 0
    oy = math.floor(min(p[1] for p in allp) / 1000) * 1000 if allp else 0

    def natural(s):
        return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]

    os.makedirs(out_dir, exist_ok=True)
    lines_path = os.path.join(out_dir, "lines.lin")
    n_var = 0
    with open(lines_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("RLIN\t1\n# made by mapgen from the map's own timetable, network and eras - do not edit by hand\n")
        f.write(f"ORIGEM\t{ox:.1f}\t{oy:.1f}\n")
        order = ["bus", "tram", "metro", "rail"]
        for number in sorted(variants, key=lambda k: (order.index(variants[k][0]["modal"]), natural(k))):
            for v in variants[number]:
                r1 = v["routes"][0]
                kind = "EXP" if v["modal"] == "bus" and re.search(r"(E|^X.*)$", number) and not number.endswith("N") else "ALI"
                f.write(f"L\t{number}\t{kind}\t{r1['itin'] or number}\t{v['modal']}\t{v['frm']}\t{v['to']}\n")
                n_var += 1
                for r in v["routes"]:
                    pts, stops = way(r)
                    t = r["trip"]
                    km = r["km"] if r["km"] > 0 else sum(math.dist(p, q) for p, q in zip(pts, pts[1:])) / 1000.0
                    circ = 1 if t["stations"] and t["stations"][0] == t["stations"][-1] else 0
                    f.write(f"R\t{km:.3f}\t{r['n']}\t{round(t['factor'])}\t{circ}\t{days_text(r['mask'])}\t\t{r['itin']}\n")
                    f.write("P\t" + " ".join(f"{p[0] - ox:.1f} {p[1] - oy:.1f}" for p in pts) + "\n")
                    f.write("S\t" + " ".join(f"{p[0] - ox:.1f} {p[1] - oy:.1f}" for p in stops) + "\n")

    kinds = rail_vehicles(omsi, map_dir, [os.path.join(map_dir, "Chrono", c.name) for c in chronos])
    if manifest:
        set_manifest_keys(manifest, {"tram_vehicles": kinds["tram"], "metro_vehicles": kinds["metro"], "rail_vehicles": kinds["rail"]})

    n_st = write_station_markers(os.path.join(out_dir, "markers.cfg"), variants, layers, chronos, geo)
    cnt = collections.Counter(v[0]["modal"] for v in variants.values())
    return dict(lines=len(variants), forms=n_var, by_modal=dict(cnt), stations=n_st, jumps=jumps, vehicles={k: sorted(v) for k, v in kinds.items()},
                layers=layers, chronos=chronos, geo=geo, variants=variants, origin=(ox, oy))


def set_manifest_keys(path, values):
    """Puts `key = a, b` lines (the vehicle kinds) into a manifest.cfg, replacing the ones that were there."""
    keep = [l for l in open(path, encoding="utf-8").read().split("\n") if not re.match(r"\s*(metro|rail|tram)_vehicles\s*=", l)]
    while keep and not keep[-1].strip():
        keep.pop()
    keep += ["", "# what the map's rail vehicles are (a part of the vehicle file's path): the map's own AI groups"]
    for key, vals in values.items():
        if vals:
            keep.append(f"{key} = " + ", ".join(sorted(vals)))
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(keep) + "\n")


def write_station_markers(path, variants, layers, chronos, geo):
    """The stations of the railways and the metro, for markers.cfg (the map's own stops, as the lines call at them)."""
    stations = {}
    for number, vs in variants.items():
        for v in vs:
            if v["modal"] not in ("rail", "metro"):
                continue
            icon = "ubahn.png" if v["modal"] == "metro" else ("sbahn.png" if re.match(r"S\d", number) else "stop.png")
            for r in v["routes"]:
                for sid, name in r["stops"]:
                    p = geo.stop(sid)
                    if p:
                        stations.setdefault((v["modal"], name), (icon, p))
    # and the stations the map names among its stops that no line of it calls at (a bus stop object called "U Altstadt")
    named = collections.defaultdict(list)
    for L in layers + chronos:
        for oid, name in L.busstops.items():
            p = geo.stop(oid)
            if not p:
                continue
            if re.match(r"(S\+U|U\+S|U)\b", name):
                named[("metro", name)].append(p)
            elif re.match(r"S\b", name):
                named[("rail", name)].append(("s", p))
            elif re.search(r"\b(Bhf|Bahnhof|Fernbahnhof)\b", name) and not re.search(r"g(ü|ue)ter", name, re.I):
                named[("rail", name)].append(p)
    for (modal, name), ps in named.items():
        pts = [q[1] if isinstance(q[0], str) else q for q in ps]
        c = (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
        icon = "ubahn.png" if modal == "metro" else ("sbahn.png" if any(isinstance(q[0], str) for q in ps) else "stop.png")
        stations.setdefault((modal, name), (icon, c))
    kept = {}
    for key, (icon, pt) in sorted(stations.items(), key=lambda kv: (["ubahn.png", "sbahn.png", "stop.png"].index(kv[1][0]), kv[0][1])):
        if all(math.dist(pt, q[1]) > 120 for q in kept.values()):
            kept[key] = (icon, pt)
    if not kept:
        return 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# icon | width in pixels at interface size 1 | x | y | name  (x, y: metres of the author's grid)\n")
        for (modal, name), (icon, p) in sorted(kept.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            f.write(f"marker = icons/{icon} | 24 | {p[0]:.1f} | {p[1]:.1f} | {name}\n")
    return len(kept)
