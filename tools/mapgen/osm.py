#!/usr/bin/env python3
"""osm.py - everything that talks to the outside: OpenStreetMap (Overpass), the place search (Nominatim), and the
spelling of names so that the map's stop "Pl. Zołnierza Polskiego" and the real one meet.

Every answer is kept in a cache folder (a second run asks for nothing) and the code waits between requests (at least 5 s between
Overpass queries, 1.5 s between place searches, longer after a slow answer) and moves to another server when one is busy: be kind to
these free services. Data (c) OpenStreetMap contributors, ODbL: keep the credit in manifest.cfg.
"""
import hashlib
import json
import math
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

# The public Overpass servers that answer for the whole planet, tried in turn. A server that answers 5xx, 429 or does not answer is left alone
# for a while (the more it fails in a row, the longer) and the next one gets the query at once; only when all of them are resting does the
# run wait. (overpass.openstreetmap.fr answers 403 to scripts, and the Swiss and Japanese servers only hold their own country, so they are not here.)
# Own servers can be added: `--overpass URL` (repeat it), or the variable OVERPASS_URLS (addresses separated by spaces).
OVERPASS_MIRRORS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
                    "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
OVERPASS = OVERPASS_MIRRORS[0]
# the place search: Nominatim first (at most one request a second, by its rules), then Photon (Komoot), which serves the same data of OpenStreetMap
NOMINATIM = "https://nominatim.openstreetmap.org/search"
PHOTON = "https://photon.komoot.io/api/"
AGENT = "openOMSI-Map-Package-Creator/1.0 (+https://leomonteiro.eti.br; mapgen)"

STREETS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"

MIN_PAUSE = 5.0                  # seconds between two Overpass queries (never less); after a slow answer the pause is longer (see Net.pause_for)
NOMINATIM_PAUSE = 1.5            # their rule is one request a second
COOLDOWN = 45.0                  # a mirror that failed rests this long, doubled for each failure in a row, up to 15 minutes
MAX_TRIES = 14
GUESS_SECONDS = 22.0             # what a block query is guessed to take before one has been timed


class Net:
    """What the run knows about the servers: who rests until when, when the last call ended and how long the answers take, and the
    plan (how many queries are still to ask) the forecast is made from. One instance, `NET`."""

    def __init__(self):
        self.mirrors = list(OVERPASS_MIRRORS)
        self.fails = {}                      # mirror -> failures in a row
        self.rest_until = {}                 # mirror -> time.time() until which it rests
        self.last_end = {}                   # host -> time.time() of the end of the last call
        self.last_took = 8.0
        self.took = []                       # seconds each answered query took
        self.total = 0                       # queries of the plan still unasked when it was made
        self.done = 0
        self.min_pause = MIN_PAUSE
        self.t0 = None
        self.out = lambda s: print(s, flush=True)

    # ---- the mirrors ----------------------------------------------------------------------------------------------------
    def configure(self, mirrors=None, pause=None):
        env = os.environ.get("OVERPASS_URLS", "").split()
        extra = [m for m in list(mirrors or []) + env if m]
        if extra:
            self.mirrors = extra + [m for m in OVERPASS_MIRRORS if m not in extra]
        if pause is not None:
            self.min_pause = max(1.0, float(pause))

    def pick(self):
        """The first mirror that is not resting, else (None, seconds until the first one wakes up)."""
        now = time.time()
        for m in self.mirrors:
            if self.rest_until.get(m, 0) <= now:
                return m, 0.0
        return None, min(self.rest_until[m] for m in self.mirrors) - now

    def failed(self, mirror, wait=None):
        n = self.fails[mirror] = self.fails.get(mirror, 0) + 1
        self.rest_until[mirror] = time.time() + (wait if wait else min(COOLDOWN * 2 ** (n - 1), 900.0))

    def worked(self, mirror, took):
        self.fails[mirror] = 0
        self.took.append(took)
        self.last_took = took
        # the mirror that answered goes to the front: it is the one to ask first next time
        self.mirrors.remove(mirror)
        self.mirrors.insert(0, mirror)

    # ---- the pause ------------------------------------------------------------------------------------------------------
    def pause_for(self, host, minimum):
        """Seconds still to wait before a call to `host`: at least `minimum` after the last one ended, and (Overpass) one and a half times
        what the last answer took, so that a busy server is not asked again before it has caught its breath."""
        need = minimum
        if "overpass" in host or "mail.ru" in host:
            need = max(minimum, 1.5 * self.last_took)
        return max(0.0, self.last_end.get(host, 0) + need - time.time())

    # ---- the forecast ---------------------------------------------------------------------------------------------------
    def typical(self):
        t = sorted(self.took)
        return t[len(t) // 2] if t else GUESS_SECONDS

    def forecast(self, left):
        """Seconds a plan of `left` queries is expected to take: each one is its answer plus the pause."""
        return left * (self.typical() + max(self.min_pause, 1.5 * self.typical()))

    def plan(self, queries, cache):
        """Says how many of these queries are not in the cache yet and how long they will take: call it before a loop of queries."""
        todo = [q for q in queries if not os.path.isfile(_key(q, cache))]
        self.total, self.done, self.t0 = len(todo), 0, time.time()
        if not todo:
            self.out(f"OpenStreetMap: all {len(queries)} queries are in the cache: nothing to ask")
            return 0
        self.out(f"OpenStreetMap: {len(todo)} of {len(queries)} queries still to ask ({len(queries) - len(todo)} already in the cache). "
                 f"Each one waits at least {self.min_pause:g} s after the last (more after a slow answer) and the servers are slow: "
                 f"expect about {fmt_time(self.forecast(len(todo)))} (it can be several times that when they are busy; the answers are kept, "
                 f"so a run that is stopped resumes where it was)")
        return len(todo)

    def progress(self, took, mirror):
        self.done += 1
        host = urllib.parse.urlparse(mirror).netloc
        if self.total:
            left = max(self.total - self.done, 0)
            self.out(f"  query {self.done}/{self.total} answered by {host} in {took:.0f} s; about {fmt_time(self.forecast(left))} left")
        else:
            self.out(f"  query answered by {host} in {took:.0f} s")


NET = Net()


def fmt_time(s):
    s = int(round(s))
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60:02d} min"


def configure(mirrors=None, pause=None):
    NET.configure(mirrors, pause)


def plan(queries, cache):
    return NET.plan(list(queries), cache)


def _key(key_text, cache):
    return os.path.join(cache, hashlib.sha1(key_text.encode()).hexdigest()[:16] + ".json")


def _retry_after(e):
    try:
        return float(e.headers.get("Retry-After", ""))
    except (AttributeError, TypeError, ValueError):
        return None


def _cached(key_text, cache, fetch, pause):
    os.makedirs(cache, exist_ok=True)
    key = _key(key_text, cache)
    if os.path.isfile(key):
        with open(key, encoding="utf-8") as f:
            return json.load(f)
    data = fetch()
    with open(key, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def overpass(query, cache, pause=None, fatal=True):
    """The answer (a dict with `elements`) of an Overpass query, from the cache when it was asked before. A server that fails (500, 502,
    503, 504, 429, a timeout) rests and the next mirror gets the query; with fatal=False a query no mirror answers gives an empty answer
    (a sample is no reason to stop the run). `pause` is a floor for this call; `--pause` raises the floor of all of them."""
    if not fatal:
        try:
            return overpass(query, cache, pause, True)
        except SystemExit:
            return {"elements": []}

    def fetch():
        for attempt in range(MAX_TRIES):
            mirror, wait = NET.pick()
            if mirror is None:
                NET.out(f"  all the Overpass servers are resting: waiting {fmt_time(wait)} (try {attempt + 1}/{MAX_TRIES})")
                time.sleep(max(wait, 1.0))
                continue
            host = urllib.parse.urlparse(mirror).netloc
            time.sleep(NET.pause_for(host, max(NET.min_pause, pause or 0.0)))
            req = urllib.request.Request(mirror, data=urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": AGENT})
            t = time.time()
            try:
                with urllib.request.urlopen(req, timeout=200) as r:
                    data = json.loads(r.read().decode("utf-8"))
                NET.last_end[host] = time.time()
                NET.worked(mirror, time.time() - t)
                NET.progress(time.time() - t, mirror)
                return data
            except urllib.error.HTTPError as e:
                NET.last_end[host] = time.time()
                NET.failed(mirror, _retry_after(e))
                NET.out(f"  {host} answered HTTP {e.code}: it rests for {fmt_time(NET.rest_until[mirror] - time.time())}"
                        + (", next server" if len(NET.mirrors) > 1 else ""))
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                NET.last_end[host] = time.time()
                NET.failed(mirror)
                NET.out(f"  {host}: {getattr(e, 'reason', e)}: it rests for {fmt_time(NET.rest_until[mirror] - time.time())}, next server")
        raise SystemExit("No Overpass server answered. The answers already received are kept: run it again in a while, or add a server with --overpass URL.")
    return _cached(query, cache, fetch, pause)


def _photon_place(place):
    req = urllib.request.Request(PHOTON + "?" + urllib.parse.urlencode({"q": place, "limit": 1}), headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        feats = json.loads(r.read().decode("utf-8")).get("features", [])
    if not feats:
        return []
    f = feats[0]
    lon, lat = f["geometry"]["coordinates"]
    pr = f.get("properties", {})
    ext = pr.get("extent") or [lon - 0.05, lat + 0.05, lon + 0.05, lat - 0.05]          # photon: [west, north, east, south]
    shown = ", ".join(str(pr[k]) for k in ("name", "state", "country") if pr.get(k)) or place
    return [{"lat": lat, "lon": lon, "boundingbox": [ext[3], ext[1], ext[0], ext[2]], "display_name": shown}]


def geocode(place, cache):
    """A place written by a person ("Szczecin, West Pomeranian, Poland") -> (lat, lon, (south, west, north, east), display name).
    Nominatim is asked one request a second at most; when it answers 5xx or 429 the place is asked of Photon, which has the same data. With
    --at LAT,LON none of this is needed."""
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})

    def fetch():
        last = None
        for attempt in range(4):
            time.sleep(NET.pause_for("nominatim", NOMINATIM_PAUSE))
            req = urllib.request.Request(url, headers={"User-Agent": AGENT})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                NET.last_end["nominatim"] = time.time()
                return data
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                NET.last_end["nominatim"] = time.time()
                last = e
                wait = _retry_after(e) if isinstance(e, urllib.error.HTTPError) else None
                NET.out(f"  Nominatim: {e}; " + ("trying Photon" if attempt >= 1 else f"again in {wait or 5 * (attempt + 1):g} s"))
                if attempt >= 1:
                    break
                time.sleep(wait or 5 * (attempt + 1))
        try:
            return _photon_place(place)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError) as e:
            raise SystemExit(f"No place search answered (Nominatim: {last}; Photon: {e}). Give the place as --at LAT,LON to skip the search.")
    res = _cached("nominatim:" + place, cache, fetch, NOMINATIM_PAUSE)
    if not res:
        raise SystemExit(f"No place found for {place!r}: try a more complete name or give --at LAT,LON")
    r = res[0]
    s, n, w, e = (float(v) for v in r["boundingbox"])
    return float(r["lat"]), float(r["lon"]), (s, w, n, e), r.get("display_name", place)


# ---------------------------------------------------------------------------- queries (the text is the cache key: keep it)
def bbox_text(s, w, n, e):
    return f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"


def stops_query(s, w, n, e):
    bb = bbox_text(s, w, n, e)
    return f'[out:json][timeout:180];(node["highway"="bus_stop"]["name"]{bb};node["public_transport"="platform"]["name"]{bb};);out;'


def tram_stops_query(s, w, n, e):
    bb = bbox_text(s, w, n, e)
    return f'[out:json][timeout:180];(node["railway"~"^(tram_stop|halt|station)$"]["name"]{bb};);out;'


def places_query(s, w, n, e):
    bb = bbox_text(s, w, n, e)
    return f'[out:json][timeout:180];(node["place"~"^(suburb|neighbourhood|quarter|village|town)$"]["name"]{bb};);out;'


def streets_query(s, w, n, e):
    return f'[out:json][timeout:120];way["highway"~"^({STREETS})$"]["name"]({s:.5f},{w:.5f},{n:.5f},{e:.5f});out geom;'


def routes_query(refs, s, w, n, e):
    import re
    return ('[out:json][timeout:180];relation["route"="bus"]["ref"~"^(' + "|".join(re.escape(r) for r in refs) + ')$"]'
            f'({s:.5f},{w:.5f},{n:.5f},{e:.5f});out geom;')


def block_query(s, w, n, e):
    bb = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    return f"""[out:json][timeout:120];
(
  way["natural"~"^(water|wetland|wood|scrub|grassland|heath)$"]{bb};
  relation["natural"="water"]{bb};
  way["waterway"~"^(river|stream|canal|drain)$"]{bb};
  way["leisure"~"^(park|garden|pitch|stadium|golf_course|playground|recreation_ground)$"]{bb};
  way["landuse"~"^(forest|grass|meadow|recreation_ground|cemetery|industrial|commercial|retail|residential|farmland|allotments|orchard|reservoir|basin)$"]{bb};
  way["railway"~"^(rail|light_rail|subway|tram)$"]{bb};
  way["highway"~"^({STREETS})$"]["name"]{bb};
  node["place"~"^(suburb|neighbourhood|quarter|town|city|village)$"]{bb};
  node["railway"="station"]{bb};
);
out geom;"""


def water_block_query(s, w, n, e):
    """Only the water: for the shore-only package (a fraction of the data of block_query)."""
    bb = f"({s:.6f},{w:.6f},{n:.6f},{e:.6f})"
    return f"""[out:json][timeout:120];
(
  way["natural"="water"]{bb};
  relation["natural"="water"]{bb};
  way["landuse"~"^(reservoir|basin)$"]{bb};
  way["waterway"~"^(river|canal)$"]{bb};
);
out geom;"""


def region_query(s, w, n, e, level):
    return f"""[out:json][timeout:180];
relation["boundary"="administrative"]["admin_level"="{level}"]({s:.6f},{w:.6f},{n:.6f},{e:.6f});
out geom;"""


# ---------------------------------------------------------------------------- names
_FOLD = str.maketrans({"ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ð": "d", "þ": "th", "ı": "i"})


def norm(s):
    """A name as the map may spell it: lower case, no accents (also the letters that do not decompose: ł, ø, đ ...),
    punctuation as spaces."""
    s = unicodedata.normalize("NFKD", s.lower().translate(_FOLD))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


def box_around(lat, lon, radius_km):
    d = radius_km / 111.0
    dl = d / math.cos(math.radians(lat))
    return lat - d, lon - dl, lat + d, lon + dl
