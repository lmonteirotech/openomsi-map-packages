"""o3d.py - reads the vertices and triangles of an OMSI 2 `.o3d` mesh (the openOMSI reader `omsi_o3d::parse_o3d`, ported).

Only what the footprints need: positions and triangle indices, in the mesh's own frame (x right, y up, z forward; the
map's x east, y north is the mesh's x, z). Versions 1-7, 16 or 32 bit indices, and the per-vertex scrambling of the
protected files (version 4 and up with a key other than 0xFFFFFFFF) are handled the way openOMSI handles them."""
import math
import struct

import numpy as np


def _frac_byte(p):
    f = lambda x: x - math.trunc(x)
    prod = abs(f(p[0]) * f(p[1]) * f(p[2])) * 600.0
    return int(math.trunc(prod)) % 256


def _unscramble(s, p):
    if s < 1000:
        p[0], p[1] = p[1], p[0]
    elif s < 3000:
        p[0], p[2] = p[2], p[0]
    elif s > 7000:
        p[1], p[2] = p[2], p[1]


def parse_o3d(b):
    """(positions Nx3 float32, triangles Mx3 int) of a .o3d file, or None when it is not one."""
    if len(b) < 4 or b[0] != 0x84 or b[1] != 0x19:
        return None
    version = b[2]
    p = 3
    long_idx = alt = False
    if version >= 3:
        flags = b[p]
        p += 1
        long_idx, alt = bool(flags & 1), bool(flags & 2)
    key = 0
    if version >= 4:
        key, = struct.unpack_from("<I", b, p)
        p += 4
    scrambled = version >= 4 and key != 0xFFFFFFFF
    state = 0
    if scrambled:
        state = (key + (version - 4) + (0x17D if alt else 0)) % 0xFDE8
    wide = version >= 3
    pos = tris = None
    n_total = len(b)
    while p < n_total:
        tag = b[p]
        p += 1
        if tag == 0x17:
            n, = struct.unpack_from("<I" if wide else "<H", b, p)
            p += 4 if wide else 2
            if p + n * 32 > n_total:
                return None
            raw = np.frombuffer(b, "<f4", n * 8, p).reshape(n, 8)
            pos = raw[:, :3].astype(np.float32).copy()
            if scrambled:
                n16 = n % 0xFDE8
                fb = 0
                for i in range(n):
                    if key == 0:
                        state = 0x130 if alt else 0
                    state = (state * n16 + n16 * fb) % 8000
                    q = [float(raw[i, 0]), float(raw[i, 1]), float(raw[i, 2])]
                    fb = _frac_byte(q)
                    _unscramble(state, q)
                    pos[i] = q
            p += n * 32
        elif tag == 0x49:
            n, = struct.unpack_from("<I" if wide else "<H", b, p)
            p += 4 if wide else 2
            isz = 4 if long_idx else 2
            rec = 3 * isz + 2
            if p + n * rec > n_total:
                return None
            if long_idx:
                dt = np.dtype([("i", "<u4", 3), ("m", "<u2")])
            else:
                dt = np.dtype([("i", "<u2", 3), ("m", "<u2")])
            tris = np.frombuffer(b, dt, n, p)["i"].astype(np.int64)
            p += n * rec
        elif tag == 0x26:
            n, = struct.unpack_from("<H", b, p)
            p += 2
            for _ in range(n):
                p += 4 * 4 + 3 * 4 + 3 * 4 + 4
                ln = b[p]
                p += 1 + ln
        elif tag == 0x79:
            p += 64
        elif tag == 0x54:
            n, = struct.unpack_from("<H", b, p)
            p += 2
            for _ in range(n):
                ln = b[p]
                p += 1 + ln
                w, = struct.unpack_from("<H", b, p)
                p += 2 + w * ((4 if long_idx else 2) + 4)
        # any other byte is passed over, one at a time, as the game's loader does
    if pos is None or tris is None or not len(pos):
        return None
    ok = (tris < len(pos)).all(axis=1)
    return pos, tris[ok]
