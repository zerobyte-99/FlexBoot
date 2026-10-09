from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class RescuezillaProfile:
    profile_id = "rescuezilla"
    description = "Rescuezilla"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        marker = (inspection.volume_id or "").casefold().startswith("rescuezilla")
        marker = marker or "rescuezilla" in inspection.combined_text().casefold()
        kernel = next((path for path in ("/casper/vmlinuz", "/casper/vmlinuz.efi") if path in paths), None)
        initrd = next((path for path in ("/casper/initrd.lz", "/casper/initrd", "/casper/initrd.gz") if path in paths), None)
        live_root = "/casper/filesystem.squashfs" in paths
        if not marker or not kernel or not initrd or not live_root:
            return None
        args = "boot=casper iso-scan/filename=${iso_path} quiet noeject fastboot toram fsck.mode=skip noprompt splash"
        return ProfileMatch(self.profile_id, self.description, BootPlan("linux", kernel, (initrd,), args))
