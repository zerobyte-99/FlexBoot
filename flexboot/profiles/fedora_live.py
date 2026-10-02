from __future__ import annotations

import re

from .base import BootPlan, ISOInspection, ProfileMatch


_SAFE_LABEL = re.compile(r"^[A-Za-z0-9_.+:-]+$")


class FedoraLiveProfile:
    profile_id = "fedora-live"
    description = "Fedora Live (dracut)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        volume_id = inspection.volume_id or ""
        config_marker = "rd.live.image" in inspection.combined_text()
        if "/LiveOS/squashfs.img" not in paths or not (volume_id.startswith("Fedora-") or config_marker):
            return None
        if not volume_id or not _SAFE_LABEL.fullmatch(volume_id):
            return None
        kernel = next((path for path in (
            "/boot/x86_64/loader/linux", "/images/pxeboot/vmlinuz",
            "/isolinux/vmlinuz", "/isolinux/vmlinuz0",
        ) if path in paths), None)
        initrd = next((path for path in (
            "/boot/x86_64/loader/initrd", "/images/pxeboot/initrd.img",
            "/isolinux/initrd.img", "/isolinux/initrd0.img",
        ) if path in paths), None)
        if not kernel or not initrd:
            return None
        args = f"iso-scan/filename=${{iso_path}} root=live:CDLABEL={volume_id} ro rd.live.image quiet rhgb"
        return ProfileMatch(self.profile_id, self.description, BootPlan("linux", kernel, (initrd,), args))
