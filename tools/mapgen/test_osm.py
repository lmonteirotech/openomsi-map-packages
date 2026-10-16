"""test_osm.py - the network layer of osm.py without a network: servers that fail, rest, come back; the pauses; the forecast; the place search.
Run: python test_osm.py (the clock is a fake one: nothing waits)."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

import osm


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


class Resp:
    def __init__(self, obj, clock=None, took=0.0):
        self.b = json.dumps(obj).encode()
        self.clock, self.took = clock, took

    def read(self, *a):
        if self.clock:
            self.clock.now += self.took
        return self.b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http(url, code, retry_after=None):
    h = {"Retry-After": str(retry_after)} if retry_after else {}
    return urllib.error.HTTPError(url, code, "x", h, io.BytesIO(b""))


class NetTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        osm.time = self.clock
        osm.NET = osm.Net()
        osm.NET.out = lambda s: self.log.append(s)
        self.log, self.calls = [], []
        self.cache = tempfile.mkdtemp()
        self.script = {}                       # host -> list of outcomes (exception or answer), used in order

        def fake(req, timeout=0):
            url = req.full_url
            host = url.split("/")[2]
            self.calls.append((self.clock.now, host))
            out = self.script[host].pop(0) if self.script.get(host) else {"elements": [{"id": 1}]}
            if isinstance(out, BaseException):
                raise out
            return Resp(out, self.clock, 6.0)
        osm.urllib.request.urlopen = fake

    def test_the_next_mirror_gets_the_query_at_once(self):
        m = list(osm.NET.mirrors)
        self.script = {"overpass-api.de": [http(m[0], 504)], "maps.mail.ru": [http(m[1], 500)], "overpass.private.coffee": [TimeoutError()]}
        data = osm.overpass("q1", self.cache)
        self.assertEqual(data["elements"][0]["id"], 1)
        self.assertEqual([h for _, h in self.calls], ["overpass-api.de", "maps.mail.ru", "overpass.private.coffee", "overpass.kumi.systems"])
        self.assertEqual(osm.NET.mirrors[0], "https://overpass.kumi.systems/api/interpreter")        # the one that answered goes first
        self.assertTrue(all(x < 30 for x in self.clock.slept), self.clock.slept)                  # no long wait: there was always another server

    def test_a_resting_mirror_is_left_alone_and_comes_back(self):
        m = list(osm.NET.mirrors)
        self.script = {h: [http(m[i], 504)] for i, h in enumerate(["overpass-api.de", "maps.mail.ru", "overpass.private.coffee", "overpass.kumi.systems"])}
        osm.overpass("q2", self.cache)
        self.assertTrue(any("resting" in l for l in self.log), self.log)                          # all four rested: it waited, then asked again
        self.assertEqual(len(self.calls), 5)
        self.assertGreaterEqual(self.calls[-1][0] - self.calls[0][0], osm.COOLDOWN - 1)

    def test_retry_after_is_obeyed(self):
        first = osm.NET.mirrors[0]
        self.script = {"overpass-api.de": [http(first, 429, 120)]}
        osm.overpass("q3", self.cache)
        self.assertGreaterEqual(osm.NET.rest_until[first] - self.clock.now, 100)

    def test_pause_between_queries(self):
        osm.overpass("a", self.cache)
        osm.overpass("b", self.cache)
        osm.overpass("c", self.cache)
        starts = [t for t, _ in self.calls]
        # each query takes 6 s: the next one starts at least 1.5 x 6 = 9 s after the last one ended (more than the 5 s floor)
        self.assertGreaterEqual(starts[1] - (starts[0] + 6), 9 - 0.01)
        self.assertGreaterEqual(starts[2] - (starts[1] + 6), 9 - 0.01)

    def test_cached_queries_ask_nothing_and_the_plan_counts(self):
        osm.overpass("done", self.cache)
        n = len(self.calls)
        osm.overpass("done", self.cache)
        self.assertEqual(len(self.calls), n)
        todo = osm.plan(["done", "new1", "new2", "new3"], self.cache)
        self.assertEqual(todo, 3)
        self.assertTrue(any("3 of 4 queries still to ask" in l and "expect about" in l for l in self.log), self.log)
        osm.overpass("new1", self.cache)
        self.assertTrue(any("query 1/3" in l and "left" in l for l in self.log), self.log)

    def test_the_options(self):
        osm.configure(["https://my.server/api/interpreter"], 12)
        self.assertEqual(osm.NET.mirrors[0], "https://my.server/api/interpreter")
        self.assertEqual(osm.NET.min_pause, 12.0)
        self.assertEqual(len(osm.NET.mirrors), 5)

    def test_all_down_stops_with_an_explanation(self):
        def down(req, timeout=0):
            raise http(req.full_url, 503)
        osm.urllib.request.urlopen = down
        with self.assertRaises(SystemExit) as c:
            osm.overpass("never", self.cache)
        self.assertIn("--overpass", str(c.exception))
        self.assertEqual(osm.overpass("never", self.cache, fatal=False), {"elements": []})

    def test_the_place_search_falls_back_to_photon(self):
        def fake(req, timeout=0):
            url = req.full_url
            self.calls.append((self.clock.now, url.split("/")[2]))
            if "nominatim" in url:
                raise http(url, 500)
            return Resp({"features": [{"geometry": {"coordinates": [14.55, 53.43]}, "properties": {"name": "Szczecin", "country": "Poland", "extent": [14.4, 53.5, 14.7, 53.35]}}]})
        osm.urllib.request.urlopen = fake
        lat, lon, box, shown = osm.geocode("Szczecin, Poland", self.cache)
        self.assertAlmostEqual(lat, 53.43)
        self.assertEqual(box, (53.35, 14.4, 53.5, 14.7))
        self.assertIn("Szczecin", shown)
        self.assertIn("photon.komoot.io", [h for _, h in self.calls])
        gaps = [b[0] - a[0] for a, b in zip(self.calls, self.calls[1:]) if a[1] == b[1] == "nominatim.openstreetmap.org"]
        self.assertTrue(all(g >= 1.5 - 0.01 for g in gaps), gaps)                                  # one request a second at most

    def test_the_forecast_text(self):
        self.assertEqual(osm.fmt_time(45), "45 s")
        self.assertEqual(osm.fmt_time(600), "10 min")
        self.assertEqual(osm.fmt_time(7500), "2 h 05 min")


if __name__ == "__main__":
    unittest.main(verbosity=2)
