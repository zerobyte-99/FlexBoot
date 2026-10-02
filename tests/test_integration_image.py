import os
import shutil
import tempfile
import unittest
from pathlib import Path

from flexboot.cli import main


class ImageIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__": unittest.main()
