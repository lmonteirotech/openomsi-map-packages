"""footprints.py - the outline of a building as the game draws it: from the mesh (.o3d) of its scenery object (.sco).

A tile file places an object by its file, a position and a heading. The .sco names its mesh(es) and groups; the mesh's
vertices say where the walls stand. The outline is the union of the mesh's triangles seen from above (the mesh's x and z
are the map's east and north), traced on a fine raster, simplified, and placed with the object's heading the way
openOMSI places it (heading degrees clockwise from north).

    fp = Footprints(omsi_folder)
    poly = fp.place("sceneryobjects/buildings_mc/bw_workshop_01.sco", x, y, heading)   # [(x, y), ...] or None
"""
import math
import os
import re

import contourpy
import numpy as np
from scipy import ndimage

import o3d
from geom import rdp_ring

BUILDING_GROUPS = r"build|geb|haus|house|resid|industr|commerc|gewerb|wohn|shop|church|kirche|school|hotel|tower|office|predio|edific|bud"
MIN_HEIGHT = 3.0          # a mesh lower than this (metres) is no building: a fence, a bench, a patch of grass
MIN_AREA = 8.0            # m2
MAX_CELLS = 360           # raster size of one outline; larger meshes get a coarser cell


def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace")
    return raw.decode("cp1252", "replace")


def parse_sco(path):
    """(mesh file names, group names) of a .sco."""
    t = [l.strip() for l in read_text(path).replace("\r", "").split("\n")]
    meshes, groups = [], []
    for i, l in enumerate(t):
        if l == "[mesh]" and i + 1 < len(t) and t[i + 1] and not t[i + 1].startswith("["):
            meshes.append(t[i + 1])
        elif l == "[groups]" and i + 1 < len(t):
            try:
                n = int(t[i + 1])
            except ValueError:
                continue
            groups += t[i + 2:i + 2 + n]
    return meshes, groups


def trace(pos, tris):
    """The outline (local metres) of a mesh seen from above, and its height; None for nothing building-like."""
    height = float(pos[:, 1].max() - pos[:, 1].min())
    xz = pos[:, [0, 2]].astype(np.float64)
    lo, hi = xz.min(axis=0), xz.max(axis=0)
    span = float(max(hi - lo))
    if height < MIN_HEIGHT or span < 1.0:
        return None
    cell = max(0.5, span / MAX_CELLS)
    W, H = int((hi[0] - lo[0]) / cell) + 3, int((hi[1] - lo[1]) / cell) + 3
    from PIL import Image, ImageDraw
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for t in tris:
        a, b, c = xz[t[0]], xz[t[1]], xz[t[2]]
        d.polygon([tuple((a - lo) / cell + 1), tuple((b - lo) / cell + 1), tuple((c - lo) / cell + 1)], fill=255)
    m = np.asarray(im) > 0
    m = ndimage.binary_closing(m, structure=np.ones((3, 3), bool))
    m = ndimage.binary_fill_holes(m)
    gen = contourpy.contour_generator(np.arange(W), np.arange(H), m.astype(np.float64), line_type=contourpy.LineType.Separate)
    best, best_area = None, 0.0
    for ring in gen.lines(0.5):
        r = np.asarray(ring)
        a = abs(0.5 * float(np.sum(r[:-1, 0] * r[1:, 1] - r[1:, 0] * r[:-1, 1])))
        if a > best_area:
            best, best_area = r, a
    if best is None or best_area * cell * cell < MIN_AREA:
        return None
    pts = (best[:, :2] - 1) * cell + lo
    pts = rdp_ring([(float(x), float(y)) for x, y in pts], max(0.4, cell * 0.8))
    return (pts, height) if len(pts) >= 3 else None


class Footprints:
    def __init__(self, omsi):
        self.omsi = omsi
        self.cache = {}          # sco -> (polygon, height, is_building) or None

    def _find(self, sco):
        p = os.path.join(self.omsi, sco.replace("/", os.sep))
        return p if os.path.isfile(p) else None

    def local(self, sco):
        if sco in self.cache:
            return self.cache[sco]
        out = None
        path = self._find(sco) if self.omsi else None
        if path:
            try:
                meshes, groups = parse_sco(path)
                parts_pos, parts_tri, off = [], [], 0
                base = os.path.dirname(path)
                for name in meshes[:4]:
                    for cand in (os.path.join(base, "model", name), os.path.join(base, name)):
                        if os.path.isfile(cand):
                            r = o3d.parse_o3d(open(cand, "rb").read())
                            if r:
                                parts_pos.append(r[0])
                                parts_tri.append(r[1] + off)
                                off += len(r[0])
                            break
                if parts_pos:
                    tr = trace(np.concatenate(parts_pos), np.concatenate(parts_tri))
                    if tr:
                        out = (tr[0], tr[1], bool(re.search(BUILDING_GROUPS, " ".join(groups).lower())))
            except (OSError, ValueError, IndexError):
                out = None
        self.cache[sco] = out
        return out

    def place(self, sco, x, y, heading):
        """The outline of an object standing at (x, y) with `heading` degrees clockwise from north, or None."""
        loc = self.local(sco)
        if not loc:
            return None
        h = math.radians(heading)
        c, s = math.cos(h), math.sin(h)
        return [(x + px * c + pz * s, y - px * s + pz * c) for px, pz in loc[0]]
