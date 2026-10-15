from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch
from .resources import live_kernel_pair


class GPartedLiveProfile:
    profile_id = "gparted-live"
    description = "GParted Live"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        if not ({"/GParted-Live-Version", "/live/GParted-Live-Version"} & paths):
            return None
        pair = live_kernel_pair(paths)
        if not pair or "/live/filesystem.squashfs" not in paths:
            return None
        # GParted requires its live user explicitly; generic Debian defaults
        # can leave the vendor's autologin command without a username.
        args = (
            "boot=live union=overlay username=user config components "
            "findiso=${iso_path} loglevel=3 noswap net.ifnames=0 nosplash "
            "ocs_1_cpu_udev scsi_mod.use_blk_mq=0 nvme.poll_queues=1"
        )
        return ProfileMatch(self.profile_id, self.description,
                            BootPlan("linux", pair[0], (pair[1],), args))
