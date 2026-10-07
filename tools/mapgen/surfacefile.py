#!/usr/bin/env python3
"""surfacefile.py - reads and writes surface.oms (OMSF v1, docs/MAP_PACKAGE.md section 4) whole, in memory.

A surface is {ver, origin, chunk, names, chunks}; chunks[(cx, cy)] = (fills, lines, labels) with
fills = {class: flat [x0, y0, x1, y1, x2, y2, ...]}, lines = [(class, flags, width, name, flat [x, y, ...])],
labels = [(kind, rank, name, x, y)]. Used by the checks and by the repair of a shore (check.py)."""
import struct


def read_surface(path):
    b = open(path, "rb").read()
    assert b[:4] == b"OMSF"
    ver, = struct.unpack_from("<I", b, 4)
    ox, oy = struct.unpack_from("<dd", b, 8)
    pos = 24
    bounds = struct.unpack_from("<ffff", b, pos)
    chunk, = struct.unpack_from("<f", b, pos + 16)
    pos += 20
    n, = struct.unpack_from("<I", b, pos)
    pos += 4
    names = []
    for _ in range(n):
        ln, = struct.unpack_from("<H", b, pos)
        names.append(b[pos + 2:pos + 2 + ln].decode("utf-8"))
        pos += 2 + ln
    nc, = struct.unpack_from("<I", b, pos)
    pos += 4
    index = [struct.unpack_from("<iiQI", b, pos + 20 * i) for i in range(nc)]
    chunks = {}
    for cx, cy, off, ln in index:
        p = off
        nf, = struct.unpack_from("<I", b, p)
        p += 4
        fills = {}
        for _ in range(nf):
            cls, nt = struct.unpack_from("<BI", b, p)
            p += 5
            fills[cls] = list(struct.unpack_from("<%df" % (6 * nt), b, p))
            p += 24 * nt
        nl, = struct.unpack_from("<I", b, p)
        p += 4
        lines = []
        for _ in range(nl):
            cls, fl, w, nm, npt = struct.unpack_from("<BBfII", b, p)
            p += 14
            pts = list(struct.unpack_from("<%df" % (2 * npt), b, p))
            p += 8 * npt
            lines.append((cls, fl, w, nm, pts))
        nlb, = struct.unpack_from("<I", b, p)
        p += 4
        labels = [struct.unpack_from("<BBIff", b, p + 14 * i) for i in range(nlb)]
        chunks[(cx, cy)] = (fills, lines, labels)
    return dict(ver=ver, origin=(ox, oy), chunk=chunk, names=names, chunks=chunks)


def write_surface(s, path):
    CH = s["chunk"]
    bodies = {}
    for k, (fills, lines, labels) in s["chunks"].items():
        b = bytearray()
        b += struct.pack("<I", len(fills))
        for cls, tri in sorted(fills.items()):
            b += struct.pack("<BI", cls, len(tri) // 6) + struct.pack("<%df" % len(tri), *tri)
        b += struct.pack("<I", len(lines))
        for cls, fl, w, nm, pts in lines:
            b += struct.pack("<BBfII", cls, fl, w, nm, len(pts) // 2) + struct.pack("<%df" % len(pts), *pts)
        b += struct.pack("<I", len(labels))
        for kind, rank, nm, x, y in labels:
            b += struct.pack("<BBIff", kind, rank, nm, x, y)
        bodies[k] = bytes(b)
    head = bytearray(b"OMSF") + struct.pack("<I", s["ver"]) + struct.pack("<dd", *s["origin"])
    xs = [k[0] for k in bodies]
    ys = [k[1] for k in bodies]
    head += struct.pack("<ffff", min(xs) * CH, (max(xs) + 1) * CH, min(ys) * CH, (max(ys) + 1) * CH) + struct.pack("<f", CH)
    head += struct.pack("<I", len(s["names"]))
    for n in s["names"]:
        e = n.encode("utf-8")
        head += struct.pack("<H", len(e)) + e
    order = sorted(bodies)
    head += struct.pack("<I", len(order))
    pos, idx = len(head) + 20 * len(order), bytearray()
    for k in order:
        idx += struct.pack("<iiQI", k[0], k[1], pos, len(bodies[k]))
        pos += len(bodies[k])
    open(path, "wb").write(bytes(head) + bytes(idx) + b"".join(bodies[k] for k in order))
