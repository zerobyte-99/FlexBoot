import copy
from dataclasses import replace
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot import windows
from flexboot.errors import FlexBootError, MediaStateError, SafetyError
from flexboot.media import MediaPaths
from flexboot.process import Runner
from flexboot.disk import BASIC_DATA_GUID, discover_partitions, partition_device


class FakeRunner(Runner):
    def run(self, argv, **kwargs):
        self.planned.append(list(map(str, argv)))
        return subprocess.CompletedProcess(argv, 0, '', '')


def pe(path):
    contents=bytearray(512);contents[:2]=b'MZ';struct.pack_into('<I',contents,60,128)
    contents[128:134]=b'PE\0\0\x64\x86';path.write_bytes(contents)


class WindowsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.paths=MediaPaths(root/'efi',root/'data',root/'win','1234567890ABCDEF','ABCD-1234')
        for path in (self.paths.grub_dir/'windows',self.paths.data/'.flexboot',self.paths.windows/'windows',self.paths.windows/'.flexboot-windows'):
            path.mkdir(parents=True)
        self.token='a'*64
        self.state={'schema_version':1,'uuid':self.paths.windows_uuid,'efi_uuid':self.paths.efi_uuid,'token':self.token,
                    'ntloader_sha256':'','helper_sha256':'','images':[]}
        for name,key in [('ntloader','ntloader_sha256'),('flexboot-win.exe','helper_sha256')]:
            file=self.paths.grub_dir/'windows'/name;pe(file);self.state[key]=windows.sha256_file(file)
        (self.paths.windows/'.flexboot-windows'/f'{self.token}.marker').write_text(self.paths.windows_uuid+'\n')
        from flexboot.manifest import Manifest
        Manifest(data_filesystem_uuid="1234-abcd").save(self.paths.manifest)
        windows.publish(self.paths,self.state,FakeRunner())

    def test_clean_empty_windows_media(self):
        self.assertEqual(windows.verify(self.paths),[])

    def test_layout_opt_in_and_minimum_before_erase(self):
        class DiskRunner(FakeRunner):
            def run(self,argv,**kwargs):
                self.planned.append(list(map(str,argv)))
                value='512' if '--getss' in argv else str(12*1024**3)
                return subprocess.CompletedProcess(argv,0,value,'')
        runner=DiskRunner();partition_device(Path('/dev/fixture'),runner,windows_size=8*1024**3)
        self.assertTrue(any(call[0]=='sfdisk' for call in runner.planned))
        runner=DiskRunner()
        with self.assertRaises(FlexBootError):partition_device(Path('/dev/fixture'),runner,windows_size=11*1024**3)
        self.assertFalse(any(call[0]=='wipefs' for call in runner.planned))

    def test_basic_boot_role_requires_windows_before_any_command(self):
        runner = FakeRunner()
        with self.assertRaises(SafetyError):
            partition_device(Path('/dev/fixture'), runner, boot_partition_role='basic-fat')
        self.assertEqual(runner.planned, [])

    def test_default_and_explicit_windows_partition_roles(self):
        class LayoutRunner(FakeRunner):
            def run(self, argv, **kwargs):
                self.planned.append(list(map(str, argv)))
                if argv[0] == 'sfdisk':
                    self.layout = kwargs['input_text']
                value = '512' if '--getss' in argv else str(16 * 1024**3)
                return subprocess.CompletedProcess(argv, 0, value, '')
        default = LayoutRunner()
        partition_device(Path('/dev/fixture'), default)
        self.assertIn('type=U', default.layout)
        self.assertNotIn(BASIC_DATA_GUID, default.layout)
        optional = LayoutRunner()
        partition_device(Path('/dev/fixture'), optional, windows_size=8 * 1024**3,
                         boot_partition_role='basic-fat')
        self.assertEqual(optional.layout.count('type=' + BASIC_DATA_GUID), 2)
        self.assertNotIn('type=U', optional.layout)
        self.assertEqual(optional.layout.count('type='), 3)

    def test_basic_boot_discovery_requires_complete_windows_layout(self):
        from flexboot.devices import Device
        boot = Device('fixture1', Path('/dev/fixture1'), 'part', 1,
                      partition_number=1, partition_type=BASIC_DATA_GUID)
        data = Device('fixture2', Path('/dev/fixture2'), 'part', 1,
                      partition_number=2, partition_type='0fc63daf-8483-4772-8e79-3d69d8477de4')
        win = Device('fixture3', Path('/dev/fixture3'), 'part', 1,
                     partition_number=3, partition_type=BASIC_DATA_GUID)
        root = Device('fixture', Path('/dev/fixture'), 'loop', 3, pttype='gpt',
                      children=(boot, data, win))
        with patch('flexboot.disk.discover', return_value=[root]):
            self.assertEqual(discover_partitions(root.path, FakeRunner(), include_windows=True,
                                                boot_partition_role='basic-fat'), (boot.path, data.path, win.path))
            with self.assertRaises(SafetyError):
                discover_partitions(root.path, FakeRunner(), include_windows=True, boot_partition_role='esp')
        with patch('flexboot.disk.discover', return_value=[replace(root, children=(boot, data))]):
            with self.assertRaises(SafetyError):
                discover_partitions(root.path, FakeRunner(), include_windows=True)

    def test_windows_creation_requires_explicit_boot_layout(self):
        from flexboot.cli import parser, _windows_creation
        args = parser().parse_args(['image', 'create', 'fixture.img', '--size', '16G',
                                    '--windows-size', '8G', '--dry-run'])
        with self.assertRaisesRegex(FlexBootError, 'windows-boot-layout'):
            _windows_creation(args)

    def test_boot_layout_cannot_change_without_matching_metadata(self):
        paths = replace(self.paths, boot_partition_role='basic-fat')
        with self.assertRaisesRegex(MediaStateError, 'partition role'):
            windows.load(paths)
        self.state['boot_partition_role'] = 'basic-fat'
        windows.publish(paths, self.state, FakeRunner())
        self.assertEqual(windows.verify(paths), [])
        with self.assertRaisesRegex(MediaStateError, 'partition role'):
            windows.load(self.paths)

    def test_windows_builder_refuses_esp_before_any_disk_operation(self):
        from flexboot.builder import build_attached
        runner = FakeRunner()
        with self.assertRaisesRegex(SafetyError, 'Basic Data'):
            build_attached(Path('/dev/fixture'), runner, windows_size=8 * 1024**3)
        self.assertEqual(runner.planned, [])

    def test_archive_traversal_and_collisions(self):
        for value in ('../outside','/absolute','dir\\name','C:outside','Sources/a\nPath = sources/A'):
            with self.subTest(value=value),self.assertRaises(SafetyError):
                windows.archive_entries('----------\nPath = '+value+'\nSize = 1\n')

    def test_archive_case_collision(self):
        with self.assertRaises(SafetyError):
            windows.archive_entries('----------\nPath = Sources/A\nSize = 1\n\nPath = sources/a\nSize = 2\n')

    def test_udf_directories_have_empty_sizes(self):
        entries=windows.archive_entries('----------\nPath = boot\nFolder = +\nSize = \n\nPath = boot/boot.sdi\nFolder = -\nSize = 4096\n')
        self.assertEqual(entries['boot'][1],0)
        self.assertEqual(entries['boot/boot.sdi'][1],4096)

    def test_archive_malformed(self):
        with self.assertRaises(FlexBootError):windows.archive_entries('no delimiter')
        with self.assertRaises(FlexBootError):windows.archive_entries('----------\nPath = a\nSize = -1\n')

    def test_source_layout_rejects_installer_esd_for_now(self):
        iso=Path(self.temp.name)/'example.iso';iso.write_bytes(b'0'*1024)
        class Listing(FakeRunner):
            def run(self,argv,**kwargs):
                return subprocess.CompletedProcess(argv,0,'Type = Udf\n----------\n'+ '\n\n'.join(f'Path = {p}\nSize = 1' for p in windows.REQUIRED if p!='sources/install.wim'),'')
        with self.assertRaisesRegex(FlexBootError,'install.wim'):windows.inspect_source(iso,Listing())

    def test_renamed_zip_rejected(self):
        iso=Path(self.temp.name)/'example.iso';iso.write_bytes(b'0'*1024)
        for kind in ('zip', 'MBR', 'FAT'):
            for borrowed in (False, True):
                with self.subTest(kind=kind,borrowed=borrowed), patch.object(Runner,'run',return_value=subprocess.CompletedProcess([],0,f'Type = {kind}\n----------','')):
                    with self.assertRaisesRegex(FlexBootError,'renamed archives'):windows.inspect_source(iso,borrowed_winpe=borrowed)

    def test_older_iso_can_omit_usb_efi_fallback_only_with_donor(self):
        iso=Path(self.temp.name)/'old.iso';iso.write_bytes(b'0'*4096)
        listing='Type = Iso\n----------\n'+'\n\n'.join(f'Path = {p}\nSize = 1' for p in ('setup.exe','sources/setup.exe','sources/boot.wim','sources/install.wim'))
        with patch.object(Runner,'run',return_value=subprocess.CompletedProcess([],0,listing,'')):
            with self.assertRaises(FlexBootError):windows.inspect_source(iso)
            self.assertIn('sources/setup.exe',windows.inspect_source(iso,borrowed_winpe=True)['entries'])

    def test_borrowed_cli_dry_run_does_not_prepare_wim_or_target(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from flexboot.cli import main
        source=Path(self.temp.name)/'old.iso';source.write_bytes(b'old')
        donor=Path(self.temp.name)/'donor.iso';donor.write_bytes(b'donor')
        before=set(Path(self.temp.name).iterdir());output=StringIO()
        with patch.object(windows,'inspect_source',return_value={}) as inspect, patch.object(windows,'wim_info',side_effect=AssertionError('dry run extracted WIM')), redirect_stdout(output):
            self.assertEqual(main(['windows','add','/dev/missing',str(source),'--winpe-from',str(donor),'--dry-run','--json']),0)
        self.assertFalse(json.loads(output.getvalue())['persistent_changes'])
        self.assertFalse(json.loads(output.getvalue())['winpe_build_checked'])
        self.assertEqual(inspect.call_args_list[-1].kwargs,{'borrowed_winpe':True})
        self.assertEqual(set(Path(self.temp.name).iterdir()),before)

    def test_manifest_uuid_and_identifier_and_types(self):
        for field,value in [('uuid','FEDCBA9876543210'),('token','../outside'),('images',None),('helper_sha256','z'*64),('schema_version',4)]:
            state=copy.deepcopy(self.state);state[field]=value
            windows.state_path(self.paths).write_text(json.dumps(state))
            with self.subTest(field=field),self.assertRaises(MediaStateError):windows.load(self.paths)

    def test_runtime_changed_and_marker_changed(self):
        (self.paths.grub_dir/'windows/ntloader').write_bytes(b'corrupt')
        self.assertTrue(any('runtime hash mismatch' in p for p in windows.verify(self.paths)))
        (self.paths.windows/'.flexboot-windows'/f'{self.token}.marker').write_text('wrong')
        self.assertTrue(any('marker' in p for p in windows.verify(self.paths)))

    def test_no_windows_metadata_rejects_menu(self):
        windows.state_path(self.paths).unlink()
        with self.assertRaises(MediaStateError):windows.load(self.paths)

    def test_symlink_inventory_rejected(self):
        source=Path(self.temp.name)/'outside';source.write_text('outside')
        (self.paths.grub_dir/'windows/ntloader').unlink()
        (self.paths.grub_dir/'windows/ntloader').symlink_to(source)
        self.assertTrue(any('owned regular' in p for p in windows.verify(self.paths)))

    def test_interrupted_preparation_reported(self):
        (self.paths.windows/'windows/.preparing-interrupted').mkdir()
        self.assertTrue(any('interrupted' in p for p in windows.verify(self.paths)))

    def test_supported_winpe_builds_and_legacy_boundary(self):
        class Info(FakeRunner):
            def __init__(self, build, arch='9'):
                super().__init__(); self.build=build; self.arch=arch
            def run(self, argv, **kwargs):
                output = next(str(value).split('=',1)[1] for value in argv if str(value).startswith('--extract-xml='))
                Path(output).write_text(f'<WIM><IMAGE INDEX="2"><WINDOWS><ARCH>{self.arch}</ARCH><VERSION><BUILD>{self.build}</BUILD></VERSION></WINDOWS></IMAGE></WIM>')
                return subprocess.CompletedProcess(argv,0,'','')
        for build in (15063,17134,17763,19041,20348,26100):
            with self.subTest(build=build):
                self.assertEqual(windows.wim_info(Path('fixture.wim'), Info(build)), build)
        for build in (7601,9200,9600,14393):
            with self.subTest(build=build), self.assertRaisesRegex(FlexBootError,'multi-partition'):
                windows.wim_info(Path('fixture.wim'), Info(build))
        with self.assertRaisesRegex(FlexBootError, 'x86-64'):
            windows.wim_info(Path('fixture.wim'), Info(9600, '0'))
        self.assertEqual(windows.wim_info(Path('fixture.wim'), Info(9600), minimum_build=windows.MIN_LEGACY_BUILD), 9600)
        for build in (7600,7601):
            with self.subTest(build=build), self.assertRaises(FlexBootError):
                windows.wim_info(Path('fixture.wim'), Info(build), minimum_build=windows.MIN_LEGACY_BUILD)

    def test_borrowed_startup_never_uses_donor_setup(self):
        script = windows.startup(self.token, 'b'*64, 17134, source_setup=True)
        self.assertIn('"%FBSOURCE%\\sources\\setup.exe" /InstallFrom:', script)
        self.assertNotIn('%SYSTEMDRIVE%\\sources\\setup.exe', script)
        self.assertIn('if not "%MATCHES%"=="1" goto failed', script)

    def test_borrowed_provenance_is_validated(self):
        self.prepare_fake_record()
        record = self.state['images'][0]
        record['build'] = 17134
        record['winpe_source'] = {'filename': 'donor.iso', 'sha256': 'd'*64, 'installer_build': 9600}
        windows.state_path(self.paths).write_text(json.dumps(self.state))
        with self.assertRaises(MediaStateError): windows.load(self.paths)
        self.state['schema_version'] = 2
        windows.state_path(self.paths).write_text(json.dumps(self.state))
        self.assertEqual(windows.verify(self.paths), [])
        for key, value in [('sha256','invalid'), ('installer_build',19041), ('installer_build',7601), ('filename','../outside')]:
            changed = copy.deepcopy(self.state)
            changed['images'][0]['winpe_source'][key] = value
            windows.state_path(self.paths).write_text(json.dumps(changed))
            with self.subTest(key=key), self.assertRaises(FlexBootError): windows.load(self.paths)

    def test_startup_rejects_untrusted_values(self):
        with self.assertRaises(SafetyError):windows.startup('bad', 'b'*64,26100)
        script=windows.startup(self.token,'b'*64,19041)
        self.assertIn('/InstallFrom:',script)
        self.assertIn('"%SYSTEMDRIVE%\\sources\\setup.exe" /InstallFrom:', script)
        self.assertNotIn('"%FBSOURCE%\\setup.exe"', script)
        self.assertIn('"%SYSTEMDRIVE%\\sources\\setup.exe" /InstallFrom:', windows.startup(self.token, 'b'*64, 26100))
        self.assertIn('if not "%MATCHES%"=="1" goto failed',script)
        self.assertIn(' detach ',script)
        self.assertNotIn('powershell',script.lower())
        self.assertNotIn('tasklist',script.lower())
        self.assertNotIn('timeout',script.lower())

    def test_menu_quotes_filename_and_has_no_disk_order(self):
        state=copy.deepcopy(self.state)
        name="Windows 'test' image.iso"
        state['images']=[{'filename':name,'id':windows.identifier(name)}]
        text=windows.menu(state)
        self.assertIn("'\\''",text)
        self.assertNotIn('/dev/',text);self.assertNotIn('(hd0',text)
        self.assertIn('uuid='+state['uuid'],text)
        self.assertIn('wim=/windows/'+windows.identifier(name),text)
        self.assertEqual(text,windows.menu(state))

    def test_cpio_is_valid_and_deterministic(self):
        source=Path(self.temp.name)/'source';source.write_bytes(b'testing')
        a=Path(self.temp.name)/'a.cpio';b=a.with_name('b.cpio')
        windows.cpio({'boot.sdi':source},a);windows.cpio({'boot.sdi':source},b)
        self.assertEqual(a.read_bytes(),b.read_bytes())
        self.assertEqual(a.read_bytes()[:6],b'070701')
        self.assertIn(b'TRAILER!!!',a.read_bytes())

    def test_cpio_rejects_unsafe_names_before_creating_output(self):
        source = Path(self.temp.name) / 'source'
        source.write_bytes(b'testing')
        output = Path(self.temp.name) / 'unsafe.cpio'
        for name in ('../boot.wim', 'TRAILER!!!', 'startup.bat'):
            with self.subTest(name=name), self.assertRaises(SafetyError):
                windows.cpio({name: source}, output)
        self.assertFalse(output.exists())

    def test_pe_wrong_architecture_rejected(self):
        path=Path(self.temp.name)/'test.exe';pe(path);windows.pe_x64(path)
        contents=bytearray(path.read_bytes());contents[132:134]=b'\x4c\x01';path.write_bytes(contents)
        with self.assertRaises(FlexBootError):windows.pe_x64(path)

    def prepare_fake_record(self):
        name='windows.iso';image_id=windows.identifier(name)
        directory=self.paths.windows/'windows'/image_id;directory.mkdir()
        files={}
        for part in ('image.iso','boot.wim','initrd.cpio'):
            file=directory/part;file.write_bytes(b'test')
            files[part]={'size':4,'sha256':windows.sha256_file(file)}
        record={'filename':name,'id':image_id,'size':4,'build':26100,'files':files}
        self.state['images']=[record];windows.publish(self.paths,self.state,FakeRunner())
        return directory

    def test_remove_cleans_owned_prepared_resources(self):
        directory=self.prepare_fake_record();windows.remove(self.paths,'windows.iso',FakeRunner())
        self.assertFalse(directory.exists());self.assertEqual(windows.load(self.paths)['images'],[])
        self.assertEqual(windows.verify(self.paths),[])

    def test_remove_publication_failure_restores_everything(self):
        directory=self.prepare_fake_record()
        old_state=windows.state_path(self.paths).read_bytes();old_menu=(self.paths.grub_dir/'windows.cfg').read_bytes()
        with patch.object(windows,'publish',side_effect=FlexBootError('injected menu failure')):
            with self.assertRaises(FlexBootError):windows.remove(self.paths,'windows.iso',FakeRunner())
        self.assertTrue(directory.exists())
        self.assertEqual(windows.state_path(self.paths).read_bytes(),old_state)
        self.assertEqual((self.paths.grub_dir/'windows.cfg').read_bytes(),old_menu)

    def test_manifest_size_and_hash_corruption_rejected(self):
        directory=self.prepare_fake_record();(directory/'image.iso').write_bytes(b'evil')
        self.assertTrue(any('integrity mismatch' in p for p in windows.verify(self.paths)))
        self.state['images'][0]['size']=99
        windows.state_path(self.paths).write_text(json.dumps(self.state))
        with self.assertRaises(MediaStateError):windows.load(self.paths)

    def test_custom_label_survives_windows_publication_and_removal(self):
        from flexboot.menu import configure, load_settings
        source = Path(self.temp.name) / 'test.iso'
        source.write_bytes(b'0' * 4096)
        self.fake_add(source)
        configure(self.paths, 'label', entry='Windows:test.iso', label='Windows installation', runner=FakeRunner())
        configure(self.paths, 'order', order=['Windows:test.iso'], runner=FakeRunner())
        self.fake_add(source, replace=True)
        self.assertIn('[Windows] Windows installation', (self.paths.grub_dir / 'generated.cfg').read_text())
        self.assertNotIn('source ($root)/boot/grub/windows.cfg', (self.paths.grub_dir / 'grub.cfg').read_text())
        windows.remove(self.paths, source.name, FakeRunner())
        self.assertNotIn('menuentry ', (self.paths.grub_dir / 'generated.cfg').read_text())
        self.assertEqual(load_settings(self.paths)['labels']['Windows:test.iso'], 'Windows installation')

    def test_combined_menu_publication_failure_rolls_back_every_file(self):
        import os
        from copy import deepcopy
        changed = deepcopy(self.state)
        changed['images'] = [{'filename': 'new.iso', 'id': 'c' * 64}]
        files = [windows.state_path(self.paths), self.paths.grub_dir / 'windows.cfg',
                 self.paths.grub_dir / 'generated.cfg', self.paths.grub_dir / 'grub.cfg']
        original = [p.read_bytes() for p in files]
        replace = os.replace
        def fail_generated(source, destination):
            if Path(source).name == 'generated.cfg.new':
                raise OSError('injected publication failure')
            return replace(source, destination)
        with patch('flexboot.windows.os.replace', side_effect=fail_generated), self.assertRaises(OSError):
            windows.publish(self.paths, changed, FakeRunner())
        self.assertEqual([p.read_bytes() for p in files], original)
        self.assertFalse(list(self.paths.grub_dir.glob('*.new')))

    def test_stale_windows_menu_detected(self):
        (self.paths.grub_dir/'windows.cfg').write_text('bad menu')
        self.assertTrue(any('stale' in p for p in windows.verify(self.paths)))

    def fake_add(self, source, *, runner=None, replace=False, winpe_from=None, donor_build=17134, installer_build=9600, allow_windows7_csm=False):
        entries={p:(p,512 if p.endswith('.efi') else 1) for p in windows.REQUIRED}
        entries['sources/setup.exe'] = ('sources/setup.exe', 512)
        def extract(_source,entry,destination):
            if entry[0].endswith(('.efi', '.exe')):pe(destination)
            else:destination.write_bytes(b'a')
        facts={'entries':entries,'size':source.stat().st_size}
        def info(path, _runner, **kwargs):
            build = installer_build if path.name == 'installer.wim' else (donor_build if winpe_from else 26100)
            if build < kwargs.get('minimum_build', windows.MIN_WINPE_BUILD):
                raise FlexBootError('WinPE build below minimum')
            return build
        with patch.object(windows,'inspect_source',return_value=facts), patch.object(windows,'extract',side_effect=extract), patch.object(windows,'wim_info',side_effect=info):
            return windows.add(self.paths,source,runner or FakeRunner(),replace=replace,winpe_from=winpe_from,allow_windows7_csm=allow_windows7_csm)

    def test_windows7_explicit_gate_and_schema_preserved_with_other_images(self):
        source=Path(self.temp.name)/'win7.iso';source.write_bytes(b'old installer')
        donor=Path(self.temp.name)/'donor.iso';donor.write_bytes(b'PE source')
        with self.assertRaises(FlexBootError):
            self.fake_add(source,winpe_from=donor,installer_build=7600)
        self.assertEqual(windows.load(self.paths)['images'], [])
        record,status=self.fake_add(source,winpe_from=donor,installer_build=7600,allow_windows7_csm=True)
        self.assertTrue(record['requires_csm'])
        self.assertEqual(status,'added')
        self.assertEqual(windows.load(self.paths)['schema_version'],3)
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(self.fake_add(source)[1],'skipped')
        source.write_bytes(b'replacement')
        with self.assertRaises(FlexBootError):
            self.fake_add(source,replace=True,winpe_from=donor,installer_build=7600)
        other=source.with_name('server.iso');other.write_bytes(b'server')
        self.fake_add(other,winpe_from=donor)
        self.assertEqual(windows.load(self.paths)['schema_version'],3)
        self.assertEqual(windows.verify(self.paths),[])
        windows.remove(self.paths,other.name,FakeRunner())
        self.assertEqual(windows.verify(self.paths),[])

    def test_windows7_flag_rejects_missing_donor_and_wrong_builds(self):
        source=Path(self.temp.name)/'old.iso';source.write_bytes(b'old')
        donor=Path(self.temp.name)/'donor.iso';donor.write_bytes(b'donor')
        with self.assertRaisesRegex(FlexBootError,'requires --winpe-from'):
            self.fake_add(source,allow_windows7_csm=True)
        for build in (7602,9200,9600,14393,19041):
            with self.subTest(build=build),self.assertRaisesRegex(FlexBootError,'only for Windows 7'):
                self.fake_add(source,winpe_from=donor,installer_build=build,allow_windows7_csm=True)
        self.fake_add(source,winpe_from=donor)
        with self.assertRaisesRegex(FlexBootError,'only for Windows 7'):
            self.fake_add(source,winpe_from=donor,allow_windows7_csm=True)

    def test_csm_metadata_and_menu_annotation_cannot_be_lost_by_alias(self):
        from flexboot.grub import generated_config
        self.prepare_fake_record()
        record=self.state['images'][0]
        record.update(build=17134,requires_csm=True,winpe_source={'filename':'donor.iso','sha256':'d'*64,'installer_build':7600})
        self.state['schema_version']=3
        windows.state_path(self.paths).write_text(json.dumps(self.state))
        self.assertEqual(windows.load(self.paths),self.state)
        settings={'schema_version':1,'labels':{'Windows:'+record['filename']:'My custom name'},'order':[]}
        self.assertIn('[Windows] My custom name [CSM required]',generated_config([],self.state,settings))
        for schema,marker,build in [(2,True,7600),(3,False,7600),(3,1,7600),(3,True,9600)]:
            invalid=copy.deepcopy(self.state);invalid['schema_version']=schema
            invalid['images'][0]['requires_csm']=marker
            invalid['images'][0]['winpe_source']['installer_build']=build
            windows.state_path(self.paths).write_text(json.dumps(invalid))
            with self.subTest(schema=schema,marker=marker,build=build),self.assertRaises(MediaStateError):
                windows.load(self.paths)

    def test_windows7_cli_dry_run_reports_unchecked_firmware(self):
        from contextlib import redirect_stdout, redirect_stderr
        from io import StringIO
        from flexboot.cli import main
        output=StringIO();errors=StringIO()
        with redirect_stderr(errors):
            self.assertEqual(main(['windows','add','/dev/missing','win7.iso','--allow-windows7-csm','--dry-run']),2)
        with patch.object(windows,'inspect_source',return_value={}),redirect_stdout(output):
            self.assertEqual(main(['windows','add','/dev/missing','win7.iso','--winpe-from','donor.iso','--allow-windows7-csm','--dry-run','--json']),0)
        payload=json.loads(output.getvalue())
        self.assertTrue(payload['requires_csm'])
        self.assertFalse(payload['firmware_checked'])
        self.assertFalse(payload['persistent_changes'])

    def test_borrowed_preparation_integrity_and_replacement(self):
        source=Path(self.temp.name)/'old.iso';source.write_bytes(b'old installer')
        donor=Path(self.temp.name)/'donor.iso';donor.write_bytes(b'PE source')
        record,status=self.fake_add(source,winpe_from=donor)
        self.assertEqual(status,'added')
        self.assertEqual(record['winpe_source']['sha256'],windows.sha256_file(donor))
        self.assertEqual(windows.load(self.paths)['schema_version'],2)
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(self.fake_add(source,winpe_from=donor)[1],'skipped')
        donor.write_bytes(b'changed donor')
        with self.assertRaisesRegex(FlexBootError,'Different WinPE'):
            self.fake_add(source,winpe_from=donor)
        before=windows.state_path(self.paths).read_bytes()
        with self.assertRaisesRegex(FlexBootError,'Windows 10-era'):
            self.fake_add(source,winpe_from=donor,replace=True,donor_build=26100)
        self.assertEqual(windows.state_path(self.paths).read_bytes(),before)
        self.assertEqual(windows.verify(self.paths),[])

    def test_borrowed_source_change_rolls_back(self):
        source=Path(self.temp.name)/'old.iso';source.write_bytes(b'old installer')
        donor=Path(self.temp.name)/'donor.iso';donor.write_bytes(b'PE source')
        identity=windows._identity(donor)
        with patch.object(windows,'_identity',side_effect=[identity,identity,(*identity[:-1],identity[-1]+1)]):
            with self.assertRaisesRegex(FlexBootError,'changed during preparation'):
                self.fake_add(source,winpe_from=donor)
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(list((self.paths.windows/'windows').iterdir()),[])

    def test_add_skip_replace_and_full_verify(self):
        source=Path(self.temp.name)/'space and quote\' image.iso';source.write_bytes(b'0'*4096)
        record,status=self.fake_add(source);self.assertEqual(status,'added')
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(self.fake_add(source)[1],'skipped')
        source.write_bytes(b'1'*4096)
        with self.assertRaises(FlexBootError):self.fake_add(source)
        self.assertEqual(self.fake_add(source,replace=True)[1],'replaced')
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(len(windows.load(self.paths)['images']),1)

    def test_add_update_failure_leaves_no_resources_or_menu(self):
        source=Path(self.temp.name)/'test.iso';source.write_bytes(b'0'*4096)
        class Failing(FakeRunner):
            def run(self,argv,**kwargs):
                if 'update' in argv:raise FlexBootError('injected WIM failure')
                return super().run(argv,**kwargs)
        with self.assertRaises(FlexBootError):self.fake_add(source,runner=Failing())
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(list((self.paths.windows/'windows').iterdir()),[])

    def test_missing_native_setup_leaves_media_unchanged(self):
        source = Path(self.temp.name) / 'test.iso'
        source.write_bytes(b'0' * 4096)
        class MissingSetup(FakeRunner):
            def run(self, argv, **kwargs):
                if '--path=/sources/setup.exe' in argv:
                    raise FlexBootError('missing native WinPE Setup')
                return super().run(argv, **kwargs)
        with self.assertRaisesRegex(FlexBootError, 'native WinPE Setup'):
            self.fake_add(source, runner=MissingSetup())
        self.assertEqual(windows.verify(self.paths), [])
        self.assertEqual(list((self.paths.windows / 'windows').iterdir()), [])

    def test_runtime_requires_pinned_loader_and_ntfs_module(self):
        loader = self.paths.grub_dir / 'windows/ntloader'
        helper = self.paths.grub_dir / 'windows/flexboot-win.exe'
        with self.assertRaisesRegex(SafetyError, 'expected SHA-256'):
            windows.require_runtime(loader, '0' * 64, helper)
        contents = bytearray(loader.read_bytes())
        contents.extend(b'\0' * 512)
        contents[0x202:0x206] = b'HdrS'
        loader.write_bytes(contents)
        with patch.object(Runner, 'run', return_value=subprocess.CompletedProcess([], 0, 'grub-install (GRUB) 2.14', '')), \
                patch('flexboot.doctor.GRUB_DIRECTORIES', ()):
            with self.assertRaisesRegex(FlexBootError, 'NTFS module'):
                windows.require_runtime(loader, windows.sha256_file(loader), helper)

    def test_replace_publication_failure_preserves_previous_iso(self):
        source=Path(self.temp.name)/'test.iso';source.write_bytes(b'0'*4096)
        record,_=self.fake_add(source);old_state=windows.state_path(self.paths).read_bytes()
        source.write_bytes(b'1'*4096)
        def broken_publish(paths,state,runner):
            windows.state_path(paths).write_text('partial failure')
            raise FlexBootError('injected publication failure')
        with patch.object(windows,'publish',side_effect=broken_publish),self.assertRaises(FlexBootError):
            self.fake_add(source,replace=True)
        self.assertEqual(windows.state_path(self.paths).read_bytes(),old_state)
        self.assertEqual((self.paths.windows/'windows'/record['id']/'image.iso').read_bytes(),b'0'*4096)
        self.assertEqual(windows.verify(self.paths),[])

    def test_remove_refuses_untracked_files(self):
        directory=self.prepare_fake_record();(directory/'user-data.txt').write_text('preserve')
        with self.assertRaises(SafetyError):windows.remove(self.paths,'windows.iso',FakeRunner())
        self.assertTrue((directory/'user-data.txt').exists())

    def test_prepare_root_symlink_rejected(self):
        root=self.paths.windows/'windows';root.rmdir()
        outside=Path(self.temp.name)/'outside';outside.mkdir();root.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(SafetyError):windows.load(self.paths)


    def test_source_changed_after_inspection_is_not_published(self):
        source=Path(self.temp.name)/'test.iso';source.write_bytes(b'0'*4096)
        original_copy=windows.copy_and_hash
        def changing_copy(src,dst,progress=None):
            digest=original_copy(src,dst,progress)
            src.write_bytes(b'1'*4096)
            return digest
        with patch.object(windows,'copy_and_hash',side_effect=changing_copy):
            with self.assertRaisesRegex(FlexBootError,'changed after inspection'):self.fake_add(source)
        self.assertEqual(windows.verify(self.paths),[])
        self.assertEqual(list((self.paths.windows/'windows').iterdir()),[])


    def test_stale_partition_node_rejected_before_use(self):
        import os,stat
        from types import SimpleNamespace
        from flexboot.devices import Device
        from flexboot.disk import validate_partition_nodes
        part=Device('fixturep1',Path('/dev/fixturep1'),'part',1024,major_minor='259:11')
        root=Device('fixture',Path('/dev/fixture'),'loop',4096,children=(part,))
        with patch('flexboot.disk.discover',return_value=[root]),patch.object(Path,'stat',return_value=SimpleNamespace(st_mode=stat.S_IFBLK,st_rdev=os.makedev(259,12))):
            with self.assertRaisesRegex(SafetyError,'identity differs'):validate_partition_nodes(root.path,FakeRunner())


    def test_bad_sector_information_never_erases(self):
        class BadSector(FakeRunner):
            def run(self,argv,**kwargs):
                self.planned.append(list(map(str,argv)))
                return subprocess.CompletedProcess(argv,0,'invalid','')
        runner=BadSector()
        with self.assertRaises(FlexBootError):partition_device(Path('/dev/fixture'),runner)
        self.assertFalse(any(c[0]=='wipefs' for c in runner.planned))

    def test_bad_capacity_information_never_erases(self):
        class BadCapacity(FakeRunner):
            def run(self, argv, **kwargs):
                self.planned.append(list(map(str, argv)))
                return subprocess.CompletedProcess(argv, 0, '512' if '--getss' in argv else 'invalid', '')
        runner = BadCapacity()
        with self.assertRaisesRegex(FlexBootError, 'capacity'):
            partition_device(Path('/dev/fixture'), runner, windows_size=8 * 1024**3)
        self.assertFalse(any(c[0] == 'wipefs' for c in runner.planned))

    def test_windows_doctor_rejects_old_grub(self):
        from flexboot.doctor import diagnose
        with patch('flexboot.doctor.shutil.which', return_value='/usr/bin/tool'), \
                patch.object(Runner, 'run', return_value=subprocess.CompletedProcess([], 0, 'grub-install (GRUB) 2.06', '')):
            report = diagnose('windows')
        self.assertFalse(report['ready'])
        self.assertIn('GRUB >= 2.12', report['capabilities']['windows']['missing'])



if __name__=='__main__':unittest.main()
