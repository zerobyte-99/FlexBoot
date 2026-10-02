import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.process import Runner
from flexboot.targets import attached_image


class CleanupTests(unittest.TestCase):
    def test_loop_detached_after_exception(self):
        calls = []
        def fake_run(self, argv, **kwargs):
            import subprocess
            calls.append(list(argv))
            if argv[0] == "losetup" and "--show" in argv:
                return subprocess.CompletedProcess(argv, 0, "/dev/loop99\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "x.img"; image.write_bytes(b"x")
            with patch.object(Runner, "run", fake_run):
                with self.assertRaises(RuntimeError):
                    with attached_image(image, Runner()): raise RuntimeError("boom")
        self.assertIn(["losetup", "--detach", "/dev/loop99"], calls)


if __name__ == "__main__": unittest.main()
