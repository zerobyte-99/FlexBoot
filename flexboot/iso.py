"""Read-only ISO filesystem inspection."""
from __future__ import annotations

import shutil
from pathlib import Path

from .errors import FlexBootError, UnsupportedISOError
from .process import Runner
from .profiles import detect_profile, supported_descriptions
from .profiles.base import ISOInspection, ProfileMatch
from .iso9660 import ISO9660Reader


TEXT_CANDIDATES = {
    "/boot/grub/grub.cfg", "/boot/grub2/grub.cfg",
    "/boot/grub/loopback.cfg", "/EFI/BOOT/grub.cfg", "/isolinux/isolinux.cfg",
    "/Clonezilla-Live-Version", "/.disk/info",
}


def validate_filename(name: str) -> None:
    if name in ("", ".", "..") or "/" in name or "\\" in name:
        raise FlexBootError(f"Invalid ISO filename: {name!r}")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise FlexBootError("ISO filenames may not contain control characters")
    if not name.lower().endswith(".iso"):
        raise FlexBootError(f"ISO filename must end in .iso: {name}")


def directory_paths(root: Path) -> set[str]:
    return {"/" + str(path.relative_to(root)) for path in root.rglob("*")}


def inspect_iso(path: Path, runner: Runner | None = None) -> tuple[ISOInspection, ProfileMatch | None]:
    if not path.is_file():
        raise FlexBootError(f"ISO is not a regular file: {path}")
    validate_filename(path.name)
    run = runner or Runner()
    paths: set[str]
    volume_id: str | None = None
    text_files: dict[str, str] = {}
    if shutil.which("xorriso"):
        result = run.run(["xorriso", "-indev", str(path), "-find", "/", "-type", "f", "-print"])
        paths = {line.strip() for line in result.stdout.splitlines() if line.startswith("/")}
    elif shutil.which("isoinfo"):
        result = run.run(["isoinfo", "-R", "-f", "-i", str(path)])
        paths = {line.strip() for line in result.stdout.splitlines() if line.startswith("/")}
    else:
        with ISO9660Reader(path) as image:
            entries = image.entries()
            paths = {entry.path for entry in entries if not entry.directory}
            volume_id = image.volume_id
            text_files = {
                entry.path: image.read(entry)
                for entry in entries if entry.path in TEXT_CANDIDATES
            }
    if volume_id is None and shutil.which("blkid"):
        label = run.run(["blkid", "-p", "-o", "value", "-s", "LABEL", str(path)], check=False)
        volume_id = label.stdout.strip() or None
    inspection = ISOInspection(frozenset(paths), volume_id, text_files)
    return inspection, detect_profile(inspection)


def require_supported(path: Path, runner: Runner | None = None) -> ProfileMatch:
    paths, match = inspect_iso(path, runner)
    if match:
        return match
    clues = sorted(p for p in paths.paths if p.count("/") <= 2)[:12]
    detail = "\n  ".join(clues) if clues else "(no recognizable boot files)"
    families = "\n  ".join(supported_descriptions())
    raise UnsupportedISOError(
        f"Unsupported ISO:\n  {path.name}\n\nReason:\n  No supported boot profile matched this image."
        f"\n\nDetected characteristics:\n  {detail}\n\nSupported families:\n  {families}"
    )
