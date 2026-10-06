"""Shared capability checks for diagnostics, installation and write preflight."""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from .errors import DependencyError
from .process import Runner

PACKAGES = {
    "python3": "python3", "lsblk": "util-linux", "findmnt": "util-linux",
    "sfdisk": "fdisk", "wipefs": "util-linux", "blockdev": "util-linux",
    "mkfs.fat": "dosfstools", "mkfs.ext4": "e2fsprogs", "blkid": "util-linux",
    "losetup": "util-linux", "mount": "mount", "umount": "mount",
    "udevadm": "udev", "grub-install": "grub2-common",
    "grub-script-check": "grub2-common", "xorriso": "xorriso",
    "isoinfo": "genisoimage", "qemu-system-x86_64": "qemu-system-x86",
}
DISCOVERY = ("lsblk", "findmnt")
MEDIA = (*DISCOVERY, "blkid", "mount", "umount")
CREATE = (*MEDIA, "sfdisk", "wipefs", "blockdev", "mkfs.fat", "mkfs.ext4", "udevadm", "grub-install")
PROFILES = {"discovery": DISCOVERY, "media": MEDIA, "create": CREATE,
            "image": (*CREATE, "losetup"), "qemu": ("qemu-system-x86_64",)}
REQUIRED = {name: PACKAGES[name] for name in ("python3", *PROFILES["image"])}
OPTIONAL = {name: PACKAGES[name] for name in ("grub-script-check", "xorriso", "isoinfo", "qemu-system-x86_64")}
GRUB_MODULES = ("normal", "linux", "loopback", "part_gpt", "fat", "ext2", "search_fs_uuid",
                "efi_gop", "gfxterm", "gfxterm_background", "gfxmenu", "png", "font",
                "reboot", "halt")
GRUB_DIRECTORIES = (Path("/usr/lib/grub/x86_64-efi"), Path("/usr/lib/grub2/x86_64-efi"),
                    Path("/usr/share/grub/x86_64-efi"))
GRUB_FONT = Path("/usr/share/grub/unicode.pf2")


def find_ovmf() -> str:
    candidates = ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_CODE_4M.fd",
                  "/usr/share/edk2/x64/OVMF_CODE.fd", "/usr/share/qemu/OVMF_CODE.fd")
    return next((path for path in candidates if Path(path).is_file()), "")


def grub_target_available() -> bool:
    return any(all((directory / f"{name}.mod").is_file() for name in GRUB_MODULES)
               for directory in GRUB_DIRECTORIES)


def diagnose(profile: str = "create") -> dict[str, object]:
    if profile not in PROFILES:
        raise ValueError(f"Unknown capability: {profile}")
    commands = {name: {"found": bool(shutil.which(name)), "package": package}
                for name, package in PACKAGES.items()}
    target = grub_target_available()
    font = GRUB_FONT.is_file()
    firmware = find_ovmf()
    version = ""
    if commands["grub-install"]["found"]:
        probe = Runner().run(["grub-install", "--version"], check=False)
        commands["grub-install"]["usable"] = probe.returncode == 0
        version = probe.stdout.strip()
    host_ok = platform.system() == "Linux" and sys.version_info >= (3, 11)
    x64 = platform.machine().lower() in ("x86_64", "amd64")
    capabilities = {}
    for name, required in PROFILES.items():
        missing = [command for command in required if not commands[command]["found"] or not commands[command].get("usable", True)]
        if not host_ok:
            missing.append("Linux with Python >= 3.11")
        if name in ("create", "image"):
            if not x64:
                missing.append("x86-64 host")
            if not target:
                missing.append("GRUB x86_64-efi modules")
            if not font:
                missing.append("GRUB Unicode font")
        if name == "qemu" and not firmware:
            missing.append("OVMF")
        capabilities[name] = {"ready": not missing, "missing": missing}
    optional = {name: commands[name] for name in OPTIONAL}
    optional["OVMF"] = {"found": bool(firmware), "path": firmware, "package": "ovmf"}
    return {
        "host": {"system": platform.system(), "release": platform.release(),
                 "architecture": platform.machine(), "python": platform.python_version()},
        "profile": profile, "required": {name: commands[name] for name in PROFILES[profile]},
        "optional": optional, "capabilities": capabilities,
        "grub_version": version, "grub_target_x86_64_efi": target,
        "grub_unicode_font": font, "ready": capabilities[profile]["ready"],
    }


def preflight(profile: str = "create") -> dict[str, object]:
    result = diagnose(profile)
    if not result["ready"]:
        missing = result["capabilities"][profile]["missing"]
        raise DependencyError(f"Host is not ready for {profile}: " + ", ".join(missing)
                              + f"\nRun: flexboot doctor --for {profile}")
    return result
