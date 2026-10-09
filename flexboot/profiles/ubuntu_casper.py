from __future__ import annotations

import re

from .base import BootPlan, ISOInspection, ProfileMatch


class UbuntuCasperProfile:
    profile_id = "ubuntu-casper"
    description = "Ubuntu family (casper)"
    aliases = ("ubuntu-server-casper",)

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        paths = inspection.paths
        kernel = next((p for p in ("/casper/vmlinuz", "/casper/vmlinuz.efi") if p in paths), None)
        initrd = next((p for p in ("/casper/initrd", "/casper/initrd.lz", "/casper/initrd.gz", "/casper/initrd.img", "/casper/initrd.xz") if p in paths), None)
        if not kernel or not initrd:
            return None
        server_layout = (
            "/casper/install-sources.yaml" in paths
            and "/casper/ubuntu-server-minimal.squashfs" in paths
        )
        standard_layout = "/casper/filesystem.squashfs" in paths
        layers = [p for p in paths if re.fullmatch(r"/casper/[A-Za-z0-9_.+-]+\.live\.squashfs", p)]
        if not server_layout and not standard_layout and len(layers) != 1:
            return None
        if not server_layout and not standard_layout:
            # Casper derives every parent by removing the last dotted component.
            # A leaf alone would panic during initramfs startup.
            layer = layers[0].removesuffix(".squashfs")
            while True:
                if layer + ".squashfs" not in paths:
                    return None
                parent = layer.rsplit(".", 1)[0]
                if parent == layer:
                    break
                layer = parent
        if server_layout:
            return ProfileMatch("ubuntu-server-casper", "Ubuntu Server (casper)",
                                BootPlan("linux", kernel, (initrd,), "iso-scan/filename=${iso_path} ---"))
        layer_arg = f" layerfs-path={layers[0].rsplit('/', 1)[1]}" if not standard_layout and len(layers) == 1 else ""
        return ProfileMatch(
            self.profile_id, self.description,
            BootPlan("linux", kernel, (initrd,), f"boot=casper iso-scan/filename=${{iso_path}}{layer_arg} quiet splash --"),
        )
