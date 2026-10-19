"""Shared media builder for validated disks and attached raw images."""
from __future__ import annotations

import os
import fcntl
import json
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

from .branding import BRAND
from .devices import discover, find_device
from .doctor import preflight
from .disk import ESP_GUID, data_partition_type, assert_loop_target, discover_partitions, format_partitions, partition_device, validate_partition_nodes
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


def build_attached(device: Path, runner: Runner, *, identity_check=None, windows_size: int = 0,
                   ntloader: Path | None = None, windows_helper: Path | None = None, ntloader_sha256: str = "",
                   boot_partition_role: str = "esp", data_filesystem: str = "ext4") -> None:
    if boot_partition_role != ("basic-fat" if windows_size else "esp"):
        raise SafetyError("Windows creation requires the explicit Basic Data FAT32 boot layout")
    require_root()
    data_partition_type(data_filesystem)
    preflight("create-exfat" if data_filesystem == "exfat" else "create")
    if windows_size:
        from .windows import require_runtime
        preflight("windows")
        if ntloader is None or windows_helper is None:
            raise FlexBootError("Windows creation requires local NTloader, expected SHA-256, and helper")
        require_runtime(ntloader, ntloader_sha256, windows_helper)
    if identity_check:
        identity_check()
    else:
        assert_loop_target(device)
    partition_device(device, runner, windows_size=windows_size, boot_partition_role=boot_partition_role, data_filesystem=data_filesystem)
    partitions = discover_partitions(device, runner, include_windows=bool(windows_size), boot_partition_role=boot_partition_role, data_filesystem=data_filesystem)
    efi_part, data_part = partitions[:2]
    if identity_check:
        identity_check()
    validate_partition_nodes(device, runner)
    format_partitions(efi_part, data_part, runner, data_filesystem=data_filesystem)
    data_uuid = filesystem_uuid(data_part, runner)
    with ExitStack() as stack:
        efi_root = stack.enter_context(mounted(efi_part, runner=runner))
        data_root = stack.enter_context(mounted(data_part, runner=runner))
        win_root = None
        win_uuid = ""
        if windows_size:
            runner.run(["mkfs.ntfs", "-F", "-Q", "-L", BRAND.windows_label, str(partitions[2])], mutate=True)
            win_uuid = filesystem_uuid(partitions[2], runner)
            win_root = stack.enter_context(mounted(partitions[2], runner=runner))
        paths = MediaPaths(efi_root, data_root, win_root, win_uuid, filesystem_uuid(efi_part, runner), boot_partition_role, data_filesystem)
        install_grub(efi_root, runner)
        initialize(paths, data_uuid, runner)
        if windows_size:
            from .windows import initialize as initialize_windows
            initialize_windows(paths, ntloader, windows_helper, ntloader_sha256, runner)


@contextmanager
def open_media(device: Path, runner: Runner, *, readonly: bool = False) -> Iterator[MediaPaths]:
    target = find_device(device, runner)
    if target.type not in ("disk", "loop") or target.name in protected_device_names(discover(runner), system_mount_sources()):
        raise SafetyError("Refusing a partition, virtual backing target, or protected system disk")
    before = target.identity()
    if not readonly and (target.mounted or target.readonly):
        raise SafetyError("Writable media operations require an unmounted, writable target")
    data_candidates = [child for child in target.children if child.type == "part" and child.partition_number == 2]
    if len(data_candidates) != 1 or data_candidates[0].fstype not in ("ext4", "exfat"):
        raise SafetyError("FlexBoot data partition must be ext4 or exfat")
    data_filesystem = data_candidates[0].fstype
    partitions = discover_partitions(device, runner, include_windows=True, data_filesystem=data_filesystem)
    efi_part, data_part = partitions[:2]
    validate_partition_nodes(device, runner)
    efi = find_device(efi_part, runner)
    data = find_device(data_part, runner)
    if efi.fstype != "vfat" or efi.label != BRAND.efi_label or data.fstype != data_filesystem or data.label != BRAND.data_label or not data.uuid:
        raise SafetyError("Filesystems do not match the FlexBoot EFI/data layout")
    revalidate_identity(before, find_device(device, runner).identity())
    with ExitStack() as stack:
        roots = []
        parts = [efi, data]
        win_uuid = ""
        if len(partitions) == 3:
            win = find_device(partitions[2], runner)
            if win.fstype != "ntfs" or win.label != BRAND.windows_label or not win.uuid:
                raise SafetyError("Windows filesystem does not match the optional layout")
            parts.append(win); win_uuid = win.uuid
        for part in parts:
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
        boot_role = "esp" if efi.partition_type == ESP_GUID else "basic-fat"
        paths = MediaPaths(roots[0], roots[1], roots[2] if len(roots)>2 else None, win_uuid, efi.uuid, boot_role, data_filesystem)
        for base, path in ((paths.data, paths.iso_dir), (paths.data, paths.data / BRAND.metadata_dir),
                           (paths.data, paths.manifest), (paths.efi, paths.grub_dir)):
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
                raise SafetyError(f"Media path escapes its filesystem or is a symlink: {path}")
        lock_path = paths.data / BRAND.metadata_dir / "lock"
        if not readonly or lock_path.exists():
            flags = os.O_RDONLY if readonly else os.O_RDWR | os.O_CREAT
            lock_fd = os.open(lock_path, flags | os.O_NOFOLLOW, 0o600)
            stack.callback(os.close, lock_fd)
            try:
                fcntl.flock(lock_fd, (fcntl.LOCK_SH if readonly else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SafetyError("Media is already in use by another FlexBoot operation") from exc
        if Manifest.load(paths.manifest).data_filesystem_uuid != data.uuid:
            raise SafetyError("Manifest does not identify the actual data filesystem")
        if paths.windows is not None:
            for path in (paths.windows / "windows", paths.windows / ".flexboot-windows"):
                if path.is_symlink() or not path.is_dir() or not path.resolve().is_relative_to(paths.windows.resolve()):
                    raise SafetyError(f"Invalid owned Windows media directory: {path}")
        from .windows import load as load_windows
        load_windows(paths)
        yield paths
