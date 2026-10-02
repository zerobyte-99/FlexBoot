import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.cli import main
from flexboot.errors import SafetyError
from flexboot.process import Runner
from flexboot.targets import create_sparse, parse_size
from flexboot.disk import assert_loop_target


class TargetTests(unittest.TestCase):
    def test_size_parser(self):
        self.assertEqual(parse_size("8G"), 8 * 1024**3)

    def test_sparse_dry_run_has_zero_changes(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "test.img"; runner = Runner(dry_run=True)
            create_sparse(path, 2 * 1024**3, runner=runner)
            self.assertFalse(path.exists())
            self.assertEqual(runner.planned[0][0], "truncate")

    def test_image_cli_dry_run(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "test.img"
            self.assertEqual(main(["image", "create", str(path), "--size", "2G", "--dry-run"]), 0)
            self.assertFalse(path.exists())

    def test_autonomous_guard_rejects_physical_names(self):
        with self.assertRaises(SafetyError): assert_loop_target(Path("/dev/sda"))


if __name__ == "__main__": unittest.main()

