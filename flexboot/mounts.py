"""Owned temporary mount lifecycle."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import CleanupError
from .process import Runner


@contextmanager
def mounted(device: Path, *, readonly: bool = False, runner: Runner | None = None) -> Iterator[Path]:
    run = runner or Runner()
    mountpoint = Path(tempfile.mkdtemp(prefix="flexboot-mnt-"))
    active = False
    try:
        options = ["-o", "ro,noload,nosuid,nodev,noexec"] if readonly else ["-o", "nosuid,nodev,noexec"]
        # noload prevents ext4 journal replay on read-only inspections. FAT
        # does not understand it, so select it only for ext4.
        if readonly:
            fs = run.run(["blkid", "-o", "value", "-s", "TYPE", str(device)]).stdout.strip()
            if fs != "ext4":
                options[1] = "ro,nosuid,nodev,noexec"
        run.run(["mount", *options, str(device), str(mountpoint)], capture=False, mutate=True)
        active = True
        try:
            yield mountpoint
        finally:
            # USB controllers may acknowledge file writes before directory and
            # allocation metadata reaches the medium. Flush while still mounted.
            if not readonly and os.path.ismount(mountpoint):
                os.sync()
            result = run.run(["umount", str(mountpoint)], check=False, capture=True, mutate=True)
            if result.returncode or os.path.ismount(mountpoint):
                raise CleanupError(f"Could not unmount FlexBoot-owned mountpoint; preserved for recovery: {mountpoint}")
            active = False
    finally:
        # Never recursively delete an expected mountpoint. If unmount failed,
        # preserve the directory so an administrator can recover it safely.
        if not active and not os.path.ismount(mountpoint):
            try:
                mountpoint.rmdir()
            except OSError:
                # Unexpected contents are preserved, including on mount failure.
                pass
