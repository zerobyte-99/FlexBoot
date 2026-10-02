#!/usr/bin/env python3
"""Generate FlexBoot's code-drawn UI assets with the standard library."""
from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def png(path: Path, width: int, height: int, pixels: bytes, *, channels: int = 3) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)

    color_type = {3: 2, 4: 6}[channels]
    stride = width * channels
    rows = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    payload = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def classic_background() -> bytes:
    width, height = 1920, 1080
    data = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            vignette = int(9 * (((x - width / 2) / width) ** 2 + ((y - height / 2) / height) ** 2))
            base = max(13, 25 - vignette)
            color = (base, base + 3, base + 7)
            if (x + y) % 160 == 0 or (x - y) % 240 == 0:
                color = (36, 38, 41)
            i = (y * width + x) * 3
            data[i:i + 3] = bytes(color)
    return bytes(data)


def logo() -> bytes:
    width = height = 256
    data = bytearray(width * height * 4)
    amber = (217, 139, 58, 255)
    pale = (239, 235, 225, 255)
    for y in range(height):
        for x in range(width):
            stem = 50 <= x <= 88 and 42 <= y <= 214
            top = 88 <= x <= 190 and 42 <= y <= 78
            middle = 88 <= x <= 164 and 108 <= y <= 142
            arrow = 142 <= x <= 205 and abs(y - 176) <= (x - 142) // 2
            if stem or top or middle or arrow:
                i = (y * width + x) * 4
                data[i:i + 4] = bytes(amber if arrow or y > 105 else pale)
    return bytes(data)


def selection_piece(name: str) -> bytes:
    width = height = 8
    data = bytearray(width * height * 4)
    fill = (217, 139, 58, 225)
    for y in range(height):
        for x in range(width):
            visible = True
            if name in {"nw", "ne", "sw", "se"}:
                cx = width - 1 if "w" in name else 0
                cy = height - 1 if "n" in name else 0
                distance = (x - cx) ** 2 + (y - cy) ** 2
                visible = distance <= (width - 1) ** 2
            if ("n" in name and y < 5) or ("s" in name and y >= height - 5):
                visible = False
            if visible:
                i = (y * width + x) * 4
                data[i:i + 4] = bytes(fill)
    return bytes(data)


def menu_piece(name: str) -> bytes:
    width = height = 20
    data = bytearray(width * height * 4)
    glass = (7, 12, 18, 178)
    edge = (217, 139, 58, 115)
    for y in range(height):
        for x in range(width):
            visible = True
            curved_border = False
            if name in {"nw", "ne", "sw", "se"}:
                cx = width - 1 if "w" in name else 0
                cy = height - 1 if "n" in name else 0
                distance = (x - cx) ** 2 + (y - cy) ** 2
                visible = distance <= (width - 1) ** 2
                curved_border = distance >= (width - 2) ** 2
            if not visible:
                continue
            border = (
                curved_border
                or
                ("n" in name and y == 0)
                or ("s" in name and y == height - 1)
                or ("w" in name and x == 0)
                or ("e" in name and x == width - 1)
            )
            i = (y * width + x) * 4
            data[i:i + 4] = bytes(edge if border else glass)
    return bytes(data)


def main() -> None:
    assets = ROOT / "flexboot" / "assets"
    png(assets / "background-classic-grid.png", 1920, 1080, classic_background())
    png(assets / "logo.png", 256, 256, logo(), channels=4)
    for name in ("c", "n", "s", "e", "w", "nw", "ne", "sw", "se"):
        png(assets / f"select_{name}.png", 8, 8, selection_piece(name), channels=4)
        png(assets / f"menu_{name}.png", 20, 20, menu_piece(name), channels=4)
    (ROOT / "branding" / "background-classic-grid.png").write_bytes(
        (assets / "background-classic-grid.png").read_bytes()
    )
    (ROOT / "branding" / "logo.png").write_bytes((assets / "logo.png").read_bytes())


if __name__ == "__main__":
    main()
