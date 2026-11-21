#!/usr/bin/env python3
"""SOLMARA poster renderer — pure Python 3.13 stdlib only.

Reads poster.png (1600x1600 RGB) from the same directory as this file,
resizes to 1024x1024, quantizes to a <=256-color palette via median cut,
and writes entry.png (palette PNG) to MAKEFUN_OUTPUT_DIR (default /output).

No third-party modules: only os, sys, struct, zlib, pathlib, collections.
"""
import os
import struct
import sys
import zlib
from pathlib import Path

SRC_NAME = "poster.png"
OUT_NAME = "entry.png"
OUT_W = 1024
OUT_H = 1024
MAX_BYTES = 1048576
MAX_COLORS = 256


def chunk(ctype, data):
    body = ctype + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def read_png(path):
    raw = Path(path).read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    width = height = None
    bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos < len(raw):
        (length,) = struct.unpack(">I", raw[pos:pos + 4])
        ctype = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _cm, _fm, interlace = struct.unpack(
                ">IIBBBBB", data)
        elif ctype == b"IDAT":
            idat += data
        elif ctype == b"IEND":
            break
    if width is None:
        raise ValueError("missing IHDR")
    if bit_depth != 8 or color_type != 2 or interlace != 0:
        raise ValueError(
            "unsupported PNG: bit_depth=%s color_type=%s interlace=%s"
            % (bit_depth, color_type, interlace))
    return width, height, zlib.decompress(bytes(idat))


def paeth(a, b, c):
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def unfilter(width, height, data):
    stride = width * 3
    rows = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        ftype = data[pos]
        raw = data[pos + 1:pos + 1 + stride]
        pos += 1 + stride
        recon = bytearray(stride)
        if ftype == 0:
            recon[:] = raw
        elif ftype == 1:
            for i in range(stride):
                left = recon[i - 3] if i >= 3 else 0
                recon[i] = (raw[i] + left) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                recon[i] = (raw[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = recon[i - 3] if i >= 3 else 0
                recon[i] = (raw[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = recon[i - 3] if i >= 3 else 0
                b = prev[i]
                c = prev[i - 3] if i >= 3 else 0
                recon[i] = (raw[i] + paeth(a, b, c)) & 0xFF
        else:
            raise ValueError("unknown filter type %d" % ftype)
        rows.append(bytes(recon))
        prev = recon
    return rows


def resize_nearest(rows, src_w, src_h, dst_w, dst_h):
    xs = [x * src_w // dst_w for x in range(dst_w)]
    ys = [y * src_h // dst_h for y in range(dst_h)]
    out = []
    for sy in ys:
        srow = rows[sy]
        out.append(b"".join(srow[3 * sx:3 * sx + 3] for sx in xs))
    return out


def median_cut_palette(rows, max_colors):
    hist = {}
    for row in rows:
        for i in range(0, len(row), 3):
            r = row[i]
            g = row[i + 1]
            b = row[i + 2]
            key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            cell = hist.get(key)
            if cell is None:
                hist[key] = [1, r, g, b]
            else:
                cell[0] += 1
                cell[1] += r
                cell[2] += g
                cell[3] += b
    keys = list(hist.keys())

    def box_stats(ks):
        rmin = gmin = bmin = 31
        rmax = gmax = bmax = 0
        total = 0
        for k in ks:
            total += hist[k][0]
            r5 = (k >> 10) & 31
            g5 = (k >> 5) & 31
            b5 = k & 31
            if r5 < rmin:
                rmin = r5
            if r5 > rmax:
                rmax = r5
            if g5 < gmin:
                gmin = g5
            if g5 > gmax:
                gmax = g5
            if b5 < bmin:
                bmin = b5
            if b5 > bmax:
                bmax = b5
        return (rmax - rmin, gmax - gmin, bmax - bmin), total

    boxes = [keys]
    stats = [box_stats(keys)]
    while len(boxes) < max_colors:
        best = -1
        best_score = -1
        for idx, (ranges, total) in enumerate(stats):
            if len(boxes[idx]) < 2:
                continue
            score = max(ranges) * 1000000 + total
            if score > best_score:
                best_score = score
                best = idx
        if best < 0:
            break
        ks = boxes[best]
        ranges, total = stats[best]
        chan = ranges.index(max(ranges))
        shift = (10, 5, 0)[chan]
        ks.sort(key=lambda k: (k >> shift) & 31)
        half = total // 2
        acc = 0
        cut = 1
        for n, k in enumerate(ks):
            acc += hist[k][0]
            if acc >= half and n + 1 < len(ks):
                cut = n + 1
                break
        else:
            cut = len(ks) - 1
        left = ks[:cut]
        right = ks[cut:]
        boxes[best] = left
        stats[best] = box_stats(left)
        boxes.append(right)
        stats.append(box_stats(right))

    palette = []
    lookup = {}
    for idx, ks in enumerate(boxes):
        cnt = 0
        rs = gs = bs = 0
        for k in ks:
            cell = hist[k]
            cnt += cell[0]
            rs += cell[1]
            gs += cell[2]
            bs += cell[3]
            lookup[k] = idx
        palette.append((
            min(255, (rs + cnt // 2) // cnt),
            min(255, (gs + cnt // 2) // cnt),
            min(255, (bs + cnt // 2) // cnt),
        ))
    return palette, lookup


def filter_row(row, prev, ftype):
    n = len(row)
    out = bytearray(n)
    if ftype == 0:
        out[:] = row
    elif ftype == 1:
        for i in range(n):
            left = row[i - 1] if i >= 1 else 0
            out[i] = (row[i] - left) & 0xFF
    elif ftype == 2:
        for i in range(n):
            out[i] = (row[i] - prev[i]) & 0xFF
    return bytes(out)


def row_score(fbytes):
    s = 0
    for v in fbytes:
        s += v if v < 128 else 256 - v
    return s


def encode_indexed_png(index_rows, palette):
    w = len(index_rows[0])
    h = len(index_rows)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0)
    plte = b"".join(bytes((r, g, b)) for (r, g, b) in palette)
    body = bytearray()
    prev = bytes(w)
    for row in index_rows:
        best_f = 0
        best_b = filter_row(row, prev, 0)
        best_s = row_score(best_b)
        for ftype in (1, 2):
            cand = filter_row(row, prev, ftype)
            sc = row_score(cand)
            if sc < best_s:
                best_s = sc
                best_f = ftype
                best_b = cand
        body.append(best_f)
        body += best_b
        prev = row
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", ihdr)
    png += chunk(b"PLTE", plte)
    png += chunk(b"IDAT", zlib.compress(bytes(body), 9))
    png += chunk(b"IEND", b"")
    return png


def main():
    here = Path(__file__).resolve().parent
    src = here / SRC_NAME
    out_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUT_NAME

    width, height, raw = read_png(src)
    print("source: %dx%d RGB" % (width, height), flush=True)
    rows = unfilter(width, height, raw)
    small = resize_nearest(rows, width, height, OUT_W, OUT_H)
    del rows, raw

    for ncolors in (256, 192, 128, 96, 64):
        palette, lookup = median_cut_palette(small, ncolors)
        index_rows = []
        for row in small:
            idx = bytearray(OUT_W)
            for x in range(OUT_W):
                i = 3 * x
                key = ((row[i] >> 3) << 10) | ((row[i + 1] >> 3) << 5) | (row[i + 2] >> 3)
                idx[x] = lookup[key]
            index_rows.append(bytes(idx))
        png = encode_indexed_png(index_rows, palette)
        print("palette %d colors -> %d bytes" % (len(palette), len(png)), flush=True)
        if len(png) <= MAX_BYTES:
            out_path.write_bytes(png)
            print("wrote %s (%dx%d, %d bytes)" % (out_path, OUT_W, OUT_H, len(png)), flush=True)
            return 0
    print("ERROR: output still over 1 MiB at 64 colors", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
