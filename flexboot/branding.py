"""Centralized product and media branding."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Brand:
    product_name: str = "FlexBoot"
    tagline: str = "Build. Boot. Repeat."
    efi_label: str = "FLEXBOOTEFI"
    data_label: str = "FLEXBOOT"
    metadata_dir: str = ".flexboot"
    accent: str = "#d98b3a"
    background: str = "#16191d"
    credit_line: str = "FLEXBOOT by ZEROBYTE  •  CODE BY CODEX 2026"
    credit_gradient: str = "#65a8d8,#173b67,#347fc1,#a6d8f5,#347fc1,#173b67,#65a8d8"
    credit_font: str = "FlexArc"
    credit_font_weight: str = "light"
    credit_font_size: str = "12"
    credit_canvas_width: str = "460"
    credit_canvas_height: str = "16"
    credit_asset: str = "credit.png"
    theme_background: str = "background-quantum-fold.png"


def load_brand(path: Path | None = None) -> Brand:
    values: dict[str, str] = {}
    candidate = path or Path(__file__).with_name("assets") / "branding.conf"
    if candidate.exists():
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip().lower()] = value.strip()
    allowed = Brand.__dataclass_fields__.keys()
    return Brand(**{k: v for k, v in values.items() if k in allowed})


BRAND = load_brand()
