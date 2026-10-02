"""Owned temporary mount lifecycle."""
from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .errors import FlexBootError
from .process import Runner


@contextmanager
def mounted(device: Path, *, readonly: bool = False, runner: Runner | None = None) -> Iterator[Path]:
    run = runner or Runner()
    with tempfile.TemporaryDirectory(prefix="flexboot-mnt-") as raw:
        mountpoint = Path(raw)
        options = ["-o", "ro,nosuid,nodev"] if readonly else []
        run.run(["mount", *options, str(device), str(mountpoint)], capture=False, mutate=True)
        try:
            yield mountpoint
        finally:
            # USB controllers may acknowledge file writes before directory and
            # allocation metadata reaches the medium. Flush while still mounted.
            if not readonly and os.path.ismount(mountpoint):
                os.sync()
            result = run.run(["umount", str(mountpoint)], check=False, capture=True, mutate=True)
            if result.returncode and os.path.ismount(mountpoint):
                raise FlexBootError(f"Could not unmount FlexBoot-owned mountpoint: {mountpoint}")
