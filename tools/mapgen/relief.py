#!/usr/bin/env python3
"""Contour lines of the REAL terrain (heights above sea level), not of the map's own height files.

The relief is the real one for the map's area, everywhere, with or without tiles, splines or streets: it comes from the
Terrarium elevation tiles (public, built from SRTM and other models, 256 x 256 px, the height in the colour:
R * 256 + G + B / 256 - 32768 m) that Mapzen's terrain data offers on AWS Open Data. The tiles needed (zoom 12, about
25-35 m a pixel) are fetched once and kept in a cache folder.

The area is laid on the map's own grid (a point of the author's grid, in metres, is turned into latitude and longitude
by the map's georeference), the heights are read there (bilinear, smoothed a little) and the lines are traced with
contourpy. Same result as terrain_contours.contours: [(height, is_index, [(x, y), ...])].
"""
import io
import math
import os
import time
import urllib.request

import numpy as np
from scipy import ndimage
import contourpy

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
Z = 12


def _tile_xy(lat, lon, z=Z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _fetch(z, x, y, cache):
    from PIL import Image
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"{z}_{x}_{y}.png")
    if not os.path.isfile(path):
        for attempt in range(5):
            try:
                data = urllib.request.urlopen(urllib.request.Request(URL.format(z=z, x=x, y=y), headers={"User-Agent": "openomsi-map-package-generator/1.0"}), timeout=60).read()
                open(path, "wb").write(data)
                break
            except Exception as e:
                print("  terrain tile:", e)
                time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("terrain tiles: no answer, try again later")
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)
    return a[..., 0] * 256.0 + a[..., 1] + a[..., 2] / 256.0 - 32768.0


class Dem:
    """The elevation model over a region, read at latitudes and longitudes."""

    def __init__(self, south, west, north, east, cache):
        x0, y1 = _tile_xy(south, west)
        x1, y0 = _tile_xy(north, east)
        self.tx0, self.ty0 = int(math.floor(x0)) - 1, int(math.floor(y0)) - 1
        tx1, ty1 = int(math.floor(x1)) + 1, int(math.floor(y1)) + 1
        W, H = (tx1 - self.tx0 + 1) * 256, (ty1 - self.ty0 + 1) * 256
        self.z = np.zeros((H, W), dtype=np.float64)
        n = (tx1 - self.tx0 + 1) * (ty1 - self.ty0 + 1)
        k = 0
        for ty in range(self.ty0, ty1 + 1):
            for tx in range(self.tx0, tx1 + 1):
                k += 1
                print(f"terrain tile {k}/{n} ...", flush=True)
                self.z[(ty - self.ty0) * 256:(ty - self.ty0 + 1) * 256, (tx - self.tx0) * 256:(tx - self.tx0 + 1) * 256] = _fetch(Z, tx, ty, cache)

    def at(self, lat, lon):
        lat, lon = np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        n = 2 ** Z
        x = ((lon + 180.0) / 360.0 * n - self.tx0) * 256.0
        y = ((1.0 - np.arcsinh(np.tan(np.radians(lat))) / math.pi) / 2.0 * n - self.ty0) * 256.0
        return ndimage.map_coordinates(self.z, [y - 0.5, x - 0.5], order=1, mode="nearest")


def contours(bounds, latlon, interval=5.0, step=40.0, cache="dem-cache", simplify=4.0, index_every=None):
    """Contour lines over `bounds` = (x0, x1, y0, y1) in metres of the author's grid. `latlon(x, y)` turns arrays of those
    into arrays of latitude and longitude. `step`: metres between the points the heights are read at."""
    x0, x1, y0, y1 = bounds
    xs = np.arange(x0, x1 + step, step)
    ys = np.arange(y0, y1 + step, step)
    gx, gy = np.meshgrid(xs, ys)
    lat, lon = latlon(gx.ravel(), gy.ravel())
    lat, lon = np.asarray(lat).reshape(gx.shape), np.asarray(lon).reshape(gx.shape)
    dem = Dem(float(lat.min()), float(lon.min()), float(lat.max()), float(lon.max()), cache)
    z = dem.at(lat, lon)
    z = ndimage.uniform_filter(z, size=3, mode="nearest")        # the model is noisy at a few metres
    gen = contourpy.contour_generator(xs, ys, z, line_type=contourpy.LineType.Separate)
    lo, hi = float(z.min()), float(z.max())
    every = index_every or (5.0 if interval <= 1.0 else interval * 5.0)
    out = []
    for k in range(int(math.ceil(lo / interval)), int(math.floor(hi / interval)) + 1):
        level = k * interval
        index = abs(level / every - round(level / every)) < 1e-6
        for line in gen.lines(level):
            pts = [(float(a), float(b)) for a, b in line]
            if simplify and len(pts) > 2:
                pts = _rdp(pts, simplify)
            if len(pts) >= 2:
                out.append((level, index, pts))
    print(f"relief: {len(out)} lines, heights {lo:.0f}..{hi:.0f} m above sea level")
    return out


def _rdp(pts, eps):
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
            d = math.hypot(px - ax, py - ay) if d2 == 0 else math.hypot(px - ax - max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2)) * dx, py - ay - max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2)) * dy)
            if d > best:
                best, bi = d, i
        if best > eps and bi >= 0:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]
