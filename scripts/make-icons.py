#!/usr/bin/env python3
"""V/HOME icon: black rounded tile with a glossy 3D purple blob (a recreation of the design Vineeth chose).
Stdlib only (no PIL on this Mac). Blob = metaball height field, lit from the upper left."""
import math, os, struct, zlib

# (cx, cy, semi_minor a, semi_major b, angle_deg from vertical, weight) in unit-tile coordinates
MAIN = [(0.63, 0.50, 0.165, 0.32, 17, 1.0), (0.38, 0.61, 0.10, 0.20, 24, 1.0)]
SAT = [(0.23, 0.72, 0.045, 0.08, 24, 1.0)]
K = 1.8  # higher = tighter lobes, deeper neck between them
T = math.exp(-K)
LIGHT = (-0.45, -0.62, 0.64)
DARK, LIT, SPEC = (70, 24, 140), (178, 134, 255), (255, 240, 255)

def _field(blobs, x, y):
    f = 0.0
    for cx, cy, a, b, ang, w in blobs:
        t = math.radians(ang); s, c = math.sin(t), math.cos(t)
        dx, dy = x - cx, y - cy
        u = dx * c - dy * s          # across the blob
        v = dx * s + dy * c          # along its long axis
        f += w * math.exp(-K * ((u / a) ** 2 + (v / b) ** 2))
    return f

def _height(blobs, x, y, top):
    d = _field(blobs, x, y) - T
    return 0.0 if d <= 0 else 0.15 * math.sqrt(min(1.0, d / (top - T)))

def _norm(v):
    n = math.sqrt(sum(c * c for c in v)); return tuple(c / n for c in v)

L = _norm(LIGHT)
H = _norm((L[0], L[1], L[2] + 1.0))

def _mix(a, b, t): return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

def blob_color(x, y):
    """RGB if (x, y) is on a blob, else None."""
    for blobs, top in ((MAIN, 1.5), (SAT, 1.0)):
        if _field(blobs, x, y) > T:
            e = 0.004
            zx = (_height(blobs, x + e, y, top) - _height(blobs, x - e, y, top)) / (2 * e)
            zy = (_height(blobs, x, y + e, top) - _height(blobs, x, y - e, top)) / (2 * e)
            n = _norm((-zx, -zy, 1.0))
            diff = max(0.0, sum(n[i] * L[i] for i in range(3)))
            spec = max(0.0, sum(n[i] * H[i] for i in range(3))) ** 38
            col = _mix(DARK, LIT, diff ** 0.85)
            return _mix(col, SPEC, min(1.0, spec * 0.7))
    return None

def in_tile(x, y, r=0.23):
    dx = max(r - x, 0, x - (1 - r)); dy = max(r - y, 0, y - (1 - r))
    return 0 <= x <= 1 and 0 <= y <= 1 and dx * dx + dy * dy <= r * r

def render(size):
    ss = 2 if size >= 400 else 3 if size >= 150 else 5
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(ss):
                for sx in range(ss):
                    x, y = (px + (sx + .5) / ss) / size, (py + (sy + .5) / ss) / size
                    if not in_tile(x, y): continue
                    c = blob_color(x, y) or (0, 0, 0)
                    r += c[0]; g += c[1]; b += c[2]; a += 1
            n = ss * ss
            row += bytes((0, 0, 0, 0)) if a == 0 else bytes((round(r / a), round(g / a), round(b / a), round(255 * a / n)))
        rows.append(row)
    return rows

def write_png(path, w, h, rows):
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, size in {'webos/icon.png': 80, 'webos/largeIcon.png': 130, 'public/icons/icon-192.png': 192,
                      'public/icons/icon-512.png': 512, 'public/icons/apple-touch-icon.png': 180}.items():
        write_png(os.path.join(root, rel), size, size, render(size)); print('wrote', rel, size)
