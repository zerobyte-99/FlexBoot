#!/usr/bin/env python3
"""Render the exact FlexBoot footer credit as a transparent gradient PNG."""
from __future__ import annotations

import ctypes
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "flexboot" / "assets" / "branding.conf"

# Original wide geometric lettering. Coordinates use a 4 × 6 design grid;
# rounded strokes and open counters keep the 12-pixel text crisp in GRUB.
GLYPHS: dict[str, tuple[tuple[tuple[float, float], ...], ...]] = {
    "B": (((0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)),
          ((3, 3), (4, 4), (4, 5), (3, 6), (0, 6))),
    "C": (((4, 1), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5)),),
    "D": (((0, 6), (0, 0), (2.5, 0), (4, 1.5), (4, 4.5), (2.5, 6), (0, 6)),),
    "E": (((4, 0), (0, 0), (0, 6), (4, 6)), ((0, 3), (3, 3))),
    "F": (((4, 0), (0, 0), (0, 6)), ((0, 3), (3, 3))),
    "L": (((0, 0), (0, 6), (4, 6)),),
    "O": (((1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)),),
    "R": (((0, 6), (0, 0), (3, 0), (4, 1), (4, 2), (3, 3), (0, 3)),
          ((2.5, 3), (4, 6))),
    "T": (((0, 0), (4, 0)), ((2, 0), (2, 6))),
    "X": (((0, 0), (4, 6)), ((4, 0), (0, 6))),
    "Y": (((0, 0), (2, 3), (4, 0)), ((2, 3), (2, 6))),
    "Z": (((0, 0), (4, 0), (0, 6), (4, 6)),),
    "0": (((1, 0), (3, 0), (4, 1), (4, 5), (3, 6), (1, 6), (0, 5), (0, 1), (1, 0)),
          ((0.8, 5.3), (3.2, 0.7))),
    "2": (((0, 1), (1, 0), (3, 0), (4, 1), (4, 2), (0, 6), (4, 6)),),
    "6": (((4, 0.7), (3, 0), (1, 0), (0, 1), (0, 5), (1, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)),),
    "•": (((2, 2.4), (2.6, 3), (2, 3.6), (1.4, 3), (2, 2.4)),),
}


def config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))


def render() -> None:
    values = config()
    if values.get("credit_font") != "FlexArc":
        raise ValueError("credit_font must be FlexArc")
    if values.get("credit_font_weight") != "light":
        raise ValueError("FlexArc supports credit_font_weight=light")
    text = values["credit_line"].upper()
    unsupported = sorted(set(text) - set(GLYPHS) - {" "})
    if unsupported:
        raise ValueError(f"Unsupported FlexArc characters: {unsupported}")
    colors = [rgb(value) for value in values["credit_gradient"].split(",")]
    if len(colors) < 2:
        raise ValueError("credit_gradient needs at least two colors")

    width = int(values.get("credit_canvas_width", "460"))
    height = int(values.get("credit_canvas_height", "16"))
    font_size = float(values.get("credit_font_size", "12"))
    if width < 64 or height < 8 or font_size <= 0 or font_size > height:
        raise ValueError("Invalid credit canvas or font size")

    cairo = ctypes.CDLL("libcairo.so.2")
    cairo.cairo_image_surface_create.restype = ctypes.c_void_p
    cairo.cairo_create.restype = ctypes.c_void_p
    cairo.cairo_pattern_create_linear.restype = ctypes.c_void_p
    cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    cairo.cairo_create.argtypes = [ctypes.c_void_p]
    cairo.cairo_pattern_create_linear.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    cairo.cairo_pattern_add_color_stop_rgb.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    cairo.cairo_set_source.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cairo.cairo_set_line_width.argtypes = [ctypes.c_void_p, ctypes.c_double]
    cairo.cairo_set_line_cap.argtypes = [ctypes.c_void_p, ctypes.c_int]
    cairo.cairo_move_to.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cairo.cairo_line_to.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
    cairo.cairo_stroke.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    cairo.cairo_surface_write_to_png.restype = ctypes.c_int
    cairo.cairo_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_surface_destroy.argtypes = [ctypes.c_void_p]
    cairo.cairo_pattern_destroy.argtypes = [ctypes.c_void_p]

    surface = cairo.cairo_image_surface_create(0, width, height)
    context = cairo.cairo_create(surface)
    scale_y = font_size / 6
    scale_x = scale_y
    advance = 5.6 * scale_x
    space_advance = 3.1 * scale_x
    text_width = sum(space_advance if char == " " else advance for char in text)
    if text_width > width - 6:
        raise ValueError(f"Credit text needs {text_width:.1f}px but canvas is only {width}px")
    origin_x = width - text_width - 3
    origin_y = (height - font_size) / 2

    gradient = cairo.cairo_pattern_create_linear(0, 0, width, 0)
    for index, color in enumerate(colors):
        cairo.cairo_pattern_add_color_stop_rgb(gradient, index / (len(colors) - 1), *color)
    cairo.cairo_set_source(context, gradient)
    cairo.cairo_set_line_width(context, max(1.0, scale_x * 0.54))
    cairo.cairo_set_line_cap(context, 1)

    cursor = origin_x
    for char in text:
        if char == " ":
            cursor += space_advance
            continue
        for stroke in GLYPHS[char]:
            first, *remaining = stroke
            cairo.cairo_move_to(context, cursor + first[0] * scale_x, origin_y + first[1] * scale_y)
            for point in remaining:
                cairo.cairo_line_to(context, cursor + point[0] * scale_x, origin_y + point[1] * scale_y)
        cursor += advance
    cairo.cairo_stroke(context)

    outputs = [ROOT / "flexboot" / "assets" / values["credit_asset"], ROOT / "branding" / values["credit_asset"]]
    for output in outputs:
        output.parent.mkdir(parents=True, exist_ok=True)
        status = cairo.cairo_surface_write_to_png(surface, str(output).encode())
        if status:
            raise RuntimeError(f"Cairo failed to write {output}: status {status}")
    cairo.cairo_pattern_destroy(gradient)
    cairo.cairo_destroy(context)
    cairo.cairo_surface_destroy(surface)
    print(f"Generated {outputs[0]} and {outputs[1]} ({width}x{height})")


if __name__ == "__main__":
    render()
