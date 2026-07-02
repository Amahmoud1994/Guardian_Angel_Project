"""
setup_icons.py — Run once to create Guardian Angel PWA icons.
No third-party dependencies — pure Python stdlib.
Usage: py setup_icons.py
"""
import os
import struct
import zlib

def create_png(size):
    """Create a dark-background PNG with the Guardian Angel ring + dot."""
    bg  = (10,  13,  15)   # --bg color
    ring = (0, 229, 160)   # --accent green
    dot  = (0, 180, 120)   # slightly darker green for dot

    cx = cy = size / 2
    outer = size * 0.40
    inner = size * 0.28
    dot_r = size * 0.11

    rows = []
    for y in range(size):
        row = bytearray([0])   # filter byte: None
        for x in range(size):
            dx = x - cx + 0.5
            dy = y - cy + 0.5
            d  = (dx * dx + dy * dy) ** 0.5
            if d <= dot_r:
                row.extend(dot)
            elif inner <= d <= outer:
                # anti-alias the edges slightly
                t = min(1.0, max(0.0, min(d - inner, outer - d) / 1.5))
                r = int(bg[0] + t * (ring[0] - bg[0]))
                g = int(bg[1] + t * (ring[1] - bg[1]))
                b = int(bg[2] + t * (ring[2] - bg[2]))
                row.extend((r, g, b))
            else:
                row.extend(bg)
        rows.append(bytes(row))

    raw = b''.join(rows)

    def chunk(name, data):
        crc = zlib.crc32(name + data) & 0xffffffff
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', crc)

    sig  = b'\x89PNG\r\n\x1a\n'
    ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0))
    idat = chunk(b'IDAT', zlib.compress(raw, 9))
    iend = chunk(b'IEND', b'')
    return sig + ihdr + idat + iend


if __name__ == '__main__':
    os.makedirs('icons', exist_ok=True)
    for size in [72, 96, 128, 144, 152, 192, 384, 512]:
        data = create_png(size)
        path = f'icons/icon-{size}.png'
        with open(path, 'wb') as f:
            f.write(data)
        print(f'  created {path} ({len(data):,} bytes)')
    print('Done. Icons are in ./icons/')
