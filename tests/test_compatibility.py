import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.cli import main
from flexboot.boot_paths import alias_path, alias_problems, ensure_aliases, iso_boot_path
from flexboot.errors import FlexBootError
from flexboot.iso import inspect_iso
from flexboot.iso9660 import Entry, ISO9660Reader, SECTOR
from flexboot.manifest import ISORecord, Manifest
from flexboot.media import MediaPaths, add_iso, regenerate, remove_iso, sync, verify
from flexboot.profiles import detect_profile
from flexboot.profiles.base import ISOInspection


def tiny_iso(path, files, label="TEST"):
    """Minimal ISO9660 directory fixture; never attaches or mounts storage."""
    directories = {"/"}
    for name in files:
        directories.update(str(parent) for parent in Path(name).parents)
    nodes = sorted(directories) + sorted(files)
    extents = {name: 20 + index for index, name in enumerate(nodes)}
    sizes = {name: SECTOR if name in directories else len(files[name]) for name in nodes}

    def record(name, node):
        raw = name.encode("ascii")
        result = bytearray(33 + len(raw) + (len(raw) % 2 == 0))
        result[0] = len(result)
        result[2:6] = extents[node].to_bytes(4, "little")
        result[10:14] = sizes[node].to_bytes(4, "little")
        result[25] = 2 if node in directories else 0
        result[32] = len(raw)
        result[33:33 + len(raw)] = raw
        return result

    image = bytearray((20 + len(nodes)) * SECTOR)
    descriptor = bytearray(SECTOR)
    descriptor[:7] = b"\x01CD001\x01"
    descriptor[40:72] = label.encode().ljust(32, b" ")
    descriptor[156:190] = record("\0", "/")
    image[16 * SECTOR:17 * SECTOR] = descriptor
    image[17 * SECTOR:17 * SECTOR + 7] = b"\xffCD001\x01"
    for node in nodes:
        if node in directories:
            content = b"".join(record(Path(child).name, child) for child in nodes
                               if child != "/" and str(Path(child).parent) == node)
        else:
            content = files[node]
        start = extents[node] * SECTOR
        image[start:start + len(content)] = content
    path.write_bytes(image)


class CompatibilityTests(unittest.TestCase):
    def grml(self, bootid="grmlsmallamd64202609"):
        return ISOInspection(frozenset({
            "/boot/grmlsmallamd64/vmlinuz", "/boot/grmlsmallamd64/initrd.img",
            "/live/grml-small-amd64/grml-small-amd64.squashfs",
        }), "grml", {"/conf/bootid.txt": bootid})

    def gentoo(self, config=None):
        label = "Gentoo-amd64-20260913"
        return ISOInspection(frozenset({"/boot/gentoo", "/boot/gentoo.igz", "/image.squashfs", "/livecd"}),
                             label, {"/boot/grub/grub.cfg": config if config is not None else
                                     f"linux /boot/gentoo root=live:CDLABEL={label} rd.live.squashimg=image.squashfs"})

    def test_grml_requires_matching_safe_bootid(self):
        match = detect_profile(self.grml())
        self.assertEqual(match.profile, "grml-live")
        self.assertIn("live-media-path=/live/grml-small-amd64/", match.boot_args)
        for value in ("", "grmlfullamd64202609", "grmlsmallamd64;halt", "grmlsmallamd64\nreboot"):
            self.assertIsNone(detect_profile(self.grml(value)))

    def test_gentoo_requires_current_dracut_recipe(self):
        self.assertEqual(detect_profile(self.gentoo()).profile, "gentoo-live")
        for config in ("linux /boot/gentoo isoboot=/iso/gentoo.iso", "# linux /boot/gentoo root=live:CDLABEL=Gentoo-amd64-20260913 rd.live.squashimg=image.squashfs",
                       "linux /boot/gentoo root=live:CDLABEL=wrong rd.live.squashimg=image.squashfs"):
            self.assertIsNone(detect_profile(self.gentoo(config)))

    def test_new_profiles_roundtrip_manifest(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            for facts in (self.grml(), self.gentoo()):
                match = detect_profile(facts)
                record = ISORecord("example.iso", 1, "a" * 64, match.profile, match.kernel, match.initrd,
                                   boot_args=match.boot_args)
                Manifest(data_filesystem_uuid="abcd-1234", isos=[record]).save(path)
                self.assertEqual(Manifest.load(path).isos[0].boot_plan(), match.boot)

    def test_live_pairs_must_match_and_be_unambiguous(self):
        root = {"/live/filesystem.squashfs"}
        self.assertIsNone(detect_profile(root | {"/live/vmlinuz-6.1", "/live/initrd.img-6.2"}))
        pairs = root | {"/live/vmlinuz-6.1", "/live/initrd.img-6.1", "/live/vmlinuz-6.2", "/live/initrd.img-6.2"}
        self.assertIsNone(detect_profile(pairs))
        match = detect_profile(pairs | {"/live/vmlinuz", "/live/initrd.img"})
        self.assertEqual(match.kernel, "/live/vmlinuz")

    def test_casper_requires_payload_and_selects_layer(self):
        base = {"/casper/vmlinuz", "/casper/initrd.xz"}
        self.assertIsNone(detect_profile(base | {"/casper/filesystem.manifest", "/casper/filesystem.size"}))
        layers = {"/casper/minimal.squashfs", "/casper/minimal.standard.squashfs", "/casper/minimal.standard.live.squashfs"}
        self.assertIsNone(detect_profile(base | {"/casper/minimal.standard.live.squashfs"}))
        match = detect_profile(base | layers)
        self.assertIn("layerfs-path=minimal.standard.live.squashfs", match.boot_args)
        self.assertIsNone(detect_profile(base | {"/casper/a.live.squashfs", "/casper/b.live.squashfs"}))

    def test_known_32bit_kernel_rejected(self):
        facts = self.grml()
        self.assertIsNone(detect_profile(ISOInspection(facts.paths, facts.volume_id, facts.text_files,
                                                     {"/boot/grmlsmallamd64/vmlinuz": "x86"})))

    def test_backends_preserve_metadata_and_kernel_architecture(self):
        header = bytearray(0x238)
        header[0x202:0x206] = b"HdrS"
        header[0x206:0x208] = (0x20C).to_bytes(2, "little")
        header[0x236:0x238] = (1).to_bytes(2, "little")
        files = {name: bytes(header) if name.endswith("vmlinuz") else b"fixture" for name in self.grml().paths}
        files["/conf/bootid.txt"] = b"grmlsmallamd64202609\n"
        files["/name with spaces"] = b"text"
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "name with spaces.iso"
            tiny_iso(path, files, "GRML_TEST")
            for backend in (None, "xorriso", "isoinfo"):
                listing = "\n".join(repr(name) if backend == "xorriso" else name for name in files)
                with patch("flexboot.iso.shutil.which", side_effect=lambda name: name if name == backend else None), \
                     patch("flexboot.process.Runner.run", return_value=subprocess.CompletedProcess([], 0, listing, "")):
                    facts, match = inspect_iso(path)
                self.assertEqual(match.profile, "grml-live")
                self.assertEqual(facts.volume_id, "GRML_TEST")
                self.assertIn("/name with spaces", facts.paths)
                self.assertEqual(facts.kernel_architectures["/boot/grmlsmallamd64/vmlinuz"], "x86_64")
            with ISO9660Reader(path) as image:
                with self.assertRaises(FlexBootError):
                    image.read_prefix(Entry("/bad", 9999, 2, False), 1)

    def test_external_listing_does_not_hide_invalid_metadata_extent(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "bad.iso"
            tiny_iso(path, {"/.disk/info": b"marker"})
            with patch("flexboot.iso.shutil.which", side_effect=lambda name: name if name == "xorriso" else None), \
                 patch("flexboot.process.Runner.run", return_value=subprocess.CompletedProcess([], 0, "'/.disk/info'", "")), \
                 patch.object(ISO9660Reader, "read", side_effect=FlexBootError("ISO file extent is outside the image")):
                with self.assertRaises(FlexBootError):
                    inspect_iso(path)

    def test_source_inspection_cli_and_profiles(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["profiles", "--json"]), 0)
        self.assertIn("grml-live", output.getvalue())
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "unsupported.iso"
            tiny_iso(source, {"/hello": b"world"})
            before = source.read_bytes()
            with patch("flexboot.iso.shutil.which", return_value=None), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["iso", "inspect", str(source), "--json"]), 2)
            self.assertIsNone(json.loads(output.getvalue())["profile"])
            self.assertEqual(source.read_bytes(), before)


class BootAliasTests(unittest.TestCase):
    def media(self, root):
        paths = MediaPaths(root / "efi", root / "data")
        paths.iso_dir.mkdir(parents=True)
        paths.grub_dir.mkdir(parents=True)
        Manifest(data_filesystem_uuid="abcd-1234").save(paths.manifest)
        (paths.grub_dir / "generated.cfg").write_text("# original menu\n")
        return paths

    def match(self):
        return detect_profile({"/live/vmlinuz", "/live/initrd.img", "/live/filesystem.squashfs"})

    def test_add_and_remove_keep_original_name_and_manage_alias(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=self.match()):
            root = Path(raw)
            paths = self.media(root)
            source = root / "Kali's Live image.iso"
            source.write_bytes(b"intact ISO")
            record = add_iso(paths, source)
            link = alias_path(paths.data, record.filename)
            self.assertEqual(link.read_bytes(), source.read_bytes())
            self.assertEqual((paths.iso_dir / source.name).read_bytes(), source.read_bytes())
            self.assertEqual(alias_problems(paths.data, [source.name]), [])
            self.assertIn(iso_boot_path(source.name), (paths.grub_dir / "generated.cfg").read_text())
            link.unlink()
            self.assertIn(f"Boot alias is missing or incorrect: {source.name}", verify(paths, full_hash=False))
            ensure_aliases(paths.data, [source.name])
            remove_iso(paths, source.name)
            self.assertFalse(link.is_symlink())
            self.assertFalse((paths.iso_dir / source.name).exists())

    def test_alias_conflict_rolls_back_add_without_touching_conflict(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=self.match()):
            root = Path(raw)
            paths = self.media(root)
            source = root / "name with spaces.iso"
            source.write_bytes(b"ISO")
            link = alias_path(paths.data, source.name)
            link.parent.mkdir()
            link.symlink_to("../../victim")
            before = paths.manifest.read_bytes()
            with self.assertRaisesRegex(FlexBootError, "Conflicting boot alias"):
                add_iso(paths, source)
            self.assertEqual(paths.manifest.read_bytes(), before)
            self.assertEqual(str(link.readlink()), "../../victim")
            self.assertFalse((paths.iso_dir / source.name).exists())

    def test_alias_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = self.media(root)
            outside = root / "outside"
            outside.mkdir()
            (paths.data / ".flexboot/boot-isos").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(FlexBootError):
                ensure_aliases(paths.data, ["spaces here.iso"])
            self.assertEqual(list(outside.iterdir()), [])

    def test_failed_menu_publication_removes_new_alias(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = self.media(Path(raw))
            record = ISORecord.from_match("spaces here.iso", 1, "a" * 64, self.match())
            import os
            original_replace = os.replace
            def replace(source, destination):
                if Path(destination) == paths.grub_dir / "generated.cfg":
                    raise OSError("publication failed")
                return original_replace(source, destination)
            with patch("flexboot.media.os.replace", side_effect=replace), self.assertRaises(OSError):
                regenerate(paths, Manifest(data_filesystem_uuid="abcd-1234", isos=[record]))
            self.assertFalse(alias_path(paths.data, record.filename).is_symlink())
            self.assertEqual((paths.grub_dir / "generated.cfg").read_text(), "# original menu\n")

    def test_sync_late_failure_rolls_back_new_alias_and_menu(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=self.match()):
            paths = self.media(Path(raw))
            name = "spaces here.iso"
            (paths.iso_dir / name).write_bytes(b"ISO")
            with patch.object(Manifest, "save", side_effect=FlexBootError("late failure")), self.assertRaises(FlexBootError):
                sync(paths)
            self.assertFalse(alias_path(paths.data, name).is_symlink())
            self.assertEqual((paths.grub_dir / "generated.cfg").read_text(), "# original menu\n")
