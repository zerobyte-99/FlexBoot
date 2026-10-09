from __future__ import annotations

import re

from .base import BootPlan, ISOInspection, ProfileMatch


class GrmlLiveProfile:
    profile_id = "grml-live"
    description = "Grml Live (amd64)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        bootid = inspection.text_files.get("/conf/bootid.txt", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,80}", bootid):
            return None
        candidates = []
        for payload in sorted(paths):
            match = re.fullmatch(r"/live/(grml-(?:full|small|medium)-amd64|grml64-(?:full|small|medium))/\1\.squashfs", payload)
            if not match:
                continue
            flavour = match[1]
            compact = flavour.replace("-", "")
            kernel = f"/boot/{compact}/vmlinuz"
            initrd = f"/boot/{compact}/initrd.img"
            if kernel in paths and initrd in paths and bootid.startswith(compact):
                args = f"boot=live findiso=${{iso_path}} live-media-path=/live/{flavour}/ bootid={bootid} noeject noprompt"
                candidates.append(ProfileMatch(self.profile_id, self.description, BootPlan("linux", kernel, (initrd,), args)))
        return candidates[0] if len(candidates) == 1 else None
