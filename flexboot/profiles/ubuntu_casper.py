from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class UbuntuCasperProfile:
    profile_id = "ubuntu-casper"
    description = "Ubuntu family (casper)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        kernel = next((p for p in ("/casper/vmlinuz", "/casper/vmlinuz.efi") if p in paths), None)
        initrd = next((p for p in ("/casper/initrd", "/casper/initrd.lz", "/casper/initrd.gz") if p in paths), None)
        if not kernel or not initrd:
            return None
        server_layout = (
            "/casper/install-sources.yaml" in paths
            and "/casper/ubuntu-server-minimal.squashfs" in paths
        )
        standard_layout = any(p.startswith("/casper/filesystem.") for p in paths)
        if not server_layout and not standard_layout:
            return None
        if server_layout:
            return ProfileMatch("ubuntu-server-casper", "Ubuntu Server (casper)",
                                BootPlan("linux", kernel, (initrd,), "iso-scan/filename=${iso_path} ---"))
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("linux", kernel, (initrd,), "boot=casper iso-scan/filename=${iso_path} quiet splash --"),
        )
