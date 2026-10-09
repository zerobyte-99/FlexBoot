from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch
from .resources import live_kernel_pair


class ClonezillaProfile:
    profile_id = "clonezilla-live"
    description = "Clonezilla Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        if "/Clonezilla-Live-Version" not in paths:
            return None
        pair = live_kernel_pair(paths)
        if not pair or "/live/filesystem.squashfs" not in paths:
            return None
        args = (
            "boot=live config components union=overlay findiso=${iso_path} noswap edd=on "
            "nomodeset enforcing=0 noeject locales=en_US.UTF-8 keyboard-layouts=NONE "
            "ocs_live_run=ocs-live-general ocs_live_batch=no"
        )
        return ProfileMatch(self.profile_id, self.description,
                            BootPlan("linux", pair[0], (pair[1],), args))
