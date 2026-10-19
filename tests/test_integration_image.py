import os
import hashlib
import struct
import shutil
import tempfile
import unittest
from pathlib import Path

from flexboot.cli import main
from flexboot.doctor import diagnose


class ImageIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("FLEXBOOT_RUN_IMAGE_TESTS") == "1", "set FLEXBOOT_RUN_IMAGE_TESTS=1 as root to run loop-image integration")
    def test_exfat_create_manage_and_verify_loop_image(self):
        from tests.test_compatibility import tiny_iso
        self.assertEqual(os.geteuid(), 0)
        if not diagnose("image-exfat")["ready"]:
            self.skipTest("exFAT provisioning dependencies unavailable")
        with tempfile.TemporaryDirectory(prefix="flexboot-integration-") as raw:
            root = Path(raw); image = root / "exfat.img"
            self.assertEqual(main(["image", "create", str(image), "--size", "2G", "--data-filesystem", "exfat"]), 0)
            self.assertEqual(main(["image", "inspect", str(image), "--json"]), 0)
            source = root / 'debian.iso'
            tiny_iso(source, {'/live/vmlinuz': b'kernel', '/live/initrd.img': b'initrd', '/live/filesystem.squashfs': b'root'})
            self.assertEqual(main(['add', str(image), str(source)]), 0)
            self.assertEqual(main(['menu', 'label', str(image), 'debian.iso', 'Portable Linux']), 0)
            self.assertEqual(main(['sync', str(image)]), 0)
            self.assertEqual(main(['verify', str(image), '--json']), 0)
            spaced = root / 'with spaces.iso'; shutil.copyfile(source, spaced)
            self.assertEqual(main(['add', str(image), str(spaced)]), 2)
            self.assertEqual(main(['verify', str(image), '--json']), 0)
            self.assertEqual(main(['remove', str(image), source.name]), 0)
            self.assertEqual(main(['verify', str(image), '--json']), 0)

    @unittest.skipUnless(os.environ.get("FLEXBOOT_RUN_IMAGE_TESTS") == "1", "set FLEXBOOT_RUN_IMAGE_TESTS=1 as root to run loop-image integration")
    def test_create_and_inspect_loop_image(self):
        self.assertEqual(os.geteuid(), 0, "image integration needs root for loop/mount")
        for command in ("losetup", "sfdisk", "mkfs.fat", "mkfs.ext4", "grub-install"):
            self.assertIsNotNone(shutil.which(command))
        with tempfile.TemporaryDirectory(prefix="flexboot-integration-") as raw:
            image = Path(raw) / "flexboot.img"
            self.assertEqual(main(["image", "create", str(image), "--size", "2G"]), 0)
            self.assertEqual(main(["image", "inspect", str(image), "--json"]), 0)
            self.assertGreater(image.stat().st_size, 1024**3)
            self.assertEqual(main(['menu', 'list', str(image), '--json']), 0)
            self.assertEqual(main(['menu', 'order', str(image)]), 0)
            self.assertEqual(main(['menu', 'reset', str(image)]), 0)
            self.assertEqual(main(['verify', str(image), '--json']), 0)

    @unittest.skipUnless(os.environ.get("FLEXBOOT_RUN_IMAGE_TESTS") == "1", "set FLEXBOOT_RUN_IMAGE_TESTS=1 as root to run loop-image integration")
    def test_explicit_windows_layout_provisioning_and_verification(self):
        self.assertEqual(os.geteuid(), 0, "image integration needs root for loop/mount")
        report = diagnose("windows")
        if not report["ready"]:
            self.skipTest("Windows provisioning dependencies missing: " + ", ".join(report["capabilities"]["windows"]["missing"]))
        for filesystem in ('ext4', 'exfat'):
            with self.subTest(data_filesystem=filesystem):
                if filesystem == 'exfat' and not diagnose('create-exfat')['ready']:
                    self.skipTest('exFAT provisioning dependencies unavailable')
                with tempfile.TemporaryDirectory(prefix="flexboot-integration-") as raw:
                    directory = Path(raw)
                    # Header fixtures exercise provisioning/integrity, not Windows boot.
                    # No third-party executable or Microsoft resource is needed here.
                    header = bytearray(1024)
                    header[:2] = b'MZ'
                    struct.pack_into('<I', header, 60, 128)
                    header[128:134] = b'PE\0\0\x64\x86'
                    helper = directory / 'helper.exe'
                    helper.write_bytes(header)
                    header[0x202:0x206] = b'HdrS'
                    loader = directory / 'ntloader'
                    loader.write_bytes(header)
                    image = directory / 'windows.img'
                    self.assertEqual(main(['image', 'create', str(image), '--size', '8G',
                                           '--windows-size', '4G', '--windows-boot-layout', 'basic-fat',
                                           '--ntloader', str(loader), '--ntloader-sha256', hashlib.sha256(header).hexdigest(),
                                           '--windows-helper', str(helper), '--data-filesystem', filesystem]), 0)
                    self.assertEqual(main(['image', 'inspect', str(image), '--json']), 0)
                    self.assertEqual(main(['verify', str(image), '--json']), 0)


if __name__ == "__main__": unittest.main()
