"""Block device discovery using lsblk JSON."""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from .errors import FlexBootError
from .process import Runner

LSBLK_COLUMNS = "NAME,PATH,TYPE,PKNAME,MAJ:MIN,SIZE,MODEL,VENDOR,SERIAL,TRAN,RM,RO,PTTYPE,FSTYPE,LABEL,UUID,MOUNTPOINTS,PARTN,PARTTYPE"


@dataclass(frozen=True)
class Device:
    name: str
    path: Path
    type: str
    size: int
    major_minor: str = ""
    parent_name: str | None = None
    model: str = ""
    vendor: str = ""
    serial: str = ""
    transport: str = ""
    removable: bool = False
    readonly: bool = False
    pttype: str = ""
    fstype: str = ""
    label: str = ""
    uuid: str = ""
    mountpoints: tuple[str, ...] = ()
    children: tuple["Device", ...] = field(default_factory=tuple)
    partition_number: int = 0
    partition_type: str = ""

    def descendants(self) -> Iterable["Device"]:
        for child in self.children:
            yield child
            yield from child.descendants()

    @property
    def mounted(self) -> bool:
        return any(self.mountpoints) or any(child.mounted for child in self.children)

    def identity(self) -> "DeviceIdentity":
        return DeviceIdentity(
            resolved_path=str(self.path.resolve()), major_minor=self.major_minor,
            size=self.size, serial=self.serial, by_id=stable_by_id(self.path),
        )


@dataclass(frozen=True)
class DeviceIdentity:
    resolved_path: str
    major_minor: str
    size: int
    serial: str
    by_id: str = ""

    @property
    def fingerprint(self) -> str:
        return self.by_id or self.serial or f"{self.major_minor}:{self.size}"


def _integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _device(raw: dict[str, Any]) -> Device:
    mountpoints = raw.get("mountpoints") or []
    if isinstance(mountpoints, str):
        mountpoints = [mountpoints]
    return Device(
        name=str(raw.get("name") or ""), path=Path(raw.get("path") or f"/dev/{raw.get('name', '')}"),
        type=str(raw.get("type") or ""), size=_integer(raw.get("size")),
        major_minor=str(raw.get("maj:min") or ""), parent_name=raw.get("pkname"),
        model=str(raw.get("model") or "").strip(), vendor=str(raw.get("vendor") or "").strip(),
        serial=str(raw.get("serial") or "").strip(), transport=str(raw.get("tran") or "").strip(),
        removable=bool(_integer(raw.get("rm"))), readonly=bool(_integer(raw.get("ro"))),
        pttype=str(raw.get("pttype") or ""), fstype=str(raw.get("fstype") or ""),
        label=str(raw.get("label") or ""), uuid=str(raw.get("uuid") or ""),
        mountpoints=tuple(str(x) for x in mountpoints if x),
        children=tuple(_device(x) for x in raw.get("children") or []),
        partition_number=_integer(raw.get("partn")), partition_type=str(raw.get("parttype") or "").lower(),
    )


def parse_lsblk(text: str) -> list[Device]:
    try:
        payload = json.loads(text)
        return [_device(item) for item in payload.get("blockdevices", [])]
    except (json.JSONDecodeError, TypeError) as exc:
        raise FlexBootError(f"Could not parse lsblk output: {exc}") from exc


def transport_fallback(device: Device, runner: Runner) -> str:
    if device.type != "disk":
        return ""
    try:
        sysfs = (Path("/sys/class/block") / device.path.name / "device").resolve(strict=True)
        if any(re.fullmatch(r"usb\d+", part) for part in sysfs.parts):
            return "usb"
    except OSError:
        sysfs = None
    if shutil.which("udevadm"):
        result = runner.run(["udevadm", "info", "--query=property", f"--name={device.path}"], check=False)
        if result.returncode == 0:
            properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
            return properties.get("ID_BUS", "")
    return ""


def discover(runner: Runner | None = None, target: Path | None = None) -> list[Device]:
    run = runner or Runner()
    argv = ["lsblk", "--json", "--bytes", "--output", LSBLK_COLUMNS]
    if target:
        argv.append(str(target))
    result = run.run(argv, check=False)
    columns_index = argv.index(LSBLK_COLUMNS)
    while result.returncode and "unknown column" in result.stderr.lower():
        optional = next((name for name in ("TRAN", "PARTN") if name in result.stderr and name in argv[columns_index].split(",")), None)
        if optional is None:
            break
        argv[columns_index] = ",".join(name for name in argv[columns_index].split(",") if name != optional)
        result = run.run(argv, check=False)
    if result.returncode:
        raise FlexBootError("Device discovery failed: " + result.stderr.strip())
    def enrich(device: Device) -> Device:
        number = device.partition_number
        if device.type == "part" and not number:
            try:
                number = int((Path("/sys/class/block") / device.path.name / "partition").read_text().strip())
            except (OSError, ValueError):
                number = 0
        return replace(device, transport=device.transport or transport_fallback(device, run),
                       partition_number=number,
                       children=tuple(enrich(child) for child in device.children))
    return [enrich(device) for device in parse_lsblk(result.stdout)]


def flatten(devices: Iterable[Device]) -> Iterable[Device]:
    for device in devices:
        yield device
        yield from flatten(device.children)


def find_device(path: Path, runner: Runner | None = None) -> Device:
    resolved = path.resolve()
    devices = discover(runner, resolved)
    for device in flatten(devices):
        if device.path.resolve() == resolved:
            return device
    raise FlexBootError(f"Block device not found: {path}")


def stable_by_id(path: Path) -> str:
    base = Path("/dev/disk/by-id")
    if not base.is_dir():
        return ""
    resolved = path.resolve()
    for candidate in sorted(base.iterdir()):
        try:
            if candidate.resolve() == resolved and "-part" not in candidate.name:
                return str(candidate)
        except OSError:
            continue
    return ""


def format_size(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or suffix == "TiB":
            return f"{value:.1f} {suffix}"
        value /= 1024
    return f"{size} B"


def source_for_mountpoint(mountpoint: str, runner: Runner | None = None) -> str:
    run = runner or Runner()
    result = run.run(["findmnt", "--noheadings", "--output", "SOURCE", "--target", mountpoint], check=False)
    return result.stdout.strip() if result.returncode == 0 else ""
