import unittest

from flexboot.profiles import detect_profile
from flexboot.profiles.base import ISOInspection


class ProfileTests(unittest.TestCase):
    def test_ubuntu_casper(self):
        match = detect_profile({"casper/vmlinuz", "casper/initrd", "casper/filesystem.squashfs"})
        self.assertEqual(match.profile, "ubuntu-casper")

    def test_ubuntu_server_casper_layout(self):
        match = detect_profile({"casper/vmlinuz", "casper/initrd", "casper/install-sources.yaml", "casper/ubuntu-server-minimal.squashfs"})
        self.assertEqual(match.profile, "ubuntu-server-casper")
        self.assertEqual(match.boot_args, "iso-scan/filename=${iso_path} ---")

    def test_debian_and_kali_live_layout(self):
        match = detect_profile({"/live/vmlinuz-6.1", "/live/initrd.img-6.1", "/live/filesystem.squashfs"})
        self.assertEqual(match.profile, "debian-live")

    def test_installer_like_layout_is_not_claimed(self):
        self.assertIsNone(detect_profile({"/install.amd/vmlinuz", "/install.amd/initrd.gz"}))

    def test_missing_live_root_is_not_supported(self):
        self.assertIsNone(detect_profile({"/live/vmlinuz", "/live/initrd.img"}))

    def test_systemrescue_uses_vendor_loopback_config(self):
        match = detect_profile({
            "/boot/grub/loopback.cfg", "/sysresccd/boot/x86_64/vmlinuz",
            "/sysresccd/boot/x86_64/sysresccd.img",
        })
        self.assertEqual(match.profile, "systemrescue")
        self.assertEqual(match.boot.kind, "loopback-config")
        self.assertTrue(match.boot.remove_tpm_module)

    def test_archiso_uses_vendor_loopback_config(self):
        match = detect_profile({
            "/boot/grub/loopback.cfg", "/arch/x86_64/airootfs.sfs",
            "/arch/boot/x86_64/vmlinuz-linux",
        })
        self.assertEqual(match.profile, "archiso")
        self.assertEqual(match.boot.kind, "loopback-config")

    def test_rescuezilla_precedes_generic_casper(self):
        inspection = ISOInspection(frozenset({
            "/casper/vmlinuz", "/casper/initrd.lz", "/casper/filesystem.squashfs",
        }), "Rescuezilla")
        match = detect_profile(inspection)
        self.assertEqual(match.profile, "rescuezilla")
        self.assertIn("toram", match.boot_args)

    def test_clonezilla_precedes_generic_debian_live(self):
        match = detect_profile({
            "/Clonezilla-Live-Version", "/live/vmlinuz", "/live/initrd.img",
            "/live/filesystem.squashfs",
        })
        self.assertEqual(match.profile, "clonezilla-live")
        self.assertIn("ocs_live_run=ocs-live-general", match.boot_args)

    def test_fedora_44_loader_layout(self):
        inspection = ISOInspection(frozenset({
            "/LiveOS/squashfs.img", "/boot/x86_64/loader/linux",
            "/boot/x86_64/loader/initrd",
        }), "Fedora-WS-Live-44")
        match = detect_profile(inspection)
        self.assertEqual(match.profile, "fedora-live")
        self.assertIn("root=live:CDLABEL=Fedora-WS-Live-44", match.boot_args)

    def test_fedora_rejects_unsafe_or_missing_label(self):
        paths = frozenset({
            "/LiveOS/squashfs.img", "/boot/x86_64/loader/linux",
            "/boot/x86_64/loader/initrd",
        })
        self.assertIsNone(detect_profile(ISOInspection(paths, "Fedora bad; halt")))


if __name__ == "__main__": unittest.main()
