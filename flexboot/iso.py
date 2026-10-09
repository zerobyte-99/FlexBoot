"""Read-only ISO filesystem inspection."""
from __future__ import annotations

import shlex
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
    "/conf/bootid.txt",
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
    paths: set[str] = set()
    volume_id: str | None = None
    text_files: dict[str, str] = {}
    kernel_architectures: dict[str, str] = {}
    external = shutil.which("xorriso") or shutil.which("isoinfo")
    if external and Path(external).name == "xorriso":
        result = run.run(["xorriso", "-indev", str(path), "-find", "/", "-type", "f", "-print"])
        paths = set()
        for line in result.stdout.splitlines():
            value = line.strip()
            if value.startswith(("'", '"')):
                try:
                    tokens = shlex.split(value)
                except ValueError as exc:
                    raise FlexBootError("Malformed xorriso path listing") from exc
                value = tokens[0] if len(tokens) == 1 else ""
            if value.startswith("/"):
                paths.add(value)
    elif external:
        result = run.run(["isoinfo", "-R", "-f", "-i", str(path)])
        paths = {line.strip() for line in result.stdout.splitlines() if line.startswith("/")}
    # Every backend receives the same bounded volume/config/header facts.
    # External tools still supply Rock Ridge names where available; installing
    # them must not silently remove product markers used by specific profiles.
    try:
        image = ISO9660Reader(path)
    except FlexBootError:
        # An external parser may recognize a filesystem unsupported by this
        # reader. Missing facts still prevent metadata-dependent matches.
        if not external:
            raise
        image = None
    if image is not None:
        with image:
            entries = image.entries()
            if not external:
                paths = {entry.path for entry in entries if not entry.directory}
            volume_id = image.volume_id
            candidates = {name.casefold(): name for name in TEXT_CANDIDATES}
            text_files = {
                candidates[entry.path.casefold()]: image.read(entry)
                for entry in entries if entry.path.casefold() in candidates
            }
            header_count = 0
            for entry in entries:
                if entry.directory or not (entry.path.rsplit("/", 1)[-1].startswith("vmlinuz") or entry.path == "/boot/gentoo"):
                    continue
                header_count += 1
                if header_count > 32:
                    raise FlexBootError("Too many kernel headers to inspect")
                header = image.read_prefix(entry, 0x238)
                if len(header) >= 0x238 and header[0x202:0x206] == b"HdrS" and int.from_bytes(header[0x206:0x208], "little") >= 0x20C:
                    kernel_architectures[entry.path] = "x86_64" if int.from_bytes(header[0x236:0x238], "little") & 1 else "x86"
    if volume_id is None and shutil.which("blkid"):
        label = run.run(["blkid", "-p", "-o", "value", "-s", "LABEL", str(path)], check=False)
        volume_id = label.stdout.strip() or None
    inspection = ISOInspection(frozenset(paths), volume_id, text_files, kernel_architectures)
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
