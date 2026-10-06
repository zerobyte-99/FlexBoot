import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flexboot.builder import build_attached, open_media
from flexboot.cli import main
from flexboot.devices import Device, discover
from flexboot.disk import discover_partitions
from flexboot.doctor import diagnose
from flexboot.errors import DependencyError, FlexBootError, MediaStateError, SafetyError
from flexboot.grub import atomic_text, base_config, generated_config
from flexboot.installer import dependency_plan, install_application, setup_report
from flexboot.manifest import ISORecord, Manifest, copy_and_hash, sha256_file
from flexboot.media import MediaPaths, add_iso_result, batch_add, deploy_theme, sync, verify
from flexboot.mounts import mounted
from flexboot.process import Runner
from flexboot.profiles.debian_live import DebianLiveProfile
from flexboot.profiles.base import ISOInspection
from flexboot.safety import protected_device_names


MATCH = DebianLiveProfile().detect(ISOInspection(frozenset({
    "/live/vmlinuz", "/live/initrd.img", "/live/filesystem.squashfs"})))


def media(root):
    paths = MediaPaths(root / "efi", root / "data")
    paths.iso_dir.mkdir(parents=True)
    paths.grub_dir.mkdir(parents=True)
    Manifest(data_filesystem_uuid="1234-abcd").save(paths.manifest)
    (paths.grub_dir / "generated.cfg").write_text(generated_config([]))
    return paths


class SafetyRegressionTests(unittest.TestCase):
    def test_existing_image_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            original = root / "existing.img"
            original.write_bytes(b"preserve")
            link = root / "link.img"
            link.symlink_to(original)
            for path in (original, link):
                with patch("flexboot.cli.require_root"), patch("flexboot.cli.preflight"), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(["image", "create", str(path), "--size", "2G"]), 2)
                self.assertEqual(original.read_bytes(), b"preserve")
                self.assertTrue(link.is_symlink())

    def test_missing_dependency_prevents_destructive_commands(self):
        with patch("flexboot.builder.require_root"), patch("flexboot.builder.preflight", side_effect=DependencyError("missing")), patch("flexboot.builder.partition_device") as partition:
            with self.assertRaises(DependencyError):
                build_attached(Path("/dev/loop99"), Runner())
            partition.assert_not_called()

    def test_failed_unmount_preserves_contents(self):
        with tempfile.TemporaryDirectory() as raw:
            point = Path(raw) / "owned"
            point.mkdir()
            sentinel = point / "keep"
            sentinel.write_text("data")
            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 1 if argv[0] == "umount" else 0, "", "")
            with patch("flexboot.mounts.tempfile.mkdtemp", return_value=str(point)), patch("flexboot.mounts.os.path.ismount", return_value=True), patch("flexboot.mounts.os.sync"), patch.object(Runner, "run", side_effect=run):
                with self.assertRaises(FlexBootError):
                    with mounted(Path("/dev/loop99")):
                        self.assertTrue(sentinel.exists())
            self.assertEqual(sentinel.read_text(), "data")

    def test_shared_ancestry_protects_both_disks_and_handles_cycles(self):
        logical = Device("dm-test", Path("/dev/dm-test"), "lvm", 1)
        disks = [Device(name, Path("/dev") / name, "disk", 2, children=(logical,)) for name in ("sdfake", "sdother")]
        self.assertEqual(protected_device_names(disks, ["/dev/dm-test[/subvolume]"]), {"dm-test", "sdfake", "sdother"})
        cycle = [Device("a", Path("/dev/a"), "part", 1, parent_name="b"), Device("b", Path("/dev/b"), "part", 1, parent_name="a")]
        self.assertEqual(protected_device_names(cycle, ["/dev/a"]), {"a", "b"})

    def test_partition_numbers_and_roles_not_names(self):
        efi = Device("odd10", Path("/dev/odd10"), "part", 1, partition_number=1, partition_type="c12a7328-f81f-11d2-ba4b-00a0c93ec93b")
        data = Device("odd2", Path("/dev/odd2"), "part", 1, partition_number=2, partition_type="0fc63daf-8483-4772-8e79-3d69d8477de4")
        root = Device("odd", Path("/dev/odd"), "disk", 2, pttype="gpt", children=(data, efi))
        with patch("flexboot.disk.discover", return_value=[root]):
            self.assertEqual(discover_partitions(root.path, Runner()), (efi.path, data.path))
        root = Device("odd", root.path, "disk", 10, children=tuple(Device(str(i), Path(f"/dev/odd{i}"), "part", 1) for i in range(10)))
        with patch("flexboot.disk.discover", return_value=[root]), self.assertRaises(FlexBootError):
            discover_partitions(root.path, Runner())

    def test_transport_column_fallback_stays_unknown_without_evidence(self):
        text = json.dumps({"blockdevices": [{"name": "fake", "path": "/dev/fake", "type": "disk", "size": 1}]})
        results = [subprocess.CompletedProcess([], 1, "", "lsblk: unknown column: TRAN"), subprocess.CompletedProcess([], 0, text, "")]
        with patch.object(Runner, "run", side_effect=results), patch("flexboot.devices.transport_fallback", return_value=""):
            self.assertEqual(discover()[0].transport, "")

    def test_atomic_text_does_not_follow_predictable_temp_symlink(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            victim = root / "victim"
            victim.write_text("preserve")
            (root / "config.tmp").symlink_to(victim)
            atomic_text(root / "config", "new")
            self.assertEqual(victim.read_text(), "preserve")


class MediaImprovementTests(unittest.TestCase):
    def test_batch_cli_json_is_a_single_structured_result(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            @contextlib.contextmanager
            def opened(*args, **kwargs):
                yield paths
            with patch("flexboot.cli.open_media", opened), patch("flexboot.cli.require_root"), patch("flexboot.cli.preflight"), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["add", "/dev/fake", str(source), str(source), "--json"]), 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["summary"]["added"], 1)
            self.assertEqual(report["summary"]["skipped"], 1)

    def test_same_content_skips_but_changed_content_requires_replace(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            self.assertEqual(add_iso_result(paths, source).status, "added")
            self.assertEqual(add_iso_result(paths, source).status, "skipped")
            source.write_bytes(b"other")
            with self.assertRaisesRegex(FlexBootError, "--replace"):
                add_iso_result(paths, source)
            self.assertEqual(add_iso_result(paths, source, replace=True).status, "replaced")
            self.assertEqual((paths.iso_dir / source.name).read_bytes(), b"other")

    def test_corrupt_duplicate_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            (paths.iso_dir / source.name).write_bytes(b"wrong")
            with self.assertRaises(MediaStateError):
                add_iso_result(paths, source)

    def test_replacement_menu_failure_restores_all_old_state(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            original = paths.manifest.read_bytes()
            menu = (paths.grub_dir / "generated.cfg").read_bytes()
            source.write_bytes(b"second")
            with patch("flexboot.media.validate_config", side_effect=FlexBootError("bad menu")), self.assertRaises(FlexBootError):
                add_iso_result(paths, source, replace=True)
            self.assertEqual((paths.iso_dir / source.name).read_bytes(), b"first")
            self.assertEqual(paths.manifest.read_bytes(), original)
            self.assertEqual((paths.grub_dir / "generated.cfg").read_bytes(), menu)
            self.assertFalse(list(paths.iso_dir.glob(".*")))

    def test_space_failure_happens_before_copy(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            with patch("flexboot.media.os.statvfs", return_value=SimpleNamespace(f_bavail=0, f_frsize=4096)), patch("flexboot.media.copy_and_hash") as copy:
                with self.assertRaisesRegex(MediaStateError, "Not enough free space"):
                    add_iso_result(paths, source)
                copy.assert_not_called()
            self.assertEqual(Manifest.load(paths.manifest).isos, [])

    def test_batch_continues_only_for_independent_errors(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = media(root)
            sources = [root / f"{name}.iso" for name in ("one", "bad", "three")]
            for source in sources:
                source.write_bytes(b"iso")
            def inspect(path, runner):
                if path.name == "bad.iso":
                    raise FlexBootError("unsupported source")
                return MATCH
            with patch("flexboot.media.require_supported", side_effect=inspect):
                outcomes = batch_add(paths, sources, Runner(), continue_on_error=True)
            self.assertEqual([item["status"] for item in outcomes], ["added", "failed", "added"])
            with patch("flexboot.media.add_iso_result", side_effect=MediaStateError("disk full")):
                outcomes = batch_add(paths, sources, Runner(), continue_on_error=True)
            self.assertEqual([item["status"] for item in outcomes], ["failed", "not-attempted", "not-attempted"])

    def test_sync_rejects_same_size_corruption(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            original = paths.manifest.read_bytes()
            (paths.iso_dir / source.name).write_bytes(b"wrong")
            with self.assertRaisesRegex(MediaStateError, "integrity mismatch"):
                sync(paths)
            self.assertEqual(paths.manifest.read_bytes(), original)

    def test_quick_verify_does_not_claim_content_integrity(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            (paths.grub_dir / "grub.cfg").write_text(base_config("1234-abcd"))
            loader = paths.efi / "EFI/BOOT/BOOTX64.EFI"
            loader.parent.mkdir(parents=True)
            loader.write_bytes(b"fixture")
            deploy_theme(paths.efi)
            (paths.iso_dir / source.name).write_bytes(b"wrong")
            self.assertEqual(verify(paths, full_hash=False), [])
            self.assertTrue(any("hash mismatch" in problem for problem in verify(paths)))

    def test_manifest_rejects_path_traversal_and_boot_injection(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = media(Path(raw))
            record = ISORecord("safe.iso", 1, "a" * 64, "debian-live", "/live/vmlinuz", "/live/initrd")
            manifest = Manifest(data_filesystem_uuid="1234-abcd", isos=[record])
            manifest.save(paths.manifest)
            valid = json.loads(paths.manifest.read_text())
            for field, value in (("filename", "../escape.iso"), ("kernel", "/live/vmlinuz;reboot"), ("boot_args", "boot=live\nreboot")):
                changed = json.loads(json.dumps(valid))
                changed["isos"][0][field] = value
                paths.manifest.write_text(json.dumps(changed))
                with self.assertRaises(FlexBootError):
                    Manifest.load(paths.manifest)

    def test_full_verify_reconciles_detected_boot_plan(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.iso"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            manifest = Manifest.load(paths.manifest)
            from dataclasses import replace
            manifest.isos = [replace(manifest.isos[0], boot_args="boot=live components findiso=${iso_path} toram")]
            manifest.save(paths.manifest)
            self.assertTrue(any("profile differs" in problem for problem in verify(paths)))

    def test_copy_detects_source_growth_and_preserves_unrelated_partial(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.iso"
            source.write_bytes(b"first")
            stale = root / ".target.iso.partial"
            stale.write_bytes(b"preserve")
            changed = False
            def progress(copied, total):
                nonlocal changed
                if not changed:
                    with source.open("ab") as handle:
                        handle.write(b"more")
                    changed = True
            with self.assertRaises(FlexBootError):
                copy_and_hash(source, root / "target.iso", progress)
            self.assertEqual(stale.read_bytes(), b"preserve")
            self.assertFalse((root / "target.iso").exists())


class InstallationTests(unittest.TestCase):
    def test_permissive_umask_does_not_expose_writable_installation(self):
        with tempfile.TemporaryDirectory() as raw:
            prefix = Path(raw) / "prefix"
            old_umask = os.umask(0)
            try:
                launcher = install_application(prefix)
            finally:
                os.umask(old_umask)
            for path in (prefix, prefix / "bin", prefix / "lib", prefix / "lib/flexboot", prefix / "lib/flexboot/releases", launcher):
                self.assertEqual(path.stat().st_mode & 0o022, 0, str(path))
            release = next((prefix / "lib/flexboot/releases").iterdir())
            self.assertEqual(release.stat().st_mode & 0o777, 0o755)

    def test_setup_detects_missing_venv_for_system_install(self):
        with patch("flexboot.installer.importlib.util.find_spec", return_value=None):
            report = setup_report("media", system=True)
        self.assertFalse(report["ready"])
        self.assertEqual(report["required"]["venv"]["package"], "python3-venv")

    def test_failed_package_postcheck_never_publishes_launcher(self):
        before = diagnose("create")
        before["required"]["mkfs.fat"]["found"] = False
        before["capabilities"]["create"] = {"ready": False, "missing": ["mkfs.fat"]}
        before["ready"] = False
        with patch("flexboot.installer.setup_report", return_value=before), patch("flexboot.builder.require_root"), patch("flexboot.installer.validate_system_prefix"), patch("flexboot.installer.distribution", return_value={"ID": "ubuntu"}), patch("flexboot.installer.shutil.which", return_value="/usr/bin/apt-get"), patch.object(Runner, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run, patch("flexboot.installer.install_application") as install, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["install", "--dependencies", "--system", "--yes"]), 2)
            install.assert_not_called()
            self.assertEqual(run.call_args[0][0][:2], ["apt-get", "install"])

    def test_media_readiness_does_not_require_efi_install_modules(self):
        with patch("flexboot.doctor.shutil.which", side_effect=lambda command: None if command == "grub-install" else f"/usr/bin/{command}"), patch("flexboot.doctor.grub_target_available", return_value=False):
            report = diagnose("media")
        self.assertTrue(report["ready"])
        self.assertFalse(report["capabilities"]["create"]["ready"])

    def test_dependency_plan_is_explicit_and_distribution_scoped(self):
        with patch("flexboot.doctor.grub_target_available", return_value=False):
            report = diagnose("create")
        with patch("flexboot.installer.distribution", return_value={"ID": "kali"}), patch("flexboot.installer.shutil.which", return_value="/usr/bin/apt-get"):
            command = dependency_plan(report, yes=True)
        self.assertIn("grub-efi-amd64-bin", command)
        self.assertIn("--no-remove", command)
        with patch("flexboot.installer.distribution", return_value={"ID": "fedora"}):
            with self.assertRaises(FlexBootError):
                dependency_plan(report)

    def test_install_dry_run_does_not_create_prefix_or_run_packages(self):
        with tempfile.TemporaryDirectory() as raw:
            prefix = Path(raw) / "prefix"
            with patch("flexboot.installer.install_application") as install, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["install", "--system", "--dependencies", "--prefix", str(prefix), "--dry-run", "--json"]), 0)
                install.assert_not_called()
            self.assertFalse(prefix.exists())
            self.assertTrue(json.loads(output.getvalue())["dry_run"])

    def test_real_offline_install_works_outside_checkout_with_assets(self):
        with tempfile.TemporaryDirectory() as raw:
            prefix = Path(raw) / "installation with spaces"
            launcher = install_application(prefix)
            env = {**os.environ, "PYTHONPATH": "/nonexistent", "PYTHONHOME": "/nonexistent"}
            result = subprocess.run([str(launcher), "theme", "--list", "--json"], check=True, text=True, capture_output=True, cwd="/tmp", env=env)
            self.assertEqual(len(json.loads(result.stdout)["backgrounds"]), 4)
            self.assertIn(" -I -m flexboot ", launcher.read_text())

    def test_unrelated_launcher_is_preserved(self):
        with tempfile.TemporaryDirectory() as raw:
            prefix = Path(raw)
            (prefix / "bin").mkdir()
            launcher = prefix / "bin/flexboot"
            for content in (b"another program", b"\x7fELF\xff\x00"):
                launcher.write_bytes(content)
                with self.assertRaises(FlexBootError):
                    install_application(prefix)
                self.assertEqual(launcher.read_bytes(), content)


class MountedMediaTests(unittest.TestCase):
    def test_readonly_mounts_can_be_reused_without_privilege(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = media(Path(raw))
            efi = Device("loop99p1", Path("/dev/loop99p1"), "part", 1, fstype="vfat", label="FLEXBOOTEFI", uuid="ABCD-1234", mountpoints=(str(paths.efi),))
            data = Device("loop99p2", Path("/dev/loop99p2"), "part", 1, fstype="ext4", label="FLEXBOOT", uuid="1234-abcd", mountpoints=(str(paths.data),))
            target = Device("loop99", Path("/dev/loop99"), "loop", 2, children=(efi, data))
            nodes = {node.path: node for node in (target, efi, data)}
            def run(argv, **kwargs):
                node = nodes[Path(argv[argv.index("--source") + 1])]
                return subprocess.CompletedProcess(argv, 0, json.dumps({"filesystems": [{"target": node.mountpoints[0], "options": "ro,nosuid,nodev"}]}), "")
            with patch("flexboot.builder.find_device", side_effect=lambda path, runner=None: nodes[path]), patch("flexboot.builder.discover", return_value=[target]), patch("flexboot.builder.system_mount_sources", return_value=[]), patch("flexboot.builder.discover_partitions", return_value=(efi.path, data.path)), patch("flexboot.builder.require_root", side_effect=AssertionError("must not request root")), patch.object(Runner, "run", side_effect=run):
                with open_media(target.path, Runner(), readonly=True) as opened:
                    self.assertEqual(opened, paths)
                with self.assertRaises(SafetyError):
                    with open_media(target.path, Runner()):
                        self.fail("must reject writable access to already mounted media")


class SyncTransactionTests(unittest.TestCase):
    def test_validation_failure_preserves_metadata_and_theme(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = media(Path(raw))
            deploy_theme(paths.efi)
            config = paths.grub_dir / "grub.cfg"
            config.write_text(base_config("1234-abcd"))
            before = paths.manifest.read_bytes(), config.read_bytes(), (paths.grub_dir / "generated.cfg").read_bytes()
            background = paths.grub_dir / "themes/flexboot/background.png"
            digest = sha256_file(background)
            with patch("flexboot.media.validate_config", side_effect=FlexBootError("invalid")), self.assertRaises(FlexBootError):
                sync(paths)
            self.assertEqual(before, (paths.manifest.read_bytes(), config.read_bytes(), (paths.grub_dir / "generated.cfg").read_bytes()))
            self.assertEqual(sha256_file(background), digest)
            self.assertFalse(list(paths.efi.glob(".flexboot-sync-*")))

    def test_manifest_publication_failure_restores_theme_and_configs(self):
        with tempfile.TemporaryDirectory() as raw:
            paths = media(Path(raw))
            deploy_theme(paths.efi)
            config = paths.grub_dir / "grub.cfg"
            config.write_text("old config")
            before = paths.manifest.read_bytes(), config.read_bytes()
            with patch.object(Manifest, "save", side_effect=OSError("disk failure")), self.assertRaises(OSError):
                sync(paths)
            self.assertEqual(before, (paths.manifest.read_bytes(), config.read_bytes()))
            self.assertTrue((paths.grub_dir / "themes/flexboot/background.png").is_file())

    def test_uppercase_iso_extension_is_reconciled(self):
        with tempfile.TemporaryDirectory() as raw, patch("flexboot.media.require_supported", return_value=MATCH):
            root = Path(raw)
            paths = media(root)
            source = root / "sample.ISO"
            source.write_bytes(b"first")
            add_iso_result(paths, source)
            manifest = sync(paths)
            self.assertEqual([record.filename for record in manifest.isos], ["sample.ISO"])
            loader = paths.efi / "EFI/BOOT/BOOTX64.EFI"
            loader.parent.mkdir(parents=True)
            loader.write_bytes(b"fixture")
            self.assertEqual(verify(paths), [])


class ISOReaderCleanupTests(unittest.TestCase):
    def test_invalid_descriptor_closes_its_file(self):
        from flexboot.iso9660 import ISO9660Reader
        handle = io.BytesIO(b"not an ISO")
        with patch.object(Path, "open", return_value=handle), self.assertRaises(FlexBootError):
            ISO9660Reader(Path("fixture.iso"))
        self.assertTrue(handle.closed)


class PublishedPermissionTests(unittest.TestCase):
    def test_iso_and_metadata_are_readable_after_private_staging(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.iso"
            source.write_bytes(b"fixture")
            destination = root / "copied.iso"
            copy_and_hash(source, destination)
            metadata = root / "metadata.json"
            atomic_text(metadata, "{}")
            self.assertEqual(destination.stat().st_mode & 0o777, 0o644)
            self.assertEqual(metadata.stat().st_mode & 0o777, 0o644)
