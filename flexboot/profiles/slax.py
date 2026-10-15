from __future__ import annotations

from .base import BootPlan, ISOInspection, ProfileMatch


class SlaxProfile:
    profile_id = "slax-live"
    description = "Slax Live (Linux Live Kit)"

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None:
        required = {
            "/slax/boot/vmlinuz", "/slax/boot/initrfs.img",
            "/slax/boot/syslinux.cfg", "/slax/modules/01-core.sb",
        }
        config = inspection.text_files.get("/slax/boot/syslinux.cfg", "")
        if not required.issubset(inspection.paths) or (inspection.volume_id or "").casefold() != "slax":
            return None
        if "Slax" not in config or "/slax/boot/vmlinuz" not in config or "/slax/boot/initrfs.img" not in config:
            return None
        # Linux Live Kit locates and mounts this exact ISO using from=. Omit
        # perchdir and automount: changes stay in RAM and persistence is opt-in.
        args = "from=${iso_path} load_ramdisk=1 prompt_ramdisk=0 rw printk.time=0 consoleblank=0"
        return ProfileMatch(self.profile_id, self.description,
                            BootPlan("linux", "/slax/boot/vmlinuz", ("/slax/boot/initrfs.img",), args))
