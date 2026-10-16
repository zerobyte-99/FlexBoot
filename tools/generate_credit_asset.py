#!/usr/bin/env python3
"""Render the gradient credit using the same bitmap glyphs as GRUB's footer."""
from __future__ import annotations

import argparse
from pathlib import Path
import struct
import zlib

ROOT = Path(__file__).resolve().parents[1]


def render(font: Path) -> None:
    from flexboot.branding import BRAND

    data = font.read_bytes()
    sections = {}
    offset = 0
    while offset + 8 <= len(data):
        name, size = struct.unpack_from('>4sI', data, offset)
        if name == b'DATA':
            break
        sections[name] = data[offset + 8:offset + 8 + size]
        offset += 8 + size
    if sections.get(b'FILE') != b'PFF2':
        raise ValueError('Expected a GRUB PF2 font')
    if sections[b'NAME'].rstrip(b'\0').decode() != BRAND.credit_font:
        raise ValueError('Credit font must match the configured GRUB footer font')
    if int.from_bytes(sections[b'PTSZ'], 'big') != int(BRAND.credit_font_size):
        raise ValueError('Credit size must match the GRUB font size')
    index = sections[b'CHIX']
    glyphs = {struct.unpack_from('>I', index, n)[0]: struct.unpack_from('>I', index, n + 5)[0]
              for n in range(0, len(index), 9)}
    width, height = int(BRAND.credit_canvas_width), int(BRAND.credit_canvas_height)
    colors = [tuple(bytes.fromhex(value.strip().lstrip('#'))) for value in BRAND.credit_gradient.split(',')]
    if len(colors) < 2 or any(len(color) != 3 for color in colors):
        raise ValueError('Expected at least two RGB gradient stops')
    pixels = bytearray(width * height * 4)
    letters = []
    for char in BRAND.credit_line:
        if ord(char) not in glyphs:
            raise ValueError(f'Missing font glyph: {char!r}')
        position = glyphs[ord(char)]
        w, h, x, y, advance = struct.unpack_from('>HHhhh', data, position)
        letters.append((w, h, x, y, advance, data[position + 10:position + 10 + (w * h + 7) // 8]))
    cursor = width - sum(letter[4] for letter in letters) - 3
    if cursor < 0:
        raise ValueError('Credit text exceeds its canvas width')
    baseline = int.from_bytes(sections[b'ASCE'], 'big')
    for w, h, x, y, advance, bitmap in letters:
        for row in range(h):
            for col in range(w):
                bit = row * w + col
                if not bitmap[bit // 8] & (128 >> (bit % 8)):
                    continue
                px, py = cursor + x + col, baseline - y - h + row
                if not (0 <= px < width and 0 <= py < height):
                    raise ValueError('Credit glyph exceeds its canvas')
                stop = px / (width - 1) * (len(colors) - 1)
                lo = min(int(stop), len(colors) - 2)
                fraction = stop - lo
                rgb = [round(a + (b - a) * fraction) for a, b in zip(colors[lo], colors[lo + 1])]
                start = (py * width + px) * 4
                pixels[start:start + 4] = bytes([*rgb, 255])
        cursor += advance

    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))

    rows = b''.join(b'\0' + pixels[row * width * 4:(row + 1) * width * 4] for row in range(height))
    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))
    for directory in (ROOT / 'flexboot/assets', ROOT / 'branding'):
        (directory / BRAND.credit_asset).write_bytes(png)


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, default=Path('/usr/share/grub/unicode.pf2'))
    render(parser.parse_args().font)
