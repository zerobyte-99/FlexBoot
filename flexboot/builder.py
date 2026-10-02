"""Shared media builder for validated disks and attached raw images."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .devices import find_device
from .disk import discover_partitions, format_partitions, partition_device
from .errors import FlexBootError
from .grub import install_grub
from .media import MediaPaths, initialize
from .mounts import mounted
from .process import Runner


def require_root() -> None:
    if os.geteuid() != 0:
        raise FlexBootError("This operation requires root privileges.\n\nTry:\n  sudo flexboot ...")


def filesystem_uuid(partition: Path, runner: Runner) -> str:
    result = runner.run(["blkid", "--output", "value", "--match-tag", "UUID", str(partition)])
    uuid = result.stdout.strip()
    if not uuid:
        raise FlexBootError(f"Could not read filesystem UUID: {partition}")
    return uuid


def build_attached(device: Path, runner: Runner, *, identity_check=None) -> None:
    if identity_check:
        identity_check()
    partition_device(device, runner)
    efi_part, data_part = discover_partitions(device, runner)
    format_partitions(efi_part, data_part, runner)
    data_uuid = filesystem_uuid(data_part, runner)
    with mounted(efi_part, runner=runner) as efi_root, mounted(data_part, runner=runner) as data_root:
        install_grub(efi_root, runner)
        initialize(MediaPaths(efi_root, data_root), data_uuid, runner)


@contextmanager
def open_media(device: Path, runner: Runner, *, readonly: bool = False) -> Iterator[MediaPaths]:
    efi_part, data_part = discover_partitions(device, runner)
    with mounted(efi_part, readonly=readonly, runner=runner) as efi_root, mounted(data_part, readonly=readonly, runner=runner) as data_root:
        yield MediaPaths(efi_root, data_root)
