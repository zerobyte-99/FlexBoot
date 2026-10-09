from __future__ import annotations

import re

from .base import BootPlan, ISOInspection, ProfileMatch


class GentooLiveProfile:
    profile_id = "gentoo-live"
    description = "Gentoo Live (amd64, dracut)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        required = {"/boot/gentoo", "/boot/gentoo.igz", "/image.squashfs", "/livecd"}
        label = inspection.volume_id or ""
        config = inspection.text_files.get("/boot/grub/grub.cfg", "")
        if not required.issubset(inspection.paths) or not re.fullmatch(r"Gentoo-(?:amd64|x86_64)[A-Za-z0-9_.+-]*", label):
            return None
        command_lines = re.findall(r"^\s*linux(?:efi)?\s+/boot/gentoo\s+([^\n]+)", config, re.MULTILINE)
        if not any("rd.live.squashimg=image.squashfs" in line.split() and f"root=live:CDLABEL={label}" in line.split() for line in command_lines):
            # Legacy genkernel's isoboot path is a different mechanism.
            return None
        args = f"iso-scan/filename=${{iso_path}} root=live:CDLABEL={label} rd.live.dir=/ rd.live.squashimg=image.squashfs cdroot ro"
        return ProfileMatch(self.profile_id, self.description, BootPlan("linux", "/boot/gentoo", ("/boot/gentoo.igz",), args))
