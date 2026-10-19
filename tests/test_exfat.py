import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flexboot.disk import partition_device, format_partitions, data_partition_type, BASIC_DATA_GUID, LINUX_DATA_GUID
from flexboot.errors import FlexBootError
from flexboot.doctor import diagnose
from flexboot.media import MediaPaths, add_iso_result, validate_data_profile


class ExfatSafetyTests(unittest.TestCase):
    def test_exfat_rejects_unvalidated_families_but_ext4_keeps_them(self):
        exfat = MediaPaths(Path('/efi'), Path('/data'), data_filesystem='exfat')
        ext4 = MediaPaths(Path('/efi'), Path('/data'))
        for profile in ('ubuntu-casper', 'ubuntu-server-casper', 'rescuezilla', 'archiso', 'fedora-live'):
            with self.assertRaisesRegex(FlexBootError, 'not enabled'):
                validate_data_profile(exfat, profile)
            validate_data_profile(ext4, profile)
        for profile in ('debian-live', 'clonezilla-live', 'gparted-live'):
            validate_data_profile(exfat, profile)

    def test_unknown_filesystem_is_rejected_before_any_command(self):
        runner = Mock()
        with self.assertRaises(FlexBootError):
            partition_device(Path('/dev/fixture'), runner, data_filesystem='unknown')
        runner.run.assert_not_called()
        with self.assertRaises(FlexBootError):
            format_partitions(Path('/dev/fixture1'), Path('/dev/fixture2'), runner, data_filesystem='unknown')
        runner.run.assert_not_called()
        self.assertEqual(data_partition_type('exfat'), BASIC_DATA_GUID)
        self.assertEqual(data_partition_type('ext4'), LINUX_DATA_GUID)

    def test_exfat_unsupported_name_is_rejected_before_inspection_or_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = MediaPaths(root / 'efi', root / 'data', data_filesystem='exfat')
            before = set(root.rglob('*'))
            with patch('flexboot.media.require_supported') as inspect:
                with self.assertRaisesRegex(FlexBootError, 'exFAT ISO names'):
                    add_iso_result(paths, root / 'with spaces.iso')
                inspect.assert_not_called()
            self.assertEqual(set(root.rglob('*')), before)

    def test_exfat_preflight_reports_missing_host_driver(self):
        with patch('flexboot.doctor.host_exfat_available', return_value=False):
            report = diagnose('create-exfat')
        self.assertFalse(report['ready'])
        self.assertIn('Host kernel exFAT filesystem driver', report['capabilities']['create-exfat']['missing'])
        self.assertNotIn('Host kernel exFAT filesystem driver', report['capabilities']['create']['missing'])
