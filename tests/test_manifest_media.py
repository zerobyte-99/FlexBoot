import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.errors import FlexBootError
from flexboot.manifest import ISORecord, Manifest, copy_and_hash, sha256_file
from flexboot.grub import base_config
from flexboot.media import MediaPaths, deploy_theme, regenerate, remove_iso, sync, verify
from flexboot.profiles.debian_live import DebianLiveProfile
from flexboot.profiles.base import ISOInspection


class ManifestTests(unittest.TestCase):
    def test_creation_update_hash_and_malformed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); path = root / "manifest.json"; source = root / "x"
            source.write_bytes(b"hello")
            manifest = Manifest(data_filesystem_uuid="uuid")
            manifest.isos.append(ISORecord("x.iso", 5, sha256_file(source), "debian-live", "/live/vmlinuz", "/live/initrd"))
            manifest.save(path)
            loaded = Manifest.load(path)
            self.assertEqual(loaded.isos[0].sha256, "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")
            path.write_text("{")
            with self.assertRaises(FlexBootError): Manifest.load(path)

    def test_copy_failure_removes_partial(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); src = root / "src.iso"; dst = root / "dst.iso"; src.write_bytes(b"data")
            with patch("os.replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError): copy_and_hash(src, dst)
            self.assertFalse((root / ".dst.iso.partial").exists())
            self.assertFalse(dst.exists())

    def test_schema_one_manifest_is_migrated(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            path.write_text(json.dumps({
                "schema_version": 1, "flexboot_version": "0.1.0",
                "created_utc": "2026-01-01T00:00:00Z", "updated_utc": "2026-01-01T00:00:00Z",
                "data_filesystem_uuid": "abcd", "isos": [{
                    "filename": "old.iso", "size": 1, "sha256": "a" * 64,
                    "profile": "debian-live", "kernel": "/live/vmlinuz", "initrd": "/live/initrd.img",
                }],
            }))
            manifest = Manifest.load(path)
            self.assertEqual(manifest.schema_version, 2)
            self.assertEqual(manifest.isos[0].boot_plan().kind, "linux")
            self.assertIn("findiso=", manifest.isos[0].boot_plan().args)

    def test_reconciliation_and_removal(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); paths = MediaPaths(root / "efi", root / "data")
            paths.iso_dir.mkdir(parents=True); paths.grub_dir.mkdir(parents=True)
            (paths.efi / "EFI/BOOT").mkdir(parents=True); (paths.efi / "EFI/BOOT/BOOTX64.EFI").write_bytes(b"x")
            content = b"iso"; (paths.iso_dir / "one.iso").write_bytes(content)
            manifest = Manifest(data_filesystem_uuid="1234-abcd", isos=[ISORecord("one.iso", 3, sha256_file(paths.iso_dir / "one.iso"), "debian-live", "/live/vmlinuz", "/live/initrd")])
            manifest.save(paths.manifest); regenerate(paths, manifest)
            (paths.grub_dir / "grub.cfg").write_text(base_config("1234-abcd"))
            deploy_theme(paths.efi)
            match = DebianLiveProfile().detect(ISOInspection(frozenset({"/live/vmlinuz", "/live/initrd", "/live/filesystem.squashfs"})))
            with patch("flexboot.media.require_supported", return_value=match):
                self.assertEqual(verify(paths), [])
            (paths.iso_dir / "extra.iso").write_bytes(b"x")
            self.assertTrue(any("absent from manifest" in x for x in verify(paths)))
            (paths.iso_dir / "extra.iso").unlink()
            remove_iso(paths, "one.iso")
            self.assertFalse((paths.iso_dir / "one.iso").exists())
            self.assertEqual(Manifest.load(paths.manifest).isos, [])

    def test_remove_rolls_back_file_and_manifest_when_menu_validation_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); paths = MediaPaths(root / "efi", root / "data")
            paths.iso_dir.mkdir(parents=True); paths.grub_dir.mkdir(parents=True)
            iso = paths.iso_dir / "one.iso"; iso.write_bytes(b"iso")
            record = ISORecord("one.iso", 3, sha256_file(iso), "debian-live", "/live/vmlinuz", "/live/initrd")
            manifest = Manifest(data_filesystem_uuid="uuid", isos=[record]); manifest.save(paths.manifest)
            regenerate(paths, manifest)
            with patch("flexboot.media.validate_config", side_effect=FlexBootError("bad menu")):
                with self.assertRaises(FlexBootError): remove_iso(paths, "one.iso")
            self.assertTrue(iso.exists())
            self.assertEqual(Manifest.load(paths.manifest).isos, [record])

    def test_sync_refreshes_stable_config_and_theme(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw); paths = MediaPaths(root / "efi", root / "data")
            paths.iso_dir.mkdir(parents=True); paths.grub_dir.mkdir(parents=True)
            Manifest(data_filesystem_uuid="1234-abcd").save(paths.manifest)
            (paths.grub_dir / "grub.cfg").write_text("old configuration\n")
            sync(paths)
            config = (paths.grub_dir / "grub.cfg").read_text()
            self.assertIn("set timeout=-1", config)
            self.assertIn("insmod efi_gop", config)
            theme = paths.grub_dir / "themes/flexboot"
            self.assertTrue((theme / "background.png").is_file())
            self.assertEqual(struct.unpack(">II", (theme / "select_nw.png").read_bytes()[16:24]), (8, 8))
            self.assertEqual(struct.unpack(">II", (theme / "menu_nw.png").read_bytes()[16:24]), (20, 20))


if __name__ == "__main__": unittest.main()
