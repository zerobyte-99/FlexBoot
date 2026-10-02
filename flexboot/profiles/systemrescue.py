from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class SystemRescueProfile:
    profile_id = "systemrescue"
    description = "SystemRescue"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        required = {
            "/boot/grub/loopback.cfg",
            "/sysresccd/boot/x86_64/vmlinuz",
            "/sysresccd/boot/x86_64/sysresccd.img",
        }
        if not required.issubset(inspection.paths):
            return None
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("loopback-config", configfile="/boot/grub/loopback.cfg", remove_tpm_module=True),
        )
