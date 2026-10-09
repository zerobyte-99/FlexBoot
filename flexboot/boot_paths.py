"""Safe boot-time aliases for initramfs parsers that split filenames on spaces."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Iterable

from .branding import BRAND
from .errors import MediaStateError


def iso_boot_path(filename: str) -> str:
    from .iso import validate_filename
    validate_filename(filename)
    if re.fullmatch(r"[A-Za-z0-9_.+-]+", filename):
        return "/iso/" + filename
    name = hashlib.sha256(filename.encode("utf-8")).hexdigest() + ".iso"
    return f"/{BRAND.metadata_dir}/boot-isos/{name}"


def alias_path(data: Path, filename: str) -> Path | None:
    boot = iso_boot_path(filename)
    return data / boot.lstrip("/") if not boot.startswith("/iso/") else None


def alias_target(filename: str) -> str:
    return "../../iso/" + filename


def alias_problems(data: Path, filenames: Iterable[str]) -> list[str]:
    problems = []
    metadata = data / BRAND.metadata_dir
    directory = metadata / "boot-isos"
    if metadata.is_symlink() or directory.is_symlink():
        return ["Boot alias directory must not be a symlink"]
    for filename in filenames:
        path = alias_path(data, filename)
        if path is not None and (not path.is_symlink() or os.readlink(path) != alias_target(filename)):
            problems.append(f"Boot alias is missing or incorrect: {filename}")
    return problems


def rollback_aliases(created: list[tuple[Path, str]]) -> None:
    for path, target in reversed(created):
        if path.parent.is_symlink() or path.parent.parent.is_symlink():
            raise MediaStateError("Boot alias directory changed during rollback")
        if path.is_symlink() and os.readlink(path) == target:
            path.unlink()


def ensure_aliases(data: Path, filenames: Iterable[str]) -> list[tuple[Path, str]]:
    """Create missing links, never overwrite conflicting files or follow dirs."""
    created = []
    try:
        for filename in filenames:
            path = alias_path(data, filename)
            if path is None:
                continue
            metadata = data / BRAND.metadata_dir
            if metadata.is_symlink() or path.parent.is_symlink():
                raise MediaStateError("Boot alias directory must not be a symlink")
            path.parent.mkdir(parents=True, exist_ok=True)
            target = alias_target(filename)
            if path.is_symlink():
                if os.readlink(path) != target:
                    raise MediaStateError(f"Conflicting boot alias: {filename}")
            elif path.exists():
                raise MediaStateError(f"Boot alias is not a symlink: {filename}")
            else:
                path.symlink_to(target)
                created.append((path, target))
        if created:
            fd = os.open(created[0][0].parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return created
    except BaseException:
        rollback_aliases(created)
        raise


def remove_alias(data: Path, filename: str) -> None:
    path = alias_path(data, filename)
    if path is None or not path.is_symlink():
        return
    if (data / BRAND.metadata_dir).is_symlink() or path.parent.is_symlink():
        raise MediaStateError("Boot alias directory must not be a symlink")
    if os.readlink(path) == alias_target(filename):
        path.unlink()
