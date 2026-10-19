"""Boot-time discovery checks; optional real GRUB test uses only regular files."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import unittest

from flexboot.discovery import discovery_config
from flexboot.doctor import find_ovmf
from flexboot.grub import base_config, generated_config, validate_config
from flexboot.manifest import ISORecord


class DiscoveryTests(unittest.TestCase):
    def test_managed_names_are_literals_and_configuration_parses(self):
        records = [ISORecord(name, 1, 'a' * 64, 'debian-live', '/live/vmlinuz', '/live/initrd.img')
                   for name in ["a'$(reboot);[x].iso", 'with spaces.iso']]
        config = generated_config(records)
        self.assertIn('function flexboot_managed', config)
        self.assertNotIn('regexp', config)
        self.assertEqual(config.count('menuentry '), 2)
        with tempfile.TemporaryDirectory() as raw:
            p = Path(raw) / 'grub.cfg'
            p.write_text(base_config('1234-abcd') + config)
            validate_config(p)

    def test_empty_windows_collection_still_exposes_drop_filesystem(self):
        config = generated_config([], {'uuid': 'ABCDEF0123456789', 'images': []})
        self.assertIn("set flexboot_drop_uuid='ABCDEF0123456789'", config)
        self.assertNotIn('menuentry ', config)
        with tempfile.TemporaryDirectory() as raw:
            p = Path(raw) / 'generated.cfg'
            for windows in (None, {'uuid': 'ABCDEF0123456789', 'images': []}):
                p.write_text(generated_config([], windows))
                validate_config(p)

    def test_failed_data_search_cannot_reuse_an_old_device(self):
        config = base_config('1234-abcd')
        self.assertLess(config.index('set flexboot_data=\n'), config.index('--set=flexboot_data'))
        self.assertLess(config.index('source ($root)/boot/grub/generated.cfg'), config.index('function flexboot_scan'))
        self.assertNotIn('save_env', config)
        self.assertNotIn('configfile (fbscan)', config)


@unittest.skipUnless(os.environ.get('FLEXBOOT_RUN_GRUB_TESTS') == '1',
                     'set FLEXBOOT_RUN_GRUB_TESTS=1 for file-only QEMU discovery tests')
class DiscoveryGrubTests(unittest.TestCase):
    def test_actual_grub_detection_rejection_and_managed_deduplication(self):
        qemu = os.environ.get('FLEXBOOT_QEMU', 'qemu-system-x86_64')
        firmware = Path(os.environ.get('FLEXBOOT_OVMF') or find_ovmf() or '')
        variables = firmware.with_name(firmware.name.replace('CODE', 'VARS')) if firmware.name else firmware
        if not shutil.which(qemu) or not firmware.is_file() or not variables.is_file():
            self.skipTest('QEMU and matching OVMF CODE/VARS required')
        mkiso = os.environ.get('FLEXBOOT_MKISO', 'genisoimage')
        for tool in ['grub-mkstandalone', 'mkfs.ext4', mkiso]:
            if not shutil.which(tool): self.skipTest(f'{tool} required')
        with tempfile.TemporaryDirectory(prefix='flexboot-discovery-test-') as raw:
            work = Path(raw)
            tree = work / 'tree'; (tree / 'iso').mkdir(parents=True)
            kernel = bytearray(1024)
            kernel[:2] = b'MZ'
            struct.pack_into('<I', kernel, 0x3c, 0x80)
            kernel[0x80:0x84] = b'PE\0\0'
            struct.pack_into('<H', kernel, 0x84, 0x8664)
            struct.pack_into('<H', kernel, 0x98, 0x20b)
            struct.pack_into('<H', kernel, 0xdc, 10)
            struct.pack_into('<H', kernel, 0x1fe, 0xaa55)
            kernel[0x202:0x206] = b'HdrS'
            struct.pack_into('<H', kernel, 0x206, 0x20c)
            struct.pack_into('<H', kernel, 0x236, 1)
            debian = {'/live/vmlinuz': bytes(kernel), '/live/initrd.img': b'i', '/live/filesystem.squashfs': b'r'}
            casper = {'/casper/vmlinuz': bytes(kernel), '/casper/initrd': b'i', '/casper/filesystem.squashfs': b'r'}
            k32 = bytearray(kernel); struct.pack_into('<H', k32, 0x84, 0x14c)
            fixtures = {
                'live.iso': debian, 'upper.IsO': debian, 'managed.iso': debian,
                'with spaces.iso': debian, "quote'evil.iso": debian,
                'notkernel.iso': {**debian, '/live/vmlinuz': b'bad'},
                '32bit.iso': {**debian, '/live/vmlinuz': bytes(k32)},
                'missing-root.iso': {'/live/vmlinuz': bytes(kernel), '/live/initrd.img': b'i'},
                'windows.iso': {'/sources/boot.wim': b'w'},
                'classic.iso': casper,
                'server.iso': {'/casper/vmlinuz': bytes(kernel), '/casper/initrd': b'i',
                               '/casper/install-sources.yaml': b'y', '/casper/ubuntu-server-minimal.squashfs': b'r'},
                'clonezilla.iso': {**debian, '/Clonezilla-Live-Version': b'1'},
                'gparted.iso': {**debian, '/GParted-Live-Version': b'1'},
                'layered.iso': {'/casper/vmlinuz': bytes(kernel), '/casper/initrd': b'i', '/casper/ubuntu.live.squashfs': b'r'},
            }
            def make_iso(path, files, label='TEST'):
                source = work / 'fixture'
                if source.exists(): shutil.rmtree(source)
                source.mkdir()
                for name, content in files.items():
                    target = source / name.lstrip('/')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                subprocess.run([mkiso, '-quiet', '-R', '-J', '-V', label, '-o', str(path), str(source)], check=True, capture_output=True)
            for name, files in fixtures.items(): make_iso(tree / 'iso' / name, files)
            make_iso(tree / 'iso/parrot.iso', debian, label='Parrot TEST')
            (tree / 'iso/broken.iso').write_bytes(b'invalid')
            (tree / 'iso/nested').mkdir()
            make_iso(tree / 'iso/nested/nested.iso', debian)
            identity = '47ab4ee9-ced8-4a70-af6b-3f9ce4e0dd34'
            generated = generated_config([ISORecord('managed.iso', 1, 'a' * 64, 'debian-live', '/live/vmlinuz', '/live/initrd.img')])
            config = 'serial --unit=0 --speed=115200\nterminal_output serial\n'
            config += 'set flexboot_data=\nsearch --fs-uuid --set=flexboot_data ' + identity + '\n'
            config += 'set flexboot_drop_uuid=\n' + generated
            # Observe entries without altering detection, arguments or filesystem reads.
            config += discovery_config().replace('menuentry "[Linux] $fb_name [discovered]"',
                                                 'echo DISCOVERED:$fb_name\nmenuentry "[Linux] $fb_name [discovered]"')
            config += '\necho DISCOVERY_DONE\nset timeout=-1\n'
            cfg = work / 'grub.cfg'; cfg.write_text(config); validate_config(cfg)
            loader = work / 'esp/EFI/BOOT/BOOTX64.EFI'; loader.parent.mkdir(parents=True)
            subprocess.run(['grub-mkstandalone', '-O', 'x86_64-efi', '--locales=', '--themes=', '-o', str(loader),
                            f'boot/grub/grub.cfg={cfg}'], check=True, capture_output=True)
            data = work / 'data.img'
            with data.open('wb') as f: f.truncate(64 * 1024**2)
            subprocess.run(['mkfs.ext4', '-q', '-F', '-U', identity, '-d', str(tree), str(data)], check=True)
            writable = work / 'vars.fd'; shutil.copyfile(variables, writable)
            serial = work / 'serial.log'; monitor = work / 'qmp.sock'
            command = [qemu, '-machine', 'q35,accel=tcg', '-m', '256', '-display', 'none', '-nic', 'none', '-no-reboot',
                       '-drive', f'if=pflash,format=raw,readonly=on,file={firmware}', '-drive', f'if=pflash,format=raw,file={writable}',
                       '-drive', f'file=fat:ro:{work}/esp,format=raw,if=ide,snapshot=on',
                       '-drive', f'file={data},format=raw,if=virtio,readonly=on', '-serial', f'file:{serial}',
                       '-monitor', 'none', '-qmp', f'unix:{monitor},server=on,wait=off']
            if os.environ.get('FLEXBOOT_QEMU_DATA'): command += ['-L', os.environ['FLEXBOOT_QEMU_DATA']]
            with (work / 'qemu.log').open('w') as log:
                proc = subprocess.Popen(command, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 60
                    while proc.poll() is None and time.monotonic() < deadline:
                        text = serial.read_text(errors='replace') if serial.exists() else ''
                        if 'DISCOVERY_DONE' in text: break
                        time.sleep(.2)
                    else: self.fail('GRUB discovery did not finish: ' + (serial.read_text(errors='replace') if serial.exists() else 'no serial output'))
                    self.assertNotIn('syntax error', text)
                    found = {line.split('DISCOVERED:', 1)[1].strip() for line in text.splitlines() if 'DISCOVERED:' in line}
                    self.assertEqual(found, {'live.iso', 'upper.IsO', 'classic.iso', 'server.iso', 'clonezilla.iso', 'gparted.iso'})
                finally:
                    proc.terminate()
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
