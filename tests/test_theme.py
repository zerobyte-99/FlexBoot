import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

from flexboot.cli import main
from flexboot.media import (
    MediaPaths, available_layouts, available_themes, configured_background,
    render_theme, resolve_builtin_theme, resolve_theme_layout, set_theme,
    theme_setting, validate_background,
)


class ThemeTests(unittest.TestCase):
    def test_names_and_numbers_resolve_stably(self):
        self.assertEqual(available_themes(), [
            "classic-grid", "ember-circuit", "orbital-lattice", "quantum-fold",
        ])
        self.assertEqual(resolve_builtin_theme("1"), "classic-grid")
        self.assertEqual(resolve_builtin_theme("ORBITAL_LATTICE"), "orbital-lattice")
        self.assertEqual(resolve_builtin_theme("background-quantum-fold.png"), "quantum-fold")
        self.assertIsNone(resolve_builtin_theme("99"))
        self.assertEqual(available_layouts(), ["flexboot", "kali"])
        self.assertEqual(resolve_theme_layout("normal"), "flexboot")
        self.assertEqual(resolve_theme_layout("KALI"), "kali")

    def test_builtin_selection_is_persistent_and_deployed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = MediaPaths(root / "efi", root / "data")
            setting = set_theme(paths, "2")
            self.assertEqual(setting["name"], "ember-circuit")
            self.assertEqual(theme_setting(paths), setting)
            deployed = paths.grub_dir / "themes/flexboot/background.png"
            self.assertEqual(deployed.read_bytes(), configured_background(paths).read_bytes())
            credit = paths.grub_dir / "themes/flexboot/credit.png"
            self.assertEqual(credit.read_bytes(), Path("flexboot/assets/credit.png").read_bytes())

    def test_layout_switch_preserves_background(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = MediaPaths(root / "efi", root / "data")
            set_theme(paths, "2")
            setting = set_theme(paths, "kali")
            self.assertEqual(setting["layout"], "kali")
            self.assertEqual(setting["name"], "ember-circuit")
            deployed = (paths.grub_dir / "themes/flexboot/theme.txt").read_text()
            self.assertEqual(deployed, render_theme("kali"))
            self.assertIn("left = 25%", deployed)
            self.assertNotIn("menu_pixmap_style", deployed)

    def test_normal_layout_has_requested_branding_and_position(self):
        rendered = render_theme("flexboot")
        self.assertNotIn("SELECT BOOT TARGET", rendered)
        self.assertIn("top = 20%", rendered)
        self.assertIn("left = 96%-620", rendered)
        self.assertIn("left = 96%-120", rendered)
        self.assertIn("width = 120", rendered)
        self.assertIn('file = "credit.png"', rendered)
        self.assertNotRegex(rendered, r"=\s*\d+\.\d+%")
        image_block = rendered.split("+ image {", 1)[1].split("}", 1)[0]
        self.assertNotIn("width =", image_block)
        self.assertNotIn("height =", image_block)
        asset = Path("flexboot/assets/credit.png").read_bytes()
        self.assertEqual(struct.unpack(">II", asset[16:24]), (460, 16))

    def test_custom_png_is_copied_to_media(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = MediaPaths(root / "efi", root / "data")
            source = Path("flexboot/assets/background-classic-grid.png").resolve()
            setting = set_theme(paths, source)
            self.assertEqual(setting["kind"], "custom")
            self.assertTrue(paths.custom_background.is_file())
            self.assertEqual(validate_background(paths.custom_background), (1920, 1080))
            self.assertEqual(configured_background(paths), paths.custom_background)

    def test_invalid_custom_image_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "not-an-image.png"
            path.write_text("not a PNG")
            with self.assertRaisesRegex(Exception, "must be PNG"):
                validate_background(path)

    def test_cli_list_and_custom_dry_run_are_unprivileged(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["theme", "--list"]), 0)
        self.assertIn("kali", output.getvalue())
        self.assertIn("1. classic-grid", output.getvalue())
        custom = Path("flexboot/assets/background-orbital-lattice.png").resolve()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["theme", "/dev/sdb", str(custom), "--dry-run"]), 0)
        self.assertIn("No changes made", output.getvalue())


if __name__ == "__main__": unittest.main()
