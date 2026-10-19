"""GPT, filesystem, and partition discovery operations."""
from __future__ import annotations

from pathlib import Path
import re
import os
import stat

from .branding import BRAND
from .devices import discover
from .errors import FlexBootError, SafetyError
from .process import Runner

ESP_MIB = 512
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
BASIC_DATA_GUID = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
LINUX_DATA_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"


def data_partition_type(filesystem: str) -> str:
    if filesystem not in ("ext4", "exfat"):
        raise SafetyError("Data filesystem must be ext4 or exfat")
    return LINUX_DATA_GUID if filesystem == "ext4" else BASIC_DATA_GUID


def partition_device(device: Path, runner: Runner, *, windows_size: int = 0,
                     boot_partition_role: str = "esp", data_filesystem: str = "ext4") -> None:
    """Create the GPT layout, including Windows only when explicitly reserved."""
    if boot_partition_role not in ("esp", "basic-fat") or (boot_partition_role == "basic-fat" and not windows_size):
        raise SafetyError("The Basic Data boot layout requires an explicit Windows reserve")
    data_type = data_partition_type(data_filesystem)
    sector_result = runner.run(["blockdev", "--getss", str(device)])
    try:
        sector_size = int(sector_result.stdout.strip())
    except ValueError as exc:
        raise FlexBootError("Cannot determine logical sector size; refusing to erase") from exc
    if sector_size not in (512, 1024, 2048, 4096):
        raise FlexBootError(f"Unsupported logical sector size {sector_size} on {device}")
    esp_sectors = ESP_MIB * 1024 * 1024 // sector_size
    layout = (
        "label: gpt\n"
        "unit: sectors\n"
        "\n"
        f"size={esp_sectors}, type=U, name=\"{BRAND.product_name} EFI\"\n"
        f"type={data_type}, name=\"{BRAND.product_name} Data\"\n"
    )
    if windows_size:
        try:
            capacity = int(runner.run(["blockdev", "--getsize64", str(device)]).stdout.strip())
        except ValueError as exc:
            raise FlexBootError("Cannot determine target capacity; refusing to erase") from exc
        if windows_size < 4 * 1024**3 or capacity - windows_size < 2 * 1024**3:
            raise FlexBootError("Windows partition needs at least 4 GiB; leave at least 2 GiB for EFI/Linux")
        # Explicit sizes leave room for both GPT headers and MiB alignment.
        linux_sectors = (capacity - windows_size - (ESP_MIB + 4) * 1024**2) // sector_size
        boot_type = "U" if boot_partition_role == "esp" else BASIC_DATA_GUID
        layout = ("label: gpt\nunit: sectors\n\n"
                  f'size={esp_sectors}, type={boot_type}, name="{BRAND.product_name} EFI"\n'
                  f'size={linux_sectors}, type={data_type}, name="{BRAND.product_name} Data"\n'
                  f'type={BASIC_DATA_GUID}, name="{BRAND.product_name} Windows"\n')
    runner.run(["wipefs", "--all", "--force", str(device)], mutate=True)
    runner.run(["sfdisk", "--wipe", "always", str(device)], input_text=layout, mutate=True)
    runner.run(["blockdev", "--rereadpt", str(device)], mutate=True)
    runner.run(["udevadm", "settle"], mutate=True)


def discover_partitions(device: Path, runner: Runner, *, include_windows: bool = False,
                        boot_partition_role: str | None = None, data_filesystem: str = "ext4") -> tuple[Path, ...]:
    roots = discover(runner, device)
    root = next((item for item in roots if item.path.resolve() == device.resolve()), None)
    if not root:
        raise FlexBootError(f"Target disappeared after partitioning: {device}")
    parts = [child for child in root.children if child.type == "part"]
    if len(parts) not in ((2, 3) if include_windows else (2,)):
        raise FlexBootError(f"Expected two partitions on {device}, found {len(parts)}")
    if root.pttype != "gpt":
        raise SafetyError("Target must have a GPT partition table")
    parts.sort(key=lambda item: item.partition_number)
    if [part.partition_number for part in parts] != list(range(1, len(parts) + 1)):
        raise SafetyError("Expected partition numbers 1 and 2")
    allowed_boot_types = {ESP_GUID}
    if include_windows and len(parts) == 3:
        allowed_boot_types.add(BASIC_DATA_GUID)
    if boot_partition_role is not None:
        if boot_partition_role not in ("esp", "basic-fat"):
            raise SafetyError("Unknown requested boot partition role")
        allowed_boot_types &= {ESP_GUID if boot_partition_role == "esp" else BASIC_DATA_GUID}
    if parts[0].partition_type not in allowed_boot_types or parts[1].partition_type != data_partition_type(data_filesystem):
        raise SafetyError("Target partition roles do not match FlexBoot EFI/data layout")
    if len(parts) == 3 and parts[2].partition_type != BASIC_DATA_GUID:
        raise SafetyError("Third partition must have the Windows data role")
    return tuple(part.path for part in parts)


def format_partitions(efi: Path, data: Path, runner: Runner, *, data_filesystem: str = "ext4") -> None:
    data_partition_type(data_filesystem)
    runner.run(["mkfs.fat", "-F", "32", "-n", BRAND.efi_label, str(efi)], capture=False, mutate=True)
    command = ["mkfs.ext4", "-F", "-L", BRAND.data_label, str(data)] if data_filesystem == "ext4" else ["mkfs.exfat", "-L", BRAND.data_label, str(data)]
    runner.run(command, capture=False, mutate=True)
    runner.run(["udevadm", "settle"], mutate=True)


def assert_loop_target(device: Path) -> None:
    """Integration-test guard: only loop devices may enter autonomous image builds."""
    if not re.fullmatch(r"/dev/loop\d+", str(device.resolve())):
        raise SafetyError(f"Image build guard rejected non-loop target: {device}")


def validate_partition_nodes(device: Path, runner: Runner) -> None:
    """Bind discovered topology to actual node identities before format/mount."""
    roots = discover(runner, device)
    root = next((item for item in roots if item.path.resolve() == device.resolve()), None)
    if root is None:
        raise SafetyError("Target disappeared before partition use")
    for part in root.children:
        if part.type != "part":
            continue
        try:
            major, minor = map(int, part.major_minor.split(":"))
            current = part.path.stat()
        except (OSError, ValueError) as exc:
            raise SafetyError("Partition node is unavailable or has no recorded identity") from exc
        if not stat.S_ISBLK(current.st_mode) or current.st_rdev != os.makedev(major, minor):
            raise SafetyError(f"Partition node identity differs from discovered topology: {part.path}")
