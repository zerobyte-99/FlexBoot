"""Physical and raw-image target lifecycles."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .errors import FlexBootError, SafetyError
from .process import Runner


@dataclass(frozen=True)
class AttachedTarget:
    device: Path
    kind: str


@contextmanager
def attached_image(image: Path, runner: Runner, *, readonly: bool = False) -> Iterator[AttachedTarget]:
    if runner.dry_run:
        yield AttachedTarget(image.resolve(), "image-dry-run")
        return
    if not image.is_file():
        raise FlexBootError(f"Image file not found: {image}")
    args = ["losetup", "--find", "--show", "--partscan"]
    if readonly:
        args.append("--read-only")
    result = runner.run([*args, str(image.resolve())], mutate=True)
    loop = Path(result.stdout.strip())
    if not str(loop).startswith("/dev/loop"):
        raise SafetyError(f"Unexpected loop device response: {loop}")
    try:
        yield AttachedTarget(loop, "image")
    finally:
        runner.run(["losetup", "--detach", str(loop)], check=False, mutate=True)


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
