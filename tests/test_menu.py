import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.cli import main, parser
from flexboot.errors import FlexBootError
from flexboot.grub import generated_config, grub_quote
from flexboot.manifest import ISORecord, Manifest
from flexboot.media import MediaPaths, regenerate, sync
from flexboot.menu import configure, entries, listing, load_settings, resolve, settings_path


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.paths = MediaPaths(root / 'efi', root / 'data')
        self.paths.iso_dir.mkdir(parents=True)
        self.records = [ISORecord(name, 1, 'a' * 64, 'debian-live', '/live/vmlinuz', '/live/initrd')
                        for name in ('z.iso', 'a.iso')]
        self.manifest = Manifest(data_filesystem_uuid='1234-abcd', isos=self.records)
        self.manifest.save(self.paths.manifest)
        regenerate(self.paths, self.manifest)
        self.windows = {'uuid': '1234567890ABCDEF', 'efi_uuid': 'ABCD-1234',
                        'images': [{'filename': 'w.iso', 'id': 'b' * 64}]}

    def test_mixed_order_labels_and_tags(self):
        settings = {'schema_version': 1, 'labels': {'Linux:z.iso': "My Linux's tools", 'Windows:w.iso': 'Install Windows'},
                    'order': ['Windows:w.iso', 'Linux:z.iso']}
        output = generated_config(self.records, self.windows, settings)
        self.assertLess(output.index('[Windows] Install Windows'), output.index('[Linux] My Linux'))
        self.assertLess(output.index('[Linux] My Linux'), output.index('[Linux] a.iso'))
        self.assertIn(grub_quote("[Linux] My Linux's tools"), output)
        self.assertIn('wim=/windows/' + 'b' * 64 + '/boot.wim', output)
        self.assertEqual(output.count('menuentry '), 3)
        self.assertEqual(output, generated_config(list(reversed(self.records)), self.windows, settings))

    def test_ambiguous_filename_requires_os_identifier(self):
        windows = {**self.windows, 'images': [{'filename': 'a.iso', 'id': 'c' * 64}]}
        items = entries(self.records, windows)
        with self.assertRaises(FlexBootError):
            resolve('a.iso', items)
        self.assertEqual(resolve('Windows:a.iso', items), 'Windows:a.iso')

    def test_persistent_labels_order_and_reset(self):
        original = self.paths.manifest.read_bytes()
        configure(self.paths, 'label', entry='z.iso', label='Recovery')
        configure(self.paths, 'order', order=['z.iso'])
        self.assertEqual([i['filename'] for i in listing(self.paths)], ['z.iso', 'a.iso'])
        regenerate(self.paths, Manifest.load(self.paths.manifest))
        self.assertIn('[Linux] Recovery', (self.paths.grub_dir / 'generated.cfg').read_text())
        self.assertEqual(original, self.paths.manifest.read_bytes())
        configure(self.paths, 'label', entry='z.iso')
        self.assertIn('[Linux] z.iso', (self.paths.grub_dir / 'generated.cfg').read_text())
        configure(self.paths, 'reset')
        self.assertEqual(load_settings(self.paths)['order'], [])
        self.assertEqual(listing(self.paths)[0]['filename'], 'a.iso')

    def test_added_and_readded_entries_keep_preferences(self):
        configure(self.paths, 'order', order=['z.iso'])
        configure(self.paths, 'label', entry='z.iso', label='Tools')
        record = ISORecord('b.iso', 1, 'b' * 64, 'debian-live', '/live/vmlinuz', '/live/initrd')
        self.assertEqual([i['filename'] for i in entries([*self.records, record], settings=load_settings(self.paths))], ['z.iso', 'a.iso', 'b.iso'])
        self.assertEqual(entries(self.records, settings=load_settings(self.paths))[0]['label'], 'Tools')

    def test_invalid_settings_and_inputs_fail_without_changes(self):
        original = (self.paths.grub_dir / 'generated.cfg').read_bytes()
        for label in ('', ' ', 'bad\nname', 'bad\x7fname', 'x' * 161):
            with self.assertRaises(FlexBootError):
                configure(self.paths, 'label', entry='a.iso', label=label)
        for order in (['missing.iso'], ['a.iso', 'Linux:a.iso']):
            with self.assertRaises(FlexBootError):
                configure(self.paths, 'order', order=order)
        self.assertEqual(original, (self.paths.grub_dir / 'generated.cfg').read_bytes())
        self.assertFalse(settings_path(self.paths).exists())
        settings_path(self.paths).write_text('{bad')
        with self.assertRaises(FlexBootError):
            load_settings(self.paths)

    def test_validation_failure_rolls_back_preferences_and_menu(self):
        configure(self.paths, 'label', entry='a.iso', label='Before')
        files = [settings_path(self.paths), self.paths.grub_dir / 'generated.cfg', self.paths.grub_dir / 'grub.cfg']
        originals = [p.read_bytes() for p in files]
        with patch('flexboot.media.validate_config', side_effect=FlexBootError('bad GRUB')):
            with self.assertRaises(FlexBootError):
                configure(self.paths, 'label', entry='a.iso', label='After')
        self.assertEqual(originals, [p.read_bytes() for p in files])
        self.assertFalse(list(self.paths.grub_dir.glob('*.new')))

    def test_symlink_settings_rejected(self):
        outside = Path(self.temp.name) / 'outside.json'
        outside.write_text('{}')
        settings_path(self.paths).symlink_to(outside)
        with self.assertRaises(FlexBootError):
            load_settings(self.paths)
        self.assertEqual(outside.read_text(), '{}')

    def test_cli_dry_run_does_not_open_target(self):
        with patch('flexboot.cli._media_target') as mount:
            self.assertEqual(main(['menu', 'label', '/dev/missing', 'a.iso', 'Tools', '--dry-run']), 0)
            self.assertEqual(main(['menu', 'order', '/dev/missing', 'a.iso', '--dry-run', '--json']), 0)
        mount.assert_not_called()
        args = parser().parse_args(['menu', 'list', 'image.img', '--json'])
        self.assertEqual(args.menu_command, 'list')


if __name__ == '__main__':
    unittest.main()
