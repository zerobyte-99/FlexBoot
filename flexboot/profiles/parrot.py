from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch
from .resources import live_kernel_pair


class ParrotLiveProfile:
    profile_id = "parrot-live"
    description = "Parrot Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        if not (inspection.volume_id or "").casefold().startswith("parrot "):
            return None
        if "hostname=parrot" not in inspection.text_files.get("/boot/grub/grub.cfg", ""):
            return None
        pair = live_kernel_pair(inspection.paths)
        if not pair or "/live/filesystem.squashfs" not in inspection.paths:
            return None
        # Preserve the vendor's noautomount behavior and default ephemeral mode.
        args = "boot=live hostname=parrot components findiso=${iso_path} noautomount noeject"
        return ProfileMatch(self.profile_id, self.description,
                            BootPlan("linux", pair[0], (pair[1],), args))
