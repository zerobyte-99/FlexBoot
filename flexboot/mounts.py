"""Owned temporary mount lifecycle."""
from __future__ import annotations

import os
import ctypes
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import CleanupError
from .process import Runner


def flush_filesystem(path: Path) -> None:
    """Flush only our mounted filesystem, without syncing unrelated host disks."""
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        library = ctypes.CDLL(None, use_errno=True)
        library.syncfs.argtypes = [ctypes.c_int]
        library.syncfs.restype = ctypes.c_int
        if library.syncfs(descriptor):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(path))
    finally:
        os.close(descriptor)


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
        fs = run.run(["blkid", "-o", "value", "-s", "TYPE", str(device)]).stdout.strip()
        driver = ["-t", "ntfs-3g"] if fs == "ntfs" else []
        run.run(["mount", *driver, *options, str(device), str(mountpoint)], capture=False, mutate=True)
        active = True
        try:
            yield mountpoint
        finally:
            # USB controllers may acknowledge file writes before directory and
            # allocation metadata reaches the medium. Flush while still mounted.
            flush_error = None
            if not readonly and os.path.ismount(mountpoint):
                try:
                    flush_filesystem(mountpoint)
                except OSError as exc:
                    flush_error = exc
            result = run.run(["umount", str(mountpoint)], check=False, capture=True, mutate=True)
            if result.returncode or os.path.ismount(mountpoint):
                raise CleanupError(f"Could not unmount FlexBoot-owned mountpoint; preserved for recovery: {mountpoint}")
            active = False
            if flush_error is not None:
                raise CleanupError(f"Filesystem flush failed; preserve media for verification: {flush_error}")
    finally:
        # Never recursively delete an expected mountpoint. If unmount failed,
        # preserve the directory so an administrator can recover it safely.
        if not active and not os.path.ismount(mountpoint):
            try:
                mountpoint.rmdir()
            except OSError:
                # Unexpected contents are preserved, including on mount failure.
                pass
