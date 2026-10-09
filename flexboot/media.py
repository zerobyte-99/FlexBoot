"""Transactional media content operations on mounted filesystems."""
from __future__ import annotations

import json
import os
import shutil
import struct
import uuid
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
from .branding import BRAND
from .boot_paths import alias_problems, ensure_aliases, iso_boot_path, remove_alias, rollback_aliases
from .errors import DependencyError, FlexBootError, MediaStateError, SafetyError
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
    fd, raw = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as dst, source.open("rb") as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        temporary.chmod(0o644)
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
    created_aliases = []
    try:
        atomic_text(candidate, generated_config(manifest.isos))
        validate_config(candidate, runner)
        created_aliases = ensure_aliases(paths.data, (item.filename for item in manifest.isos))
        os.replace(candidate, destination)
    except BaseException:
        rollback_aliases(created_aliases)
        raise
    finally:
        candidate.unlink(missing_ok=True)


@dataclass(frozen=True)
class AddResult:
    record: ISORecord
    status: str


def check_free_space(paths: MediaPaths, size: int) -> None:
    stats = os.statvfs(paths.data)
    available = stats.f_bavail * stats.f_frsize
    required = size + 8 * 1024 * 1024
    if available < required:
        raise MediaStateError(f"Not enough free space: need {required} bytes including metadata reserve; available {available} bytes")


def add_iso_result(paths: MediaPaths, source: Path, runner: Runner | None = None, *, replace: bool = False) -> AddResult:
    run = runner or Runner()
    source = source.resolve()
    validate_filename(source.name)
    if not source.is_file():
        raise FlexBootError(f"ISO is not a regular file: {source}")
    inspected_state = source.stat()
    match = require_supported(source, run)
    manifest = Manifest.load(paths.manifest)
    destination = paths.iso_dir / source.name
    previous = next((item for item in manifest.isos if item.filename == source.name), None)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise MediaStateError(f"ISO destination is not a regular file: {destination}")
    if previous:
        if not destination.is_file():
            raise MediaStateError(f"Manifest ISO is missing: {destination}")
        if not replace:
            if destination.stat().st_size != previous.size or sha256_file(destination) != previous.sha256:
                raise MediaStateError(f"Installed ISO is inconsistent: {source.name}; verify or explicitly replace it")
            if source.stat().st_size == previous.size and sha256_file(source) == previous.sha256:
                if ISORecord.from_match(source.name, previous.size, previous.sha256, match).boot_plan() != previous.boot_plan():
                    raise MediaStateError(f"Stored boot profile is stale: {source.name}; run sync")
                return AddResult(previous, "skipped")
            raise FlexBootError(f"Different ISO content uses the installed name {source.name}; use --replace")
    elif destination.exists():
        raise MediaStateError(f"Destination exists but is absent from manifest: {destination}")
    check_free_space(paths, source.stat().st_size)
    paths.iso_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged = paths.iso_dir / f".{source.name}.{token}.staged"
    backup = paths.iso_dir / f".{source.name}.{token}.backup"
    old_manifest = paths.manifest.read_text()
    menu = paths.grub_dir / "generated.cfg"
    old_menu = menu.read_text() if menu.exists() else None
    published = False
    try:
        digest = copy_and_hash(source, staged)
        current_state = source.stat()
        if (inspected_state.st_dev, inspected_state.st_ino, inspected_state.st_size, inspected_state.st_mtime_ns, inspected_state.st_ctime_ns) != (current_state.st_dev, current_state.st_ino, current_state.st_size, current_state.st_mtime_ns, current_state.st_ctime_ns):
            raise FlexBootError("Source ISO changed after profile inspection")
        record = ISORecord.from_match(source.name, staged.stat().st_size, digest, match)
        record.boot_plan()
        if previous:
            os.replace(destination, backup)
        os.replace(staged, destination)
        published = True
        manifest.isos = [item for item in manifest.isos if item.filename != source.name]
        manifest.isos.append(record)
        manifest.save(paths.manifest)
        regenerate(paths, manifest, run)
    except BaseException as original:
        try:
            if published:
                destination.unlink(missing_ok=True)
            if backup.exists():
                os.replace(backup, destination)
            atomic_text(paths.manifest, old_manifest)
            if old_menu is not None:
                atomic_text(menu, old_menu)
            else:
                menu.unlink(missing_ok=True)
        except BaseException as rollback:
            raise MediaStateError(f"ISO operation failed and rollback is incomplete. Preserve {backup} and inspect media: {rollback}") from original
        raise
    finally:
        staged.unlink(missing_ok=True)
    backup.unlink(missing_ok=True)
    return AddResult(record, "replaced" if previous else "added")


def add_iso(paths: MediaPaths, source: Path, runner: Runner | None = None, *, replace: bool = False) -> ISORecord:
    return add_iso_result(paths, source, runner, replace=replace).record


def batch_add(paths: MediaPaths, sources: list[Path], runner: Runner, *, replace: bool = False,
              continue_on_error: bool = False) -> list[dict[str, str]]:
    outcomes = []
    stopped = False
    for source in sources:
        if stopped:
            outcomes.append({"file": str(source), "status": "not-attempted"})
            continue
        try:
            result = add_iso_result(paths, source, runner, replace=replace)
            outcomes.append({"file": str(source), "status": result.status, "profile": result.record.profile})
        except (FlexBootError, OSError) as exc:
            outcomes.append({"file": str(source), "status": "failed", "reason": str(exc)})
            stopped = not continue_on_error or isinstance(exc, (SafetyError, DependencyError, OSError))
    return outcomes


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
    remove_alias(paths.data, filename)


def sync(paths: MediaPaths, runner: Runner | None = None) -> Manifest:
    old = Manifest.load(paths.manifest)
    records: list[ISORecord] = []
    for iso_path in sorted((path for path in paths.iso_dir.iterdir() if path.suffix.casefold() == ".iso"), key=lambda path: path.name.casefold()):
        if iso_path.is_symlink() or not iso_path.is_file():
            raise MediaStateError(f"ISO is not a regular file: {iso_path.name}")
        match = require_supported(iso_path, runner)
        previous = next((item for item in old.isos if item.filename == iso_path.name), None)
        digest = sha256_file(iso_path)
        if previous and digest != previous.sha256:
            raise MediaStateError(f"Local integrity mismatch: {iso_path.name}; sync will not accept changed content. Use add --replace with the intended source.")
        records.append(ISORecord.from_match(iso_path.name, iso_path.stat().st_size, digest, match))
    old.isos = records
    setting = theme_setting(paths)
    work = Path(tempfile.mkdtemp(prefix=".flexboot-sync-", dir=paths.efi))
    theme = paths.grub_dir / "themes/flexboot"
    saved_theme = work / "saved-theme"
    original_text = {path: path.read_text() if path.exists() else None for path in
                     (paths.manifest, paths.grub_dir / "grub.cfg", paths.grub_dir / "generated.cfg")}
    theme_published = False
    preserve_recovery = False
    font_published = False
    font = paths.grub_dir / "fonts/unicode.pf2"
    created_aliases = []
    try:
        stage = MediaPaths(work, paths.data)
        if font.is_file():
            _atomic_copy(font, stage.grub_dir / "fonts/unicode.pf2")
        if theme.is_dir():
            shutil.copytree(theme, stage.grub_dir / "themes/flexboot")
        deploy_theme(work, configured_background(paths), str(setting["layout"]))
        for name, text in (("grub.cfg", base_config(old.data_filesystem_uuid)), ("generated.cfg", generated_config(old.isos))):
            atomic_text(stage.grub_dir / name, text)
            validate_config(stage.grub_dir / name, runner)
        created_aliases = ensure_aliases(paths.data, (item.filename for item in old.isos))
        if theme.exists():
            os.replace(theme, saved_theme)
        theme.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage.grub_dir / "themes/flexboot", theme)
        theme_published = True
        if not font.exists():
            _atomic_copy(stage.grub_dir / "fonts/unicode.pf2", font)
            font_published = True
        for name in ("grub.cfg", "generated.cfg"):
            atomic_text(paths.grub_dir / name, (stage.grub_dir / name).read_text())
        old.save(paths.manifest)
    except BaseException as original:
        try:
            if theme_published:
                os.replace(theme, work / "failed-theme")
            if saved_theme.exists():
                os.replace(saved_theme, theme)
            if font_published:
                font.unlink(missing_ok=True)
            for path, text in original_text.items():
                if text is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_text(path, text)
            rollback_aliases(created_aliases)
        except BaseException as rollback:
            preserve_recovery = True
            raise MediaStateError(f"Sync rollback failed; preserve recovery files at {work}: {rollback}") from original
        raise
    finally:
        if not preserve_recovery:
            shutil.rmtree(work)
    return old


def verify(paths: MediaPaths, *, full_hash: bool = True) -> list[str]:
    problems: list[str] = []
    try:
        manifest = Manifest.load(paths.manifest)
    except FlexBootError as exc:
        return [str(exc)]
    expected_names = {item.filename for item in manifest.isos}
    actual_names = {path.name for path in paths.iso_dir.iterdir() if path.suffix.casefold() == ".iso"}
    for name in sorted(expected_names - actual_names):
        problems.append(f"Manifest entry is missing its file: {name}")
    for name in sorted(actual_names - expected_names):
        problems.append(f"ISO file is absent from manifest: {name}")
    for record in manifest.isos:
        path = paths.iso_dir / record.filename
        if path.is_symlink() or (path.exists() and not path.is_file()):
            problems.append(f"ISO is not a regular file: {record.filename}")
            continue
        if not path.exists():
            continue
        if path.stat().st_size != record.size:
            problems.append(f"Size mismatch: {record.filename}")
        elif full_hash and sha256_file(path) != record.sha256:
            problems.append(f"Local integrity hash mismatch: {record.filename}")
        if full_hash:
            try:
                match = require_supported(path)
                detected = ISORecord.from_match(record.filename, record.size, record.sha256, match)
                if detected.profile != record.profile or detected.boot_plan() != record.boot_plan():
                    problems.append(f"Detected ISO boot profile differs from manifest: {record.filename}")
            except (FlexBootError, OSError) as exc:
                problems.append(f"Cannot verify ISO profile for {record.filename}: {exc}")
    problems.extend(alias_problems(paths.data, (item.filename for item in manifest.isos)))
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
            {**asdict(item), "boot_iso_path": iso_boot_path(item.filename),
             "actual_sha256": sha256_file(paths.iso_dir / item.filename) if full_hash and (paths.iso_dir / item.filename).is_file() else None}
            for item in manifest.isos
        ],
        "theme": theme_setting(paths),
        "verification": verify(paths, full_hash=full_hash),
    }
