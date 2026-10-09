from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch
from .resources import live_kernel_pair


class DebianLiveProfile:
    profile_id = "debian-live"
    description = "Debian Live / Kali Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        pair = live_kernel_pair(paths)
        if not pair or "/live/filesystem.squashfs" not in paths:
            return None
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("linux", pair[0], (pair[1],), "boot=live components findiso=${iso_path}"),
        )
