#!/usr/bin/env python3
"""osm.py - everything that talks to the outside: OpenStreetMap (Overpass), the place search (Nominatim), and the
spelling of names so that the map's stop "Pl. Zołnierza Polskiego" and the real one meet.

Every answer is kept in a cache folder (a second run asks for nothing) and the code waits between requests: be kind to
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

OVERPASS_MIRRORS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                    "https://overpass.kumi.systems/api/interpreter"]       # tried in turn when one is busy (HTTP 504 / 429)
OVERPASS = OVERPASS_MIRRORS[0]
NOMINATIM = "https://nominatim.openstreetmap.org/search"
AGENT = "openOMSI-mapgen/1.0 (https://github.com/openOMSI-Project/openOMSI)"

STREETS = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"


def _cached(key_text, cache, fetch, pause):
    os.makedirs(cache, exist_ok=True)
    key = os.path.join(cache, hashlib.sha1(key_text.encode()).hexdigest()[:16] + ".json")
    if os.path.isfile(key):
        return json.load(open(key, encoding="utf-8"))
    for attempt in range(9):
        try:
            data = fetch()
            json.dump(data, open(key, "w", encoding="utf-8"))
            time.sleep(pause)
            return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 10 * (attempt + 1)
            print(f"  waiting {wait} s ({e})", file=sys.stderr)
            time.sleep(wait)
    raise SystemExit("OpenStreetMap did not answer; try again later")


def overpass(query, cache, pause=6.0, fatal=True):
    """The answer (a dict with `elements`) of an Overpass query, from the cache when it was asked before. With fatal=False a
    query no mirror answers gives an empty answer (a sample is no reason to stop the run)."""
    if not fatal:
        try:
            return overpass(query, cache, pause, True)
        except SystemExit:
            return {"elements": []}
    state = {"i": 0}

    def fetch():
        # a busy server (504, 429) passes the query to the next mirror; the wait between attempts is in _cached
        url = OVERPASS_MIRRORS[state["i"] % len(OVERPASS_MIRRORS)]
        state["i"] += 1
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(), headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    return _cached(query, cache, fetch, pause)


def geocode(place, cache):
    """A place written by a person ("Szczecin, West Pomeranian, Poland") -> (lat, lon, (south, west, north, east), display name)."""
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": place, "format": "json", "limit": 1})

    def fetch():
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    res = _cached("nominatim:" + place, cache, fetch, 1.5)
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
