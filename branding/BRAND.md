# FlexBoot Brand Direction

## Name

**FlexBoot**

## Tagline

**Build. Boot. Repeat.**

## Personality

Technical, clean, capable and understated.

FlexBoot should feel like a serious Linux utility with a good eye for design, not like a gaming bootloader skin.

## Default visual direction

### Background

- dark graphite / near-black;
- subtle geometric or circuit-like pattern;
- enough empty space around menu text;
- no photographic stock imagery;
- no distracting high-frequency texture.

### Accent

Use a restrained ember/amber/orange accent.

The exact values should live in one branding configuration rather than being scattered through source code.

### Logo concept

Create an original geometric mark.

Good conceptual directions:

- a stylized `F` built from boot/branch geometry;
- a flexible path/switch motif;
- two paths merging into one boot arrow;
- a clean abstract boot-media symbol.

Avoid:

- copied corporate logos;
- obvious Ventoy visual similarities;
- excessive gradients;
- faux-3D gamer styling.

## GRUB theme priorities

1. readability;
2. predictable rendering;
3. compatibility;
4. visual polish.

Suggested screen behavior:

- FlexBoot logo/name near top;
- centered or left-aligned clean menu;
- selected row clearly highlighted;
- subtle footer with tagline/version;
- enough contrast for poor laptop/projector displays.

## Replaceable assets

Design the implementation so the user can later replace:

```text
branding/background.png
branding/logo.png
branding/credit.png
branding/branding.conf
```

without modifying Python code.

Custom theme files should be copied into the media at build/sync time.

## Included backgrounds

- `background-quantum-fold.png` — clean folded amber light, the default;
- `background-ember-circuit.png` — technical horizon and circuit paths;
- `background-orbital-lattice.png` — a luminous orbital structure;
- `background-classic-grid.png` — the original generated graphite grid.

List and select a background by stable number or name:

```bash
flexboot theme --list
sudo flexboot theme /dev/sdX 4
sudo flexboot theme /dev/sdX quantum-fold
```

The `flexboot` layout uses the branded glass panel. The `kali` alternate uses Kali's centered frameless menu geometry. Switch layouts without changing the selected background:

```bash
sudo flexboot theme /dev/sdX kali
sudo flexboot theme /dev/sdX flexboot
```

The normal layout renders its credit as a transparent PNG with a restrained,
symmetric blue gradient. The exact text, gradient stops, font, size, and asset
name are centralized as `credit_line`, `credit_gradient`, `credit_font`,
`credit_font_weight`, `credit_font_size`, and `credit_asset` in
`branding.conf`. Regenerate both
shipped copies after changing those values:

```bash
python3 tools/generate_credit_asset.py
```

The generator draws the original wide, rounded `FlexArc` geometric lettering
directly through libcairo and does not require or download a font. Sync installs
the credit asset and selected background while preserving the per-drive layout
and background selection. In the normal layout, the 460×16 native-size credit
ends exactly 40 pixels before the fixed-width UEFI text area.

## Menu density

The default graphical menu is tuned for 15 visible entries at 1920×1080. This total includes the firmware, reboot, and power-off utility entries. The menu begins immediately below the tagline. Its controls are grouped in `flexboot/assets/theme.txt`:

```text
height = 60%
item_height = 32
item_spacing = 9
```

To support more visible entries later, reduce `item_spacing` first. If necessary, reduce `item_height` or increase the menu `height`. Keep `item_padding = 0` so the selection graphic remains confined to one row.

## Naming constants

Use these defaults:

```text
PRODUCT_NAME=FlexBoot
TAGLINE=Build. Boot. Repeat.
EFI_LABEL=FLEXBOOT_EFI
DATA_LABEL=FLEXBOOT
METADATA_DIR=.flexboot
```

Centralize them.
