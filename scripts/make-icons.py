#!/usr/bin/env python3
"""V/HOME icons: warm charcoal tile, amber arched window, sage horizon. Stdlib only (no PIL on this Mac)."""
import os, struct, zlib

SS = 4  # supersampling per axis
CHAR, AMBER, SAGE, PANE = (28, 25, 23), (224, 164, 88), (156, 175, 136), (41, 37, 36)

def write_png(path, w, h, rows):
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        return c + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + bytes(r) for r in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

def in_round_rect(x, y, r):
    # unit square with corner radius r
    dx = max(r - x, 0, x - (1 - r)); dy = max(r - y, 0, y - (1 - r))
    return dx * dx + dy * dy <= r * r and 0 <= x <= 1 and 0 <= y <= 1

def in_arch(x, y, cx, half, top, bottom):
    """Arch: semicircle of radius `half` whose top is at `top`, straight sides down to `bottom`."""
    cy = top + half
    if y > bottom or y < top or abs(x - cx) > half: return False
    return y >= cy or (x - cx) ** 2 + (y - cy) ** 2 <= half * half

def sample(x, y):
    """Returns (r, g, b, a) for a unit-square point."""
    if not in_round_rect(x, y, 0.22): return (0, 0, 0, 0)
    col = CHAR
    if in_arch(x, y, 0.5, 0.21, 0.20, 0.72): col = AMBER                      # frame
    if in_arch(x, y, 0.5, 0.21 - 0.045, 0.20 + 0.045, 0.72 - 0.045): col = PANE  # glass
    if abs(x - 0.5) <= 0.016 and 0.245 <= y <= 0.675: col = AMBER              # mullion
    if abs(y - 0.50) <= 0.016 and 0.30 <= x <= 0.70: col = AMBER               # transom
    if 0.19 <= x <= 0.81 and 0.735 <= y <= 0.775: col = SAGE                   # horizon
    return col + (255,)

def render(size):
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    r, g, b, a = sample((px + (sx + .5) / SS) / size, (py + (sy + .5) / SS) / size)
                    acc[0] += r * a; acc[1] += g * a; acc[2] += b * a; acc[3] += a
            a = acc[3]
            row += bytes((0, 0, 0, 0)) if a == 0 else bytes((round(acc[0] / a), round(acc[1] / a), round(acc[2] / a), round(a / (SS * SS))))
        rows.append(row)
    return rows

if __name__ == '__main__':
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    targets = {'webos/icon.png': 80, 'webos/largeIcon.png': 130, 'public/icons/icon-192.png': 192,
               'public/icons/icon-512.png': 512, 'public/icons/apple-touch-icon.png': 180}
    for rel, size in targets.items():
        write_png(os.path.join(root, rel), size, size, render(size)); print('wrote', rel, size)
