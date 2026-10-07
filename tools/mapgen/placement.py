#!/usr/bin/env python3
"""placement.py - where a map lies on the globe.

Two kinds of placement, with the same four calls the surface writer needs (`to_author`, `latlon_xy`, `latlon_arr`,
`covered`):

  WorldPlacement   a map with `[worldcoordinates]`: its tile index IS the place on the globe (web-mercator tiles).
  FittedPlacement  any other map (or a world map that is a little off): a similarity (scale, turn, shift) found from the
                   stops, with, if asked, a smooth local correction (`field`) found from the roads. See locate.py.

Positions of the map are metres of the author's tile grid: x = tile column * grid + place in the tile.
"""
import math

import numpy as np
from scipy.interpolate import RBFInterpolator, RegularGridInterpolator

M_LAT = 111320.0          # metres of a degree of latitude


def read_global(path):
    raw = open(path, "rb").read()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("cp1252")
    lines = [l.strip() for l in text.replace("\r", "").split("\n")]
    tiles = []
    for i, l in enumerate(lines):
        if l.lower() == "[map]":
            try:
                tiles.append((int(lines[i + 1]), int(lines[i + 2])))
            except (ValueError, IndexError):
                pass
    world = any(l.lower() == "[worldcoordinates]" for l in lines)
    return tiles, world


def row_width(ty):
    """Width of a web-mercator zoom-16 tile row's lower edge (m), as openOMSI computes it."""
    lat = 2 * math.atan(math.exp(2 * math.pi * ty / 65536)) - math.pi / 2
    return 40075016.69 * math.cos(lat) / 65536


def tile_size(rows):
    rows = sorted(rows)
    r = rows[len(rows) // 2]
    return (row_width(r) + row_width(r + 1)) / 2


def tile_to_latlon(tx, ty, lx, ly):
    w0, w1 = row_width(ty), row_width(ty + 1)
    lon = ((tx + 32768) + lx / ((w0 + w1) / 2)) / 65536 * 360 - 180
    row = ty + ly / w1
    return math.degrees(2 * math.atan(math.exp(2 * math.pi * row / 65536)) - math.pi / 2), lon




class Field:
    """A smooth correction [x, y, dx, dy] of the map's metres (thin-plate spline through the control points)."""
    smoothing = 2.0e3

    def __init__(self, pts):
        self.pts = np.asarray(pts, float).reshape(-1, 4)
        self.rbf = None
        if len(self.pts) >= 4:
            self.rbf = RBFInterpolator(self.pts[:, :2], self.pts[:, 2:], kernel="thin_plate_spline", smoothing=Field.smoothing)

    def __call__(self, x, y):
        if self.rbf is None:
            return np.zeros_like(x), np.zeros_like(y)
        d = self.rbf(np.column_stack([np.ravel(x), np.ravel(y)]))
        d = np.clip(d, -6000.0, 6000.0)
        return d[:, 0].reshape(np.shape(x)), d[:, 1].reshape(np.shape(y))


def sim(cal, x, y):
    """East and north metres (from lat0, lon0) of map metres, by the similarity of a calibration."""
    return cal["a"] * x - cal["b"] * y + cal["tx"], cal["b"] * x + cal["a"] * y + cal["ty"]


def sim_inv(cal, e, n):
    det = cal["a"] ** 2 + cal["b"] ** 2
    e, n = e - cal["tx"], n - cal["ty"]
    return (cal["a"] * e + cal["b"] * n) / det, (-cal["b"] * e + cal["a"] * n) / det


def en_of(cal, pts):
    """The same for an array of points [[x, y], ...]."""
    z = (cal["a"] + 1j * cal["b"]) * (pts[:, 0] + 1j * pts[:, 1]) + (cal["tx"] + 1j * cal["ty"])
    return np.column_stack([z.real, z.imag])


def m_lon(lat0):
    return M_LAT * math.cos(math.radians(lat0))



class WorldPlacement:
    """latitude/longitude -> metres of the author's grid (tile column * grid + place in the tile)."""

    def __init__(self, tiles, all_tiles=None):
        self.tiles = set(tiles)
        # the grid is laid out by ALL the map's tiles (the game does); a part of them only says where the map is
        self.ts = tile_size([t[1] for t in (all_tiles or tiles)])

    def to_author(self, lat, lon):
        col = (lon + 180) / 360 * 65536
        tx = math.floor(col) - 32768
        fx = col - math.floor(col)
        rowf = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * 65536 / (2 * math.pi)
        ty = math.floor(rowf)
        fy = rowf - ty
        w0, w1 = row_width(ty), row_width(ty + 1)
        return tx * self.ts + fx * (w0 + w1) / 2, ty * self.ts + fy * w1

    def covered(self, ax, ay, margin=1):
        tx, ty = math.floor(ax / self.ts), math.floor(ay / self.ts)
        return any((tx + dx, ty + dy) in self.tiles for dx in range(-margin, margin + 1) for dy in range(-margin, margin + 1))

    def latlon(self, tx, ty, lx=0.0, ly=0.0):
        return tile_to_latlon(tx, ty, lx, ly)

    def latlon_xy(self, x, y):
        tx, ty = int(x // self.ts), int(y // self.ts)
        return tile_to_latlon(tx, ty, x - tx * self.ts, y - ty * self.ts)


class FittedPlacement:
    """A map placed by a calibration dict: a, b, tx, ty, lat0, lon0 and, optionally, field."""

    def __init__(self, tiles, grid, cal):
        self.tiles, self.ts, self.cal = set(tiles), grid, cal
        self.det = cal["a"] ** 2 + cal["b"] ** 2
        self.gi = None
        if cal.get("field"):
            # the local correction of refine_calibration.py, read from a grid of 60 m (a spline over the points is slow)
            f = Field(cal["field"])
            pts = np.asarray(cal["field"], float)
            xs = np.arange(pts[:, 0].min() - 2500, pts[:, 0].max() + 2500, 60.0)
            ys = np.arange(pts[:, 1].min() - 2500, pts[:, 1].max() + 2500, 60.0)
            gx, gy = np.meshgrid(xs, ys)
            dx, dy = f(gx, gy)
            self.gi = (RegularGridInterpolator((ys, xs), dx, bounds_error=False, fill_value=None), RegularGridInterpolator((ys, xs), dy, bounds_error=False, fill_value=None))

    def _d(self, x, y):
        if self.gi is None:
            return 0.0 * np.asarray(x, float), 0.0 * np.asarray(y, float)
        p = np.column_stack([np.ravel(y), np.ravel(x)])
        return self.gi[0](p).reshape(np.shape(x)), self.gi[1](p).reshape(np.shape(y))

    def latlon(self, tx, ty, lx=0.0, ly=0.0):
        return self.latlon_xy(tx * self.ts + lx, ty * self.ts + ly)

    def latlon_xy(self, x, y):
        dx, dy = self._d(x, y)
        x, y = x + dx, y + dy
        c = self.cal
        e = c["a"] * x - c["b"] * y + c["tx"]
        n = c["b"] * x + c["a"] * y + c["ty"]
        return float(c["lat0"] + n / 111320.0), float(c["lon0"] + e / (111320.0 * math.cos(math.radians(c["lat0"]))))

    def latlon_arr(self, x, y):
        dx, dy = self._d(x, y)
        x, y = x + dx, y + dy
        c = self.cal
        e = c["a"] * x - c["b"] * y + c["tx"]
        n = c["b"] * x + c["a"] * y + c["ty"]
        return c["lat0"] + n / 111320.0, c["lon0"] + e / (111320.0 * math.cos(math.radians(c["lat0"])))

    def to_author(self, lat, lon):
        c = self.cal
        e = (lon - c["lon0"]) * 111320.0 * math.cos(math.radians(c["lat0"])) - c["tx"]
        n = (lat - c["lat0"]) * 111320.0 - c["ty"]
        x0, y0 = (c["a"] * e + c["b"] * n) / self.det, (-c["b"] * e + c["a"] * n) / self.det
        x, y = x0, y0
        for _ in range(3):          # the correction is smooth: x + d(x) = x0 is found by a few steps
            dx, dy = self._d(x, y)
            x, y = x0 - float(dx), y0 - float(dy)
        return x, y

    def covered(self, ax, ay, margin=1):
        tx, ty = math.floor(ax / self.ts), math.floor(ay / self.ts)
        return any((tx + dx, ty + dy) in self.tiles for dx in range(-margin, margin + 1) for dy in range(-margin, margin + 1))


