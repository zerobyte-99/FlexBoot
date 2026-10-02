from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class DebianLiveProfile:
    profile_id = "debian-live"
    description = "Debian Live / Kali Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        kernels = sorted(p for p in paths if p.startswith("/live/vmlinuz"))
        initrds = sorted(p for p in paths if p.startswith("/live/initrd"))
        if not kernels or not initrds or "/live/filesystem.squashfs" not in paths:
            return None
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("linux", kernels[0], (initrds[0],), "boot=live components findiso=${iso_path}"),
        )
