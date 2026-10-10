"""Physical and raw-image target lifecycles."""
from __future__ import annotations

import os
import fcntl
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import CleanupError, FlexBootError, SafetyError
from .process import Runner


@dataclass(frozen=True)
class AttachedTarget:
    device: Path
    kind: str


def assert_image_backing(loop: Path, image: Path) -> None:
    backing = Path("/sys/block") / loop.name / "loop/backing_file"
    if not backing.is_file() or backing.read_text().strip().lstrip("/") != str(image.resolve()).lstrip("/"):
        raise SafetyError("Attached loop does not identify the requested backing image")


@contextmanager
def attached_image(image: Path, runner: Runner, *, readonly: bool = False) -> Iterator[AttachedTarget]:
    if runner.dry_run:
        yield AttachedTarget(image.resolve(), "image-dry-run")
        return
    if not image.is_file():
        raise FlexBootError(f"Image file not found: {image}")
    with image.open("rb") as owner:
        try:
            fcntl.flock(owner, (fcntl.LOCK_SH if readonly else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SafetyError("Raw image is already in use by another FlexBoot operation") from exc
        before = os.fstat(owner.fileno())
        args = ["losetup", "--find", "--show", "--partscan"]
        if readonly:
            args.append("--read-only")
        result = runner.run([*args, str(image.resolve())], mutate=True)
        loop = Path(result.stdout.strip())
        if not re.fullmatch(r"/dev/loop\d+", str(loop)):
            raise SafetyError(f"Unexpected loop device response: {loop}")
        try:
            after = image.stat()
            if (before.st_dev, before.st_ino, before.st_size) != (after.st_dev, after.st_ino, after.st_size):
                raise SafetyError("Backing image changed during loop attachment")
            assert_image_backing(loop, image)
            runner.run(["udevadm", "settle"], mutate=True)
            yield AttachedTarget(loop, "image")
        finally:
            detached = runner.run(["losetup", "--detach", str(loop)], check=False, mutate=True)
            if detached.returncode:
                raise CleanupError(f"Could not detach {loop}; preserve backing image {image} for recovery")


def create_sparse(path: Path, size: int, *, runner: Runner) -> None:
    if size < 1024**3:
        raise FlexBootError("Raw images must be at least 1 GiB")
    if path.exists():
        raise FlexBootError(f"Refusing to overwrite existing image: {path}")
    if runner.dry_run:
        runner.planned.append(["truncate", "--size", str(size), str(path)])
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(fd, size)
        os.fsync(fd)
    except BaseException:
        # This function owns the newly created file even if truncation fails.
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)


def parse_size(value: str) -> int:
    text = value.strip().upper()
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    if text[-1:] in multipliers:
        try:
            return int(float(text[:-1]) * multipliers[text[-1]])
        except ValueError as exc:
            raise FlexBootError(f"Invalid size: {value}") from exc
    try:
        return int(text)
    except ValueError as exc:
        raise FlexBootError(f"Invalid size: {value}") from exc
