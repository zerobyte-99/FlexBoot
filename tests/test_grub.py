import unittest

from flexboot.grub import base_config, generated_config, grub_quote
from flexboot.manifest import ISORecord


class GrubTests(unittest.TestCase):
    def record(self, name="Kali Live.iso"):
        return ISORecord(name, 10, "a" * 64, "debian-live", "/live/vmlinuz", "/live/initrd.img")

    def test_spaces_and_deterministic_sort(self):
        output = generated_config([self.record("z.iso"), self.record("Kali Live.iso")])
        self.assertIn("set iso_path='/iso/Kali Live.iso'", output)
        self.assertLess(output.index("Kali Live.iso"), output.index("z.iso"))
        self.assertEqual(output, generated_config([self.record("z.iso"), self.record("Kali Live.iso")]))

    def test_single_quote_is_escaped(self):
        self.assertEqual(grub_quote("user's.iso"), "'user'\\''s.iso'")

    def test_stable_uuid_and_no_linux_device_order(self):
        output = base_config("1234-abcd")
        self.assertIn("--fs-uuid --set=flexboot_data 1234-abcd", output)
        self.assertIn("insmod efi_gop", output)
        self.assertIn("set gfxmode=auto", output)
        self.assertIn("terminal_output gfxterm", output)
        self.assertIn("insmod gfxterm_background", output)
        self.assertIn("insmod gfxmenu", output)
        self.assertIn("loadfont ($root)/boot/grub/fonts/unicode.pf2", output)
        self.assertNotIn("flexboot-sans-32", output)
        self.assertIn("background_image --mode stretch", output)
        self.assertIn("set timeout=-1", output)
        self.assertNotIn("/dev/sd", output)
        self.assertNotIn("(hd0", output)

    def test_multiple_profiles(self):
        ubuntu = ISORecord("ubuntu.iso", 1, "b" * 64, "ubuntu-casper", "/casper/vmlinuz", "/casper/initrd")
        output = generated_config([ubuntu, self.record()])
        self.assertIn("iso-scan/filename=${iso_path}", output)
        self.assertIn("findiso=${iso_path}", output)

    def test_ubuntu_server_arguments_match_image_loopback_configuration(self):
        server = ISORecord("ubuntu-server.iso", 1, "c" * 64, "ubuntu-server-casper", "/casper/vmlinuz", "/casper/initrd")
        output = generated_config([server])
        self.assertIn("linux (loop)/casper/vmlinuz iso-scan/filename=${iso_path} ---", output)
        self.assertNotIn("boot=casper", output)

    def test_loopback_config_boot_plan(self):
        record = ISORecord(
            "systemrescue.iso", 1, "d" * 64, "systemrescue",
            boot_kind="loopback-config", configfile="/boot/grub/loopback.cfg",
            remove_tpm_module=True,
        )
        output = generated_config([record])
        self.assertIn("export iso_path", output)
        self.assertIn("rmmod tpm", output)
        self.assertIn("set root=(loop)", output)
        self.assertIn("configfile /boot/grub/loopback.cfg", output)

    def test_fedora_boot_plan_uses_recorded_label(self):
        record = ISORecord(
            "fedora.iso", 1, "e" * 64, "fedora-live",
            "/boot/x86_64/loader/linux", "/boot/x86_64/loader/initrd",
            "iso-scan/filename=${iso_path} root=live:CDLABEL=Fedora-WS-Live-44 ro rd.live.image",
        )
        output = generated_config([record])
        self.assertIn("root=live:CDLABEL=Fedora-WS-Live-44", output)
        self.assertIn("initrd (loop)/boot/x86_64/loader/initrd", output)


if __name__ == "__main__": unittest.main()
