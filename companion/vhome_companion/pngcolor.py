"""Dominant edge colour of an app icon (stdlib only), used as the launcher tile background.

Only 8-bit, non-interlaced PNGs are decoded; anything else returns None (the TV then uses a neutral tint)."""
import struct
import zlib

_CH = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _decode(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, plte, hdr = 8, [], b"", None
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if not hdr or not idat:
        return None
    w, h, depth, ctype, _, _, interlace = hdr
    if depth != 8 or interlace != 0 or ctype not in _CH or w * h > 1_000_000 or (ctype == 3 and not plte):
        return None
    ch = _CH[ctype]
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    if len(raw) < h * (stride + 1):
        return None
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
            elif f != 0:
                return None
        rows.append(line)
        prev = line

    def px(x, y):  # -> (r, g, b, a)
        p = rows[y]
        if ctype == 6:
            return p[x * 4], p[x * 4 + 1], p[x * 4 + 2], p[x * 4 + 3]
        if ctype == 2:
            return p[x * 3], p[x * 3 + 1], p[x * 3 + 2], 255
        if ctype == 0:
            return p[x], p[x], p[x], 255
        if ctype == 4:
            return p[x * 2], p[x * 2], p[x * 2], p[x * 2 + 1]
        i = p[x] * 3
        return plte[i], plte[i + 1], plte[i + 2], 255
    return w, h, px


def edge_color(data):
    """'#rrggbb' from the icon's border ring, or None. Opaque border pixels win; a mostly transparent
    border (line icons) is averaged over white so dark glyphs stay readable."""
    try:
        d = _decode(data)
        if not d:
            return None
        w, h, px = d
        t = max(2, min(w, h) // 32)
        ring = [px(x, y) for y in range(h) for x in range(w) if x < t or y < t or x >= w - t or y >= h - t]
        solid = [p for p in ring if p[3] >= 200]
        use = solid if len(solid) >= len(ring) * 0.15 else [tuple((c * p[3] + 255 * (255 - p[3])) // 255 for c in p[:3]) + (255,) for p in ring]
        r, g, b = (sum(p[i] for p in use) // len(use) for i in range(3))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return None
