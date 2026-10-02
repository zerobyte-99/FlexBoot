from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class ArchisoProfile:
    profile_id = "archiso"
    description = "Arch Linux (archiso)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        root = "/arch/x86_64/airootfs.sfs" in paths
        kernel = any(path.startswith("/arch/boot/x86_64/vmlinuz") for path in paths)
        if "/boot/grub/loopback.cfg" not in paths or not root or not kernel:
            return None
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("loopback-config", configfile="/boot/grub/loopback.cfg"),
        )
