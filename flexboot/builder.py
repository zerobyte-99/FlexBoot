"""Shared media builder for validated disks and attached raw images."""
from __future__ import annotations

import os
import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

from .branding import BRAND
from .devices import discover, find_device
from .doctor import preflight
from .disk import assert_loop_target, discover_partitions, format_partitions, partition_device
from .errors import FlexBootError, SafetyError
from .manifest import Manifest
from .grub import install_grub
from .media import MediaPaths, initialize
from .mounts import mounted
from .process import Runner
from .safety import protected_device_names, revalidate_identity, system_mount_sources


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
    require_root()
    preflight("create")
    if identity_check:
        identity_check()
    else:
        assert_loop_target(device)
    partition_device(device, runner)
    efi_part, data_part = discover_partitions(device, runner)
    format_partitions(efi_part, data_part, runner)
    data_uuid = filesystem_uuid(data_part, runner)
    with mounted(efi_part, runner=runner) as efi_root, mounted(data_part, runner=runner) as data_root:
        install_grub(efi_root, runner)
        initialize(MediaPaths(efi_root, data_root), data_uuid, runner)


@contextmanager
def open_media(device: Path, runner: Runner, *, readonly: bool = False) -> Iterator[MediaPaths]:
    target = find_device(device, runner)
    if target.type not in ("disk", "loop") or target.name in protected_device_names(discover(runner), system_mount_sources()):
        raise SafetyError("Refusing a partition, virtual backing target, or protected system disk")
    before = target.identity()
    if not readonly and (target.mounted or target.readonly):
        raise SafetyError("Writable media operations require an unmounted, writable target")
    efi_part, data_part = discover_partitions(device, runner)
    efi = find_device(efi_part, runner)
    data = find_device(data_part, runner)
    if efi.fstype != "vfat" or efi.label != BRAND.efi_label or data.fstype != "ext4" or data.label != BRAND.data_label or not data.uuid:
        raise SafetyError("Filesystems do not match the FlexBoot EFI/data layout")
    revalidate_identity(before, find_device(device, runner).identity())
    with ExitStack() as stack:
        roots = []
        for part in (efi, data):
            reused = None
            if readonly and part.mountpoints:
                result = runner.run(["findmnt", "--json", "--source", str(part.path), "--output", "TARGET,OPTIONS"], check=False)
                if result.returncode == 0:
                    for entry in json.loads(result.stdout).get("filesystems", []):
                        if "ro" in entry["options"].split(","):
                            reused = Path(entry["target"])
                            break
            if reused is None:
                require_root()
                reused = stack.enter_context(mounted(part.path, readonly=readonly, runner=runner))
            roots.append(reused)
        paths = MediaPaths(*roots)
        for base, path in ((paths.data, paths.iso_dir), (paths.data, paths.data / BRAND.metadata_dir),
                           (paths.data, paths.manifest), (paths.efi, paths.grub_dir)):
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
                raise SafetyError(f"Media path escapes its filesystem or is a symlink: {path}")
        if Manifest.load(paths.manifest).data_filesystem_uuid != data.uuid:
            raise SafetyError("Manifest does not identify the actual data filesystem")
        yield paths
