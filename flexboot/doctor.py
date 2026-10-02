from __future__ import annotations

import platform
import shutil
from pathlib import Path

from .process import Runner

REQUIRED = {
    "python3": "python3", "lsblk": "util-linux", "findmnt": "util-linux", "sfdisk": "fdisk",
    "wipefs": "util-linux", "blockdev": "util-linux", "mkfs.fat": "dosfstools", "mkfs.ext4": "e2fsprogs",
    "losetup": "util-linux", "mount": "mount", "grub-install": "grub-efi-amd64-bin",
}
OPTIONAL = {"grub-script-check": "grub-common", "xorriso": "xorriso", "isoinfo": "genisoimage", "qemu-system-x86_64": "qemu-system-x86"}


def find_ovmf() -> str:
    candidates = (
        "/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/edk2/x64/OVMF_CODE.fd", "/usr/share/qemu/OVMF_CODE.fd",
    )
    return next((path for path in candidates if Path(path).is_file()), "")


def grub_target_available() -> bool:
    return any(path.is_dir() for path in (
        Path("/usr/lib/grub/x86_64-efi"), Path("/usr/lib/grub2/x86_64-efi"),
        Path("/usr/share/grub/x86_64-efi"),
    ))


def diagnose() -> dict[str, object]:
    required = {name: {"found": bool(shutil.which(name)), "package": package} for name, package in REQUIRED.items()}
    optional = {name: {"found": bool(shutil.which(name)), "package": package} for name, package in OPTIONAL.items()}
    optional["OVMF"] = {"found": bool(find_ovmf()), "path": find_ovmf(), "package": "ovmf"}
    version = ""
    if shutil.which("grub-install"):
        version = Runner().run(["grub-install", "--version"], check=False).stdout.strip()
    target = grub_target_available()
    return {
        "host": {"system": platform.system(), "release": platform.release(), "architecture": platform.machine()},
        "required": required, "optional": optional, "grub_version": version,
        "grub_target_x86_64_efi": target,
        "ready": all(item["found"] for item in required.values()) and target,
    }
