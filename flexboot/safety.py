"""Fail-closed validation for destructive physical operations."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .devices import Device, DeviceIdentity, flatten, source_for_mountpoint
from .errors import SafetyError


def protected_device_names(devices: Iterable[Device], mount_sources: Iterable[str]) -> set[str]:
    roots = list(devices)
    all_devices = list(flatten(roots))
    parents = {d.name: d.parent_name for d in all_devices}
    def record_tree_parent(parent: Device) -> None:
        for child in parent.children:
            parents[child.name] = child.parent_name or parent.name
            record_tree_parent(child)
    for root in roots:
        record_tree_parent(root)
    protected: set[str] = set()
    for source in mount_sources:
        try:
            resolved = str(Path(source).resolve())
        except OSError:
            resolved = source
        match = next((d for d in all_devices if str(d.path.resolve()) == resolved), None)
        while match:
            protected.add(match.name)
            match = next((d for d in all_devices if d.name == parents.get(match.name)), None)
    return protected


def system_mount_sources() -> list[str]:
    sources: list[str] = []
    for point in ("/", "/boot", "/boot/efi"):
        source = source_for_mountpoint(point)
        if source.startswith("/dev/"):
            sources.append(source)
    try:
        for line in Path("/proc/swaps").read_text(encoding="utf-8").splitlines()[1:]:
            source = line.split()[0]
            if source.startswith("/dev/"):
                sources.append(source)
    except OSError:
        return sources
    return sources


def validate_physical_target(
    device: Device,
    *,
    protected_names: set[str],
    allow_non_usb: bool = False,
    allow_mounted: bool = False,
) -> None:
    if device.type != "disk":
        raise SafetyError(f"Target must be a whole disk; got type {device.type!r}: {device.path}")
    if device.name in protected_names:
        raise SafetyError(f"Refusing system or boot backing disk: {device.path}")
    if device.readonly:
        raise SafetyError(f"Target is read-only: {device.path}")
    if device.mounted and not allow_mounted:
        raise SafetyError(f"Target or a child partition is mounted: {device.path}")
    if device.transport.lower() != "usb" and not allow_non_usb:
        raise SafetyError("Physical target is not identified as USB; pass --allow-non-usb after reviewing the device")
    if device.size < 1024 * 1024 * 1024:
        raise SafetyError("Target is smaller than the 1 GiB minimum")


def revalidate_identity(before: DeviceIdentity, after: DeviceIdentity) -> None:
    failures: list[str] = []
    if before.resolved_path != after.resolved_path:
        failures.append("resolved path")
    if before.major_minor != after.major_minor:
        failures.append("major/minor")
    if before.serial and before.serial != after.serial:
        failures.append("serial")
    if before.by_id and before.by_id != after.by_id:
        failures.append("by-id path")
    if before.size != after.size:
        failures.append("capacity")
    if failures:
        raise SafetyError("Device identity changed before write: " + ", ".join(failures))


def check_unattended_confirmation(identity: DeviceIdentity, expected: str | None, confirmed: bool) -> None:
    if not confirmed or not expected:
        raise SafetyError("Unattended erase requires both --confirm-erase and --expect-identity")
    if expected != identity.fingerprint:
        raise SafetyError("Expected device identity does not match the selected target")
