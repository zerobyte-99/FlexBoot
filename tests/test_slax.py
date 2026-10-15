import unittest
from dataclasses import replace

from flexboot.grub import generated_config
from flexboot.manifest import ISORecord
from flexboot.profiles import detect_profile
from flexboot.profiles.base import ISOInspection


class SlaxTests(unittest.TestCase):
    def facts(self):
        return ISOInspection(frozenset({
            '/slax/boot/vmlinuz', '/slax/boot/initrfs.img',
            '/slax/boot/syslinux.cfg', '/slax/modules/01-core.sb',
        }), 'slax', {'/slax/boot/syslinux.cfg':
            'MENU LABEL Run Slax from RAM\nKERNEL /slax/boot/vmlinuz\nAPPEND initrd=/slax/boot/initrfs.img toram'})

    def test_exact_iso_and_no_persistence(self):
        match = detect_profile(self.facts())
        self.assertEqual(match.profile, 'slax-live')
        output = generated_config([ISORecord.from_match('Slax with spaces.iso', 1, 'a' * 64, match)])
        self.assertIn('from="${iso_path}"', output)
        self.assertIn('linux (loop)/slax/boot/vmlinuz', output)
        self.assertIn('initrd (loop)/slax/boot/initrfs.img', output)
        self.assertNotIn('perch', output)
        self.assertNotIn('automount', output)

    def test_require_complete_product_layout(self):
        facts = self.facts()
        for path in facts.paths:
            with self.subTest(path=path):
                self.assertIsNone(detect_profile(replace(facts, paths=facts.paths - {path})))
        self.assertIsNone(detect_profile(replace(facts, volume_id='unrelated')))
        self.assertIsNone(detect_profile(replace(facts, text_files={})))

    def test_known_32bit_kernel_is_excluded(self):
        self.assertIsNone(detect_profile(replace(self.facts(), kernel_architectures={'/slax/boot/vmlinuz': 'x86'})))


if __name__ == '__main__':
    unittest.main()
