"""GPT, filesystem, and partition discovery operations."""
from __future__ import annotations

from pathlib import Path

from .branding import BRAND
from .devices import discover
from .errors import FlexBootError, SafetyError
from .process import Runner

ESP_MIB = 512


def partition_device(device: Path, runner: Runner) -> None:
    """Create exactly two GPT partitions. Caller must complete safety checks first."""
    sector_result = runner.run(["blockdev", "--getss", str(device)], check=False)
    try:
        sector_size = int(sector_result.stdout.strip()) if sector_result.returncode == 0 else 512
    except ValueError:
        sector_size = 512
    if sector_size not in (512, 1024, 2048, 4096):
        raise FlexBootError(f"Unsupported logical sector size {sector_size} on {device}")
    esp_sectors = ESP_MIB * 1024 * 1024 // sector_size
    layout = (
        "label: gpt\n"
        "unit: sectors\n"
        "\n"
        f"size={esp_sectors}, type=U, name=\"{BRAND.product_name} EFI\"\n"
        f"type=L, name=\"{BRAND.product_name} Data\"\n"
    )
    runner.run(["wipefs", "--all", "--force", str(device)], mutate=True)
    runner.run(["sfdisk", "--wipe", "always", str(device)], input_text=layout, mutate=True)
    runner.run(["partprobe", str(device)], check=False, mutate=True)
    runner.run(["udevadm", "settle"], mutate=True)


def discover_partitions(device: Path, runner: Runner) -> tuple[Path, Path]:
    roots = discover(runner, device)
    root = next((item for item in roots if item.path.resolve() == device.resolve()), None)
    if not root:
        raise FlexBootError(f"Target disappeared after partitioning: {device}")
    parts = [child for child in root.children if child.type == "part"]
    if len(parts) != 2:
        raise FlexBootError(f"Expected two partitions on {device}, found {len(parts)}")
    parts.sort(key=lambda item: item.path.name)
    return parts[0].path, parts[1].path


def format_partitions(efi: Path, data: Path, runner: Runner) -> None:
    runner.run(["mkfs.fat", "-F", "32", "-n", BRAND.efi_label, str(efi)], capture=False, mutate=True)
    runner.run(["mkfs.ext4", "-F", "-L", BRAND.data_label, str(data)], capture=False, mutate=True)
    runner.run(["udevadm", "settle"], mutate=True)


def assert_loop_target(device: Path) -> None:
    """Integration-test guard: only loop devices may enter autonomous image builds."""
    if not str(device.resolve()).startswith("/dev/loop"):
        raise SafetyError(f"Image build guard rejected non-loop target: {device}")
