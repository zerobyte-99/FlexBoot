"""Transactional media content operations on mounted filesystems."""
from __future__ import annotations

import json
import os
import shutil
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from .branding import BRAND
from .errors import FlexBootError
from .grub import atomic_text, base_config, generated_config, validate_config
from .iso import require_supported, validate_filename
from .manifest import ISORecord, Manifest, copy_and_hash, sha256_file
from .process import Runner


@dataclass(frozen=True)
class MediaPaths:
    efi: Path
    data: Path

    @property
    def manifest(self) -> Path:
        return self.data / BRAND.metadata_dir / "manifest.json"

    @property
    def iso_dir(self) -> Path:
        return self.data / "iso"

    @property
    def grub_dir(self) -> Path:
        return self.efi / "boot" / "grub"

    @property
    def theme_config(self) -> Path:
        return self.data / BRAND.metadata_dir / "theme.json"

    @property
    def custom_background(self) -> Path:
        return self.data / BRAND.metadata_dir / "theme-background.png"


def available_themes() -> list[str]:
    source = Path(__file__).with_name("assets")
    return [path.stem.removeprefix("background-") for path in sorted(source.glob("background-*.png"))]


def available_layouts() -> list[str]:
    return ["flexboot", "kali"]


def resolve_theme_layout(selection: str) -> str | None:
    normalized = selection.strip().casefold().replace("_", "-").replace(" ", "-")
    aliases = {"default": "flexboot", "normal": "flexboot", "flexboot": "flexboot", "kali": "kali"}
    return aliases.get(normalized)


def resolve_builtin_theme(selection: str) -> str | None:
    themes = available_themes()
    value = selection.strip()
    if value.isdigit():
        index = int(value)
        return themes[index - 1] if 1 <= index <= len(themes) else None
    normalized = value.casefold().replace("_", "-").replace(" ", "-")
    normalized = normalized.removeprefix("background-").removesuffix(".png")
    return next((name for name in themes if name.casefold() == normalized), None)


def validate_background(path: Path) -> tuple[int, int]:
    if not path.is_file():
        raise FlexBootError(f"Custom theme image is not a regular file: {path}")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise FlexBootError("Custom theme image exceeds the 50 MiB limit")
    with path.open("rb") as handle:
        header = handle.read(33)
    if len(header) < 33 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise FlexBootError("Custom theme images must be PNG files")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", header[16:29])
    if not width or not height or width > 8192 or height > 8192:
        raise FlexBootError("Custom PNG dimensions must be between 1 and 8192 pixels")
    if bit_depth not in (8, 16) or color_type not in (0, 2, 4, 6) or compression or filtering or interlace:
        raise FlexBootError("Custom PNG must be non-interlaced RGB, RGBA, or grayscale")
    return width, height


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def theme_setting(paths: MediaPaths) -> dict[str, object]:
    if not paths.theme_config.is_file():
        default = Path(BRAND.theme_background).stem.removeprefix("background-")
        return {"schema_version": 1, "layout": "flexboot", "kind": "builtin", "name": default}
    try:
        value = json.loads(paths.theme_config.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or value.get("kind") not in ("builtin", "custom"):
            raise ValueError("unsupported schema or kind")
        if not isinstance(value.get("name"), str):
            raise ValueError("missing theme name")
        if value["kind"] == "builtin" and resolve_builtin_theme(value["name"]) is None:
            raise ValueError("unknown built-in theme")
        layout = value.get("layout", "flexboot")
        if layout not in available_layouts():
            raise ValueError("unknown theme layout")
        value["layout"] = layout
        return value
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FlexBootError(f"Malformed theme configuration {paths.theme_config}: {exc}") from exc


def configured_background(paths: MediaPaths) -> Path:
    setting = theme_setting(paths)
    if setting["kind"] == "custom":
        validate_background(paths.custom_background)
        return paths.custom_background
    name = resolve_builtin_theme(str(setting["name"]))
    assert name is not None
    return Path(__file__).with_name("assets") / f"background-{name}.png"


def set_theme(paths: MediaPaths, selection: str | Path) -> dict[str, object]:
    raw = str(selection)
    current = theme_setting(paths)
    layout = resolve_theme_layout(raw)
    builtin = resolve_builtin_theme(raw)
    if layout is not None:
        setting = {**current, "layout": layout}
    elif builtin is not None:
        setting = {
            "schema_version": 1, "layout": current["layout"],
            "kind": "builtin", "name": builtin,
        }
    else:
        custom = Path(raw).expanduser().resolve()
        width, height = validate_background(custom)
        _atomic_copy(custom, paths.custom_background)
        setting = {
            "schema_version": 1, "layout": current["layout"], "kind": "custom", "name": custom.name,
            "width": width, "height": height, "sha256": sha256_file(paths.custom_background),
        }
    atomic_text(paths.theme_config, json.dumps(setting, indent=2, sort_keys=True) + "\n")
    deploy_theme(paths.efi, configured_background(paths), str(setting["layout"]))
    if setting["kind"] == "builtin":
        paths.custom_background.unlink(missing_ok=True)
    return setting


def initialize(paths: MediaPaths, data_uuid: str, runner: Runner | None = None) -> Manifest:
    paths.iso_dir.mkdir(parents=True, exist_ok=True)
    metadata = paths.data / BRAND.metadata_dir
    metadata.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(data_filesystem_uuid=data_uuid)
    manifest.save(paths.manifest)
    (metadata / "version").write_text(__version__ + "\n", encoding="utf-8")
    install = {"version": __version__, "architecture": "x86_64", "firmware": "UEFI", "data_uuid": data_uuid}
    atomic_text(metadata / "install.json", json.dumps(install, indent=2, sort_keys=True) + "\n")
    default_theme = Path(BRAND.theme_background).stem.removeprefix("background-")
    atomic_text(paths.theme_config, json.dumps({"schema_version": 1, "layout": "flexboot", "kind": "builtin", "name": default_theme}, indent=2, sort_keys=True) + "\n")
    atomic_text(paths.grub_dir / "grub.cfg", base_config(data_uuid))
    atomic_text(paths.grub_dir / "generated.cfg", generated_config([]))
    deploy_theme(paths.efi)
    validate_config(paths.grub_dir / "grub.cfg", runner)
    return manifest


def render_theme(layout: str) -> str:
    if layout not in available_layouts():
        raise FlexBootError(f"Unknown theme layout: {layout}")
    filename = "theme.txt" if layout == "flexboot" else f"theme-{layout}.txt"
    template = (Path(__file__).with_name("assets") / filename).read_text(encoding="utf-8")
    if Path(BRAND.credit_asset).name != BRAND.credit_asset:
        raise FlexBootError(f"Invalid branding credit asset name: {BRAND.credit_asset}")
    return template.replace("@CREDIT_ASSET@", BRAND.credit_asset)


def deploy_theme(efi: Path, background: Path | None = None, layout: str = "flexboot") -> None:
    source = Path(__file__).with_name("assets")
    target = efi / "boot" / "grub" / "themes" / "flexboot"
    unicode_font = efi / "boot" / "grub" / "fonts" / "unicode.pf2"
    target.mkdir(parents=True, exist_ok=True)
    backgrounds = tuple(path.name for path in sorted(source.glob("background-*.png")))
    selected = BRAND.theme_background
    if background is None:
        if selected not in backgrounds or Path(selected).name != selected:
            raise FlexBootError(f"Configured theme background is unavailable: {selected}")
        background = source / selected
    validate_background(background)
    graphical_assets = (
        "logo.png", BRAND.credit_asset,
        "menu_c.png", "menu_n.png", "menu_s.png", "menu_e.png", "menu_w.png",
        "menu_nw.png", "menu_ne.png", "menu_sw.png", "menu_se.png",
        "select_c.png", "select_n.png", "select_s.png", "select_e.png", "select_w.png",
        "select_nw.png", "select_ne.png", "select_sw.png", "select_se.png",
    )
    for name in (*graphical_assets, *backgrounds):
        shutil.copyfile(source / name, target / name)
    atomic_text(target / "theme.txt", render_theme(layout))
    _atomic_copy(background, target / "background.png")
    if not unicode_font.is_file():
        host_font = Path("/usr/share/grub/unicode.pf2")
        if not host_font.is_file():
            raise FlexBootError("GRUB Unicode font is unavailable: expected /usr/share/grub/unicode.pf2")
        unicode_font.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(host_font, unicode_font)


def regenerate(paths: MediaPaths, manifest: Manifest, runner: Runner | None = None) -> None:
    destination = paths.grub_dir / "generated.cfg"
    candidate = destination.with_name("generated.cfg.new")
    try:
        atomic_text(candidate, generated_config(manifest.isos))
        validate_config(candidate, runner)
        os.replace(candidate, destination)
    finally:
        candidate.unlink(missing_ok=True)


def add_iso(paths: MediaPaths, source: Path, runner: Runner | None = None) -> ISORecord:
    run = runner or Runner()
    source = source.resolve()
    validate_filename(source.name)
    if not source.is_file():
        raise FlexBootError(f"ISO is not a regular file: {source}")
    match = require_supported(source, run)
    manifest = Manifest.load(paths.manifest)
    if any(item.filename == source.name for item in manifest.isos):
        raise FlexBootError(f"ISO is already installed: {source.name}")
    destination = paths.iso_dir / source.name
    if destination.exists():
        raise FlexBootError(f"Destination already exists but is absent from manifest: {destination}")
    paths.iso_dir.mkdir(parents=True, exist_ok=True)
    digest = copy_and_hash(source, destination)
    record = ISORecord.from_match(source.name, source.stat().st_size, digest, match)
    try:
        manifest.isos.append(record)
        manifest.save(paths.manifest)
        regenerate(paths, manifest, run)
    except BaseException:
        destination.unlink(missing_ok=True)
        manifest.isos = [item for item in manifest.isos if item.filename != source.name]
        manifest.save(paths.manifest)
        raise
    return record


def remove_iso(paths: MediaPaths, filename: str, runner: Runner | None = None) -> None:
    validate_filename(filename)
    manifest = Manifest.load(paths.manifest)
    original_records = list(manifest.isos)
    record = next((item for item in manifest.isos if item.filename == filename), None)
    if not record:
        raise FlexBootError(f"ISO is not installed: {filename}")
    source = paths.iso_dir / filename
    quarantine = paths.iso_dir / f".{filename}.removing"
    if source.exists():
        os.replace(source, quarantine)
    try:
        manifest.isos = [item for item in manifest.isos if item.filename != filename]
        manifest.save(paths.manifest)
        regenerate(paths, manifest, runner)
        quarantine.unlink(missing_ok=True)
    except BaseException:
        if quarantine.exists():
            os.replace(quarantine, source)
        manifest.isos = original_records
        manifest.save(paths.manifest)
        raise


def sync(paths: MediaPaths, runner: Runner | None = None) -> Manifest:
    old = Manifest.load(paths.manifest)
    records: list[ISORecord] = []
    for iso_path in sorted(paths.iso_dir.glob("*.iso"), key=lambda path: path.name.casefold()):
        match = require_supported(iso_path, runner)
        previous = next((item for item in old.isos if item.filename == iso_path.name), None)
        digest = previous.sha256 if previous and previous.size == iso_path.stat().st_size else sha256_file(iso_path)
        records.append(ISORecord.from_match(iso_path.name, iso_path.stat().st_size, digest, match))
    old.isos = records
    old.save(paths.manifest)
    setting = theme_setting(paths)
    deploy_theme(paths.efi, configured_background(paths), str(setting["layout"]))
    atomic_text(paths.grub_dir / "grub.cfg", base_config(old.data_filesystem_uuid))
    validate_config(paths.grub_dir / "grub.cfg", runner)
    regenerate(paths, old, runner)
    return old


def verify(paths: MediaPaths, *, full_hash: bool = True) -> list[str]:
    problems: list[str] = []
    try:
        manifest = Manifest.load(paths.manifest)
    except FlexBootError as exc:
        return [str(exc)]
    expected_names = {item.filename for item in manifest.isos}
    actual_names = {path.name for path in paths.iso_dir.glob("*.iso")}
    for name in sorted(expected_names - actual_names):
        problems.append(f"Manifest entry is missing its file: {name}")
    for name in sorted(actual_names - expected_names):
        problems.append(f"ISO file is absent from manifest: {name}")
    for record in manifest.isos:
        path = paths.iso_dir / record.filename
        if not path.exists():
            continue
        if path.stat().st_size != record.size:
            problems.append(f"Size mismatch: {record.filename}")
        elif full_hash and sha256_file(path) != record.sha256:
            problems.append(f"Local integrity hash mismatch: {record.filename}")
    generated = paths.grub_dir / "generated.cfg"
    expected = generated_config(manifest.isos)
    if not generated.exists() or generated.read_text(encoding="utf-8") != expected:
        problems.append("Generated GRUB menu is stale or missing")
    base = paths.grub_dir / "grub.cfg"
    if not base.is_file() or manifest.data_filesystem_uuid not in base.read_text(encoding="utf-8"):
        problems.append("Base GRUB configuration is missing or has the wrong data UUID")
    if not (paths.efi / "EFI" / "BOOT" / "BOOTX64.EFI").is_file():
        problems.append("Removable UEFI loader is missing")
    theme = paths.grub_dir / "themes" / "flexboot"
    for name in ("theme.txt", "background.png", "logo.png"):
        if not (theme / name).is_file():
            problems.append(f"GRUB theme asset is missing: {name}")
    try:
        deployed_theme = theme / "theme.txt"
        if deployed_theme.is_file() and deployed_theme.read_text(encoding="utf-8") != render_theme(str(theme_setting(paths)["layout"])):
            problems.append("Configured GRUB layout theme is not deployed")
    except (OSError, FlexBootError) as exc:
        problems.append(str(exc))
    try:
        expected_background = configured_background(paths)
        deployed_background = theme / "background.png"
        if deployed_background.is_file() and sha256_file(deployed_background) != sha256_file(expected_background):
            problems.append("Configured GRUB background is not deployed")
    except FlexBootError as exc:
        problems.append(str(exc))
    if not (paths.grub_dir / "fonts" / "unicode.pf2").is_file():
        problems.append("GRUB Unicode font is missing: unicode.pf2")
    return problems


def inspect(paths: MediaPaths, *, full_hash: bool = False) -> dict[str, object]:
    manifest = Manifest.load(paths.manifest)
    return {
        "version": __version__, "data_filesystem_uuid": manifest.data_filesystem_uuid,
        "bootloader": str(paths.efi / "EFI" / "BOOT" / "BOOTX64.EFI"),
        "bootloader_present": (paths.efi / "EFI" / "BOOT" / "BOOTX64.EFI").is_file(),
        "isos": [
            {**asdict(item), "actual_sha256": sha256_file(paths.iso_dir / item.filename) if full_hash and (paths.iso_dir / item.filename).is_file() else None}
            for item in manifest.isos
        ],
        "theme": theme_setting(paths),
        "verification": verify(paths, full_hash=full_hash),
    }
