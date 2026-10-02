from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class ClonezillaProfile:
    profile_id = "clonezilla-live"
    description = "Clonezilla Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        if "/Clonezilla-Live-Version" not in paths:
            return None
        kernels = sorted(path for path in paths if path.startswith("/live/vmlinuz"))
        initrds = sorted(path for path in paths if path.startswith("/live/initrd"))
        if not kernels or not initrds or "/live/filesystem.squashfs" not in paths:
            return None
        args = (
            "boot=live config components union=overlay findiso=${iso_path} noswap edd=on "
            "nomodeset enforcing=0 noeject locales=en_US.UTF-8 keyboard-layouts=NONE "
            "ocs_live_run=ocs-live-general ocs_live_batch=no"
        )
        return ProfileMatch(self.profile_id, self.description,
                            BootPlan("linux", kernels[0], (initrds[0],), args))
