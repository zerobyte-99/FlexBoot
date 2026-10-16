"""Opt-in Windows installer preparation; no downloads or implicit repartitioning."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from .branding import BRAND
from .errors import FlexBootError, MediaStateError, SafetyError
from .grub import atomic_text, grub_quote, validate_config
from .iso import validate_filename
from .manifest import copy_and_hash, sha256_file
from .process import Runner

DIGEST = re.compile(r"[0-9a-f]{64}")
UUID = re.compile(r"[0-9a-fA-F-]{8,64}")
REQUIRED = ('efi/boot/bootx64.efi', 'boot/boot.sdi', 'sources/boot.wim', 'sources/install.wim', 'setup.exe')
# ISO attachment exists on Windows 8, but removable multi-partition USB access
# requires WinPE 10 version 1703. Older PE exposes only the boot partition.
MIN_WINPE_BUILD = 15063
MAX_DONOR_WINPE_BUILD = 19045
# Windows 7 remains excluded pending installed-OS firmware validation.
MIN_LEGACY_BUILD = 9200


def identifier(filename: str) -> str:
    validate_filename(filename)
    return hashlib.sha256(filename.encode('utf-8')).hexdigest()


def regular(path: Path, base: Path) -> None:
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
        raise SafetyError(f"Expected an owned regular file: {path}")


def pe_x64(path: Path) -> None:
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise FlexBootError(f"Not a PE executable: {path}")
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset > 1024 * 1024 or offset < 64:
            raise FlexBootError('Invalid PE header offset')
        stream.seek(offset)
        signature = stream.read(6)
    if signature != b'PE\0\0\x64\x86':
        raise FlexBootError(f"Expected an x86-64 PE executable: {path}")


def require_runtime(ntloader: Path, expected: str, helper: Path) -> dict:
    if not DIGEST.fullmatch(expected):
        raise FlexBootError('Supply the exact expected NTloader SHA-256')
    for path in (ntloader, helper):
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024**2:
            raise FlexBootError(f'Invalid local Windows runtime: {path}')
        pe_x64(path)
    if sha256_file(ntloader) != expected:
        raise SafetyError('NTloader does not match its supplied expected SHA-256')
    # Linux-protocol handoff requires the hybrid NTloader header as well as PE.
    with ntloader.open('rb') as stream:
        header = stream.read(0x208)
    if header[0x202:0x206] != b'HdrS':
        raise FlexBootError('NTloader must support the Linux-protocol handoff')
    version = Runner().run(['grub-install', '--version']).stdout
    parsed = re.search(r'\b(\d+)\.(\d+)', version)
    if not parsed or tuple(map(int, parsed.groups())) < (2, 12):
        raise FlexBootError('Windows support currently requires host GRUB >= 2.12')
    from .doctor import GRUB_DIRECTORIES
    if not any((directory / 'ntfs.mod').is_file() for directory in GRUB_DIRECTORIES):
        raise FlexBootError('Windows support requires the host GRUB x86_64-efi NTFS module')
    return {'ntloader_sha256': expected, 'helper_sha256': sha256_file(helper)}


def archive_entries(text: str) -> dict[str, tuple[str, int]]:
    if '----------' not in text:
        raise FlexBootError('Malformed ISO archive listing')
    result = {}
    for block in re.split(r'\r?\n\r?\n', text.split('----------', 1)[1].strip()):
        fields = {}
        for line in block.splitlines():
            if ' = ' in line:
                key, value = line.split(' = ', 1)
                if key in fields:
                    raise SafetyError('Duplicate field in ISO listing')
                fields[key] = value
        name = fields.get('Path', '')
        if not name:
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or any(ord(c)<32 for c in name):
            raise SafetyError(f'Unsafe ISO archive path: {name!r}')
        folded = name.casefold()
        if folded in result:
            raise SafetyError(f'Case-insensitive archive path collision: {name}')
        try:
            size = int(fields.get('Size') or '0') if fields.get('Folder') == '+' else int(fields.get('Size', '0'))
        except ValueError as exc:
            raise FlexBootError('Invalid archive resource size') from exc
        if size < 0 or len(result) >= 100000:
            raise FlexBootError('Invalid or excessively large ISO listing')
        result[folded] = (name, size)
    return result


def inspect_source(source: Path, runner: Runner | None = None, *, borrowed_winpe: bool = False) -> dict:
    validate_filename(source.name)
    if not source.is_file():
        raise FlexBootError(f'ISO is not a regular file: {source}')
    run = runner or Runner()
    listing = run.run(['7z', 'l', '-slt', '-spd', '--', source]).stdout
    if not re.search(r'^Type = (?:Iso|Udf)$', listing, re.MULTILINE | re.IGNORECASE):
        raise FlexBootError('Windows sources must be ISO9660/UDF images, not renamed archives')
    entries = archive_entries(listing)
    required = ('sources/boot.wim', 'sources/install.wim', 'sources/setup.exe', 'setup.exe') if borrowed_winpe else REQUIRED
    missing = [name for name in required if name not in entries or not entries[name][1]]
    if missing:
        raise FlexBootError('Not a supported Windows x64 WIM installer: missing ' + ', '.join(missing))
    if any(entries[name][1] > source.stat().st_size for name in required):
        raise FlexBootError('ISO resource is larger than its containing image')
    if any(entries[name][1] > 16 * 1024**2 for name in ('boot/boot.sdi', 'efi/boot/bootx64.efi', 'sources/setup.exe') if name in entries):
        raise FlexBootError('Windows boot resource exceeds its size limit')
    if entries['sources/boot.wim'][1] > 2 * 1024**3:
        raise FlexBootError('Windows boot WIM exceeds the supported 2 GiB limit')
    return {'entries': entries, 'size': source.stat().st_size}


def extract(source: Path, entry: tuple[str, int], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as output:
        result = subprocess.run(['7z', 'e', '-so', '-spd', '--', str(source), entry[0]], stdout=output, stderr=subprocess.PIPE, shell=False)
        output.flush(); os.fsync(output.fileno())
    if result.returncode or destination.stat().st_size != entry[1]:
        raise FlexBootError(f'Failed to extract ISO resource: {entry[0]}')


def wim_info(path: Path, runner: Runner, *, minimum_build: int = MIN_WINPE_BUILD) -> int:
    with tempfile.TemporaryDirectory(prefix='flexboot-wim-info-') as raw:
        xml = Path(raw) / 'info.xml'
        runner.run(['wimlib-imagex', 'info', path, f'--extract-xml={xml}'], mutate=True)
        if xml.stat().st_size > 2 * 1024**2:
            raise FlexBootError('WIM metadata exceeds inspection limit')
        text = xml.read_bytes()
    try:
        root = ET.fromstring(text)
        image = next(item for item in root.findall('IMAGE') if item.attrib.get('INDEX') == '2')
        if image.findtext('WINDOWS/ARCH') != '9':
            raise ValueError('boot index 2 must be x86-64')
        build = int(image.findtext('WINDOWS/VERSION/BUILD', '0'))
        if build < minimum_build:
            reason = ' for multi-partition removable USB support' if minimum_build == MIN_WINPE_BUILD else ''
            raise ValueError(f'WinPE build must be >= {minimum_build}{reason}')
        return build
    except (ET.ParseError, ValueError, StopIteration) as exc:
        raise FlexBootError(f'Unsupported WinPE WIM metadata: {exc}') from exc


def cpio(files: dict[str, Path], destination: Path) -> None:
    """Small deterministic newc writer; only fixed ASCII archive names are allowed."""
    if not set(files).issubset({'boot.sdi', 'bootx64.efi', 'boot.wim'}):
        raise SafetyError('Unsupported Windows boot archive filename')
    if any(not 0 < path.stat().st_size < 2**32 for path in files.values()):
        raise FlexBootError('Windows boot archive resource exceeds the newc size limit')
    with destination.open('xb') as output:
        for number, (name, path) in enumerate([*sorted(files.items()), ('TRAILER!!!', None)], 1):
            encoded = name.encode('ascii') + b'\0'
            size = path.stat().st_size if path else 0
            values = [number, 0o100644, 0, 0, 1, 0, size, 0, 0, 0, 0, len(encoded), 0]
            header = b'070701' + ''.join(f'{value:08x}' for value in values).encode()
            output.write(header + encoded)
            output.write(b'\0' * (-(len(header) + len(encoded)) % 4))
            if path:
                with path.open('rb') as source: shutil.copyfileobj(source, output)
            output.write(b'\0' * (-size % 4))
        output.flush(); os.fsync(output.fileno())


def startup(token: str, image_id: str, build: int, *, source_setup: bool = False) -> str:
    if not DIGEST.fullmatch(token) or not DIGEST.fullmatch(image_id):
        raise SafetyError('Unsafe Windows media/image identifier')
    # The WinPE-native Setup parser uses the colon form, including Windows 11.
    # The ISO-root Windows 11 launcher's space form is a different interface.
    argument = '/InstallFrom:'
    setup = r'%FBSOURCE%\sources\setup.exe' if source_setup else r'%SYSTEMDRIVE%\sources\setup.exe'
    # All paths in this program are generated hexadecimal IDs, not ISO filenames.
    return (r'''@echo off
setlocal EnableExtensions EnableDelayedExpansion
set LOG=%SYSTEMROOT%\Temp\flexboot.log
echo FLEXBOOT_IMAGE=IMAGEID >"%LOG%"
echo INITIALIZING_DEVICES >>"%LOG%"
wpeinit >>"%LOG%" 2>&1
if errorlevel 1 goto failed
echo DEVICES_INITIALIZED >>"%LOG%"
set FBROOT=
set MATCHES=0
for %%D in (C D E F G H I J K L M N O P Q R S T U V W Y Z) do (
  if exist %%D:\.flexboot-windows\TOKEN.marker (
    set /a MATCHES+=1
    set FBROOT=%%D:
  )
)
echo SOURCE_VOLUMES=%MATCHES% >>"%LOG%"
if not "%MATCHES%"=="1" goto failed
set FBISO=%FBROOT%\windows\IMAGEID\image.iso
if not exist "%FBISO%" goto failed
%SYSTEMROOT%\System32\flexboot-win.exe mount "%FBISO%" >"%SYSTEMROOT%\Temp\flexboot-volume.txt" 2>>"%LOG%"
if errorlevel 1 goto failed
set FBSOURCE=
for /f "usebackq delims=" %%D in ("%SYSTEMROOT%\Temp\flexboot-volume.txt") do set FBSOURCE=%%D
if not defined FBSOURCE goto detach_failed
if not exist "%FBSOURCE%\sources\install.wim" goto detach_failed
dism /English /Get-WimInfo /WimFile:"%FBSOURCE%\sources\install.wim" >>"%LOG%" 2>&1
if errorlevel 1 goto detach_failed
echo PAYLOAD_VALIDATED >>"%LOG%"
rem Use the selected installation engine; never fall back to a different ISO.
if not exist "SETUPPATH" goto detach_failed
echo INSTALL_SOURCE=%FBSOURCE% >>"%LOG%"
echo SETUP_ENGINE=SETUPPATH >>"%LOG%"
"SETUPPATH" INSTALLARG"%FBSOURCE%\sources\install.wim"
set SETUP_EXIT=%ERRORLEVEL%
echo SETUP_EXIT=%SETUP_EXIT% >>"%LOG%"
if not "%SETUP_EXIT%"=="0" goto detach_failed
goto done
:detach_failed
%SYSTEMROOT%\System32\flexboot-win.exe detach "%FBISO%" >>"%LOG%" 2>&1
:failed
echo FlexBoot could not identify or prepare the selected Windows source.
echo Setup was not allowed to discover a different installer.
if defined LOG type "%LOG%"
cmd.exe
:done
cmd.exe
''').replace('TOKEN', token).replace('IMAGEID', image_id).replace('INSTALLARG', argument).replace('SETUPPATH', setup).replace('\n', '\r\n')


def state_path(paths) -> Path:
    return paths.data / BRAND.metadata_dir / 'windows.json'


def load(paths) -> dict | None:
    path = state_path(paths)
    if not path.exists():
        if (paths.grub_dir / "windows.cfg").exists():
            raise MediaStateError("Windows boot menu exists without enabled Windows metadata")
        if paths.windows is not None:
            raise MediaStateError('Windows partition has no installation metadata')
        return None
    regular(path, paths.data)
    try:
        state = json.loads(path.read_text())
        if state['schema_version'] not in (1, 2, 3) or not UUID.fullmatch(state['uuid']) or not UUID.fullmatch(state['efi_uuid']) or not DIGEST.fullmatch(state['token']):
            raise ValueError('invalid schema or identity')
        for key in ('ntloader_sha256', 'helper_sha256'):
            if not DIGEST.fullmatch(state[key]): raise ValueError('invalid runtime hash')
        if paths.efi_uuid != state['efi_uuid']:
            raise ValueError('actual EFI UUID differs from Windows metadata')
        boot_role = state.get('boot_partition_role', 'esp')
        if boot_role not in ('esp', 'basic-fat') or boot_role != paths.boot_partition_role:
            raise ValueError('actual boot partition role differs from Windows metadata')
        if paths.windows is None or paths.windows_uuid != state['uuid']:
            raise ValueError('actual Windows filesystem UUID differs from metadata')
        for directory in (paths.windows/'windows', paths.windows/'.flexboot-windows', paths.grub_dir/'windows'):
            base = paths.windows if directory.is_relative_to(paths.windows) else paths.efi
            if directory.is_symlink() or not directory.is_dir() or not directory.resolve().is_relative_to(base.resolve()):
                raise SafetyError('Windows preparation directory escapes its filesystem')
        records = state['images']
        if not isinstance(records, list) or len({r['filename'] for r in records}) != len(records):
            raise ValueError('invalid or duplicate image records')
        for record in records:
            if record['id'] != identifier(record['filename']) or type(record['size']) is not int or record['size'] <= 0:
                raise ValueError('invalid image identifier or size')
            if type(record['build']) is not int or record['build'] < MIN_WINPE_BUILD:
                raise ValueError('invalid WinPE build')
            if 'winpe_source' in record:
                donor = record['winpe_source']
                if state['schema_version'] not in (2, 3) or not isinstance(donor, dict) or set(donor) != {'filename', 'sha256', 'installer_build'}:
                    raise ValueError('invalid borrowed WinPE provenance')
                validate_filename(donor['filename'])
                if not DIGEST.fullmatch(donor['sha256']) or record['build'] > MAX_DONOR_WINPE_BUILD:
                    raise ValueError('invalid borrowed WinPE source or build')
                legacy_csm = state['schema_version'] == 3 and record.get('requires_csm') is True and donor['installer_build'] in (7600, 7601)
                if type(donor['installer_build']) is not int or not (legacy_csm or MIN_LEGACY_BUILD <= donor['installer_build'] < MIN_WINPE_BUILD):
                    raise ValueError('invalid older installer build')
            if 'requires_csm' in record and not (state['schema_version'] == 3 and record['requires_csm'] is True and record.get('winpe_source', {}).get('installer_build') in (7600, 7601)):
                raise ValueError('invalid CSM requirement')
            if record['size'] != record['files']['image.iso']['size']:
                raise ValueError('image size differs from resource inventory')
            expected = {'image.iso', 'boot.wim', 'initrd.cpio'}
            if set(record['files']) != expected:
                raise ValueError('invalid prepared resource inventory')
            for info in record['files'].values():
                if type(info['size']) is not int or info['size'] <= 0 or not DIGEST.fullmatch(info['sha256']):
                    raise ValueError('invalid resource hash or size')
        return state
    except (ValueError, KeyError, TypeError) as exc:
        raise MediaStateError(f'Malformed Windows metadata: {exc}') from exc


def menu(state: dict, labels: dict | None = None) -> str:
    lines = ['# FlexBoot Windows entries. Prepared resources; source ISOs remain intact.', '']
    for record in sorted(state['images'], key=lambda r:r['filename'].casefold()):
        image_id = record['id']
        title = '[Windows] ' + (labels or {}).get(record['filename'], record['filename'] + ' — Windows installer')
        if record.get('requires_csm'):
            title += ' [CSM required]'
        lines.extend([f"menuentry {grub_quote(title)} {{",
                      '  insmod ntfs', f"  search --no-floppy --fs-uuid --set=flexboot_efi {state['efi_uuid']}", f"  search --no-floppy --fs-uuid --set=flexboot_windows {state['uuid']}",
                      f"  linux ($flexboot_efi)/boot/grub/windows/ntloader uuid={state['uuid']} wim=/windows/{image_id}/boot.wim hires=no gfxmode=1024x768",
                      f'  initrd ($flexboot_windows)/windows/{image_id}/initrd.cpio', '}', ''])
    return '\n'.join(lines)


def publish(paths, state: dict, runner: Runner) -> None:
    from .manifest import Manifest
    from .media import menu_config
    from .grub import base_config
    manifest = Manifest.load(paths.manifest)
    contents = {
        state_path(paths): json.dumps(state, indent=2, sort_keys=True) + '\n',
        paths.grub_dir / 'windows.cfg': menu(state),
        paths.grub_dir / 'generated.cfg': menu_config(paths, manifest, state),
        paths.grub_dir / 'grub.cfg': base_config(manifest.data_filesystem_uuid),
    }
    originals = {path: path.read_text() if path.exists() else None for path in contents}
    candidates = []
    try:
        # Validate every fragment before publishing any state or menu changes.
        for path, text in contents.items():
            candidate = path.with_name(path.name + '.new')
            candidates.append(candidate)
            atomic_text(candidate, text)
            if path.suffix == '.cfg':
                validate_config(candidate, runner)
        for path, candidate in zip(contents, candidates):
            os.replace(candidate, path)
    except BaseException:
        for path, text in originals.items():
            if text is None:
                path.unlink(missing_ok=True)
            else:
                atomic_text(path, text)
        raise
    finally:
        for candidate in candidates:
            candidate.unlink(missing_ok=True)


def initialize(paths, ntloader: Path, helper: Path, expected: str, runner: Runner) -> None:
    runtime = require_runtime(ntloader, expected, helper)
    token = uuid.uuid4().hex + uuid.uuid4().hex
    root = paths.windows
    (root / 'windows').mkdir()
    marker = root / '.flexboot-windows'
    marker.mkdir(); atomic_text(marker / f'{token}.marker', paths.windows_uuid+'\n')
    target = paths.grub_dir / 'windows'; target.mkdir()
    if copy_and_hash(ntloader, target / 'ntloader') != runtime['ntloader_sha256']:
        raise SafetyError('NTloader changed during initialization')
    if copy_and_hash(helper, target / 'flexboot-win.exe') != runtime['helper_sha256']:
        raise SafetyError('Windows helper changed during initialization')
    publish(paths, {'schema_version':1, 'uuid':paths.windows_uuid, 'efi_uuid':paths.efi_uuid,
                    'boot_partition_role': paths.boot_partition_role, 'token':token, **runtime, 'images':[]}, runner)


def verify(paths, *, full_hash: bool = True, check_menu: bool = True) -> list[str]:
    try:
        state = load(paths)
        if state is None: return []
        root = paths.windows
        problems = []
        marker = root / '.flexboot-windows' / (state['token']+'.marker')
        regular(marker, root)
        if marker.read_text().strip() != state['uuid']: problems.append('Windows source marker has the wrong UUID')
        for name, key in (('ntloader','ntloader_sha256'), ('flexboot-win.exe','helper_sha256')):
            path = paths.grub_dir/'windows'/name;regular(path,paths.efi)
            if sha256_file(path) != state[key]:problems.append(f'Windows runtime hash mismatch: {name}')
        expected_ids = {r['id'] for r in state['images']}
        if {p.name for p in (root/'windows').iterdir()} != expected_ids:
            problems.append('Untracked, missing, or interrupted Windows preparation directories')
        for record in state['images']:
            directory=root/'windows'/record['id']
            if directory.is_symlink(): raise SafetyError('Windows image directory is a symlink')
            if {p.name for p in directory.iterdir()} != set(record['files']):
                problems.append(f'Untracked or missing prepared files: {record["filename"]}')
            for name, info in record['files'].items():
                path=directory/name;regular(path,root)
                if path.stat().st_size != info['size'] or (full_hash and sha256_file(path)!=info['sha256']):
                    problems.append(f'Windows resource integrity mismatch: {record["filename"]}/{name}')
        if check_menu:
            cfg=paths.grub_dir/'windows.cfg';regular(cfg,paths.efi)
            if cfg.read_text()!=menu(state):problems.append('Windows GRUB menu is stale')
            base=paths.grub_dir/'grub.cfg'
            if base.exists() and 'source ($root)/boot/grub/generated.cfg' not in base.read_text():
                problems.append('Base GRUB configuration does not include Windows entries')
        return problems
    except (FlexBootError,OSError) as exc:
        return [str(exc)]


def _identity(path: Path) -> tuple[int, ...]:
    value = path.stat()
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def add(paths, source: Path, runner: Runner, *, replace: bool = False, winpe_from: Path | None = None, allow_windows7_csm: bool = False):
    if allow_windows7_csm and winpe_from is None:
        raise FlexBootError('--allow-windows7-csm requires --winpe-from and UEFI firmware with CSM enabled')
    state=load(paths)
    if state is None:raise FlexBootError('Windows support was not enabled when this media was created')
    if verify(paths,full_hash=False):raise MediaStateError('Windows media is inconsistent; run verify')
    inspected=source.stat()
    facts=inspect_source(source,runner,borrowed_winpe=True) if winpe_from is not None else inspect_source(source,runner)
    donor_facts = donor_identity = donor_digest = None
    if winpe_from is not None:
        donor_identity = _identity(winpe_from)
        donor_facts = inspect_source(winpe_from, runner)
        donor_digest = sha256_file(winpe_from)
        if _identity(winpe_from) != donor_identity:
            raise FlexBootError('WinPE source changed during inspection')
    image_id=identifier(source.name)
    previous=next((r for r in state['images'] if r['id']==image_id),None)
    if previous and not replace:
        if allow_windows7_csm and not previous.get('requires_csm'):
            raise FlexBootError('--allow-windows7-csm is only for Windows 7 x64 installers')
        if winpe_from is not None and previous.get('winpe_source', {}).get('sha256') != donor_digest:
            raise FlexBootError('Different WinPE source selected; use --replace')
        if sha256_file(source)==previous['files']['image.iso']['sha256']:
            if verify(paths,full_hash=True):raise MediaStateError('Existing Windows resources are inconsistent')
            return previous,'skipped'
        raise FlexBootError('Different Windows ISO uses the installed name; use --replace')
    root=paths.windows/'windows'
    boot_facts = donor_facts or facts
    required=facts['size'] + max(3*boot_facts['entries']['sources/boot.wim'][1], facts['entries']['sources/boot.wim'][1])+128*1024**2
    if shutil.disk_usage(root).free<required:raise MediaStateError('Not enough Windows partition space for transactional preparation')
    stage=Path(tempfile.mkdtemp(prefix='.preparing-',dir=root))
    destination=root/image_id;backup=root/('.backup-'+uuid.uuid4().hex)
    old_state=state_path(paths).read_text();cfg=paths.grub_dir/'windows.cfg';old_menu=cfg.read_text()
    installed=False
    try:
        digest=copy_and_hash(source,stage/'image.iso')
        current=source.stat()
        if (inspected.st_dev,inspected.st_ino,inspected.st_size,inspected.st_mtime_ns,inspected.st_ctime_ns) != (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns,current.st_ctime_ns):
            raise FlexBootError('Source ISO changed after inspection')
        # Inspect the immutable copied bytes, not the potentially changing source.
        copied=inspect_source(stage/'image.iso',runner,borrowed_winpe=True) if winpe_from is not None else inspect_source(stage/'image.iso',runner)
        if copied['entries'] != facts['entries']:raise FlexBootError('Source ISO changed during inspection/copy')
        installer_build = None
        if winpe_from is not None:
            extract(stage/'image.iso', copied['entries']['sources/boot.wim'], stage/'installer.wim')
            installer_build = wim_info(stage/'installer.wim', runner, minimum_build=7600 if allow_windows7_csm else MIN_LEGACY_BUILD)
            (stage/'installer.wim').unlink()
            if allow_windows7_csm and installer_build not in (7600, 7601):
                raise FlexBootError('--allow-windows7-csm is only for Windows 7 x64 installers (7600/7601)')
            if installer_build >= MIN_WINPE_BUILD:
                raise FlexBootError('This installer has a supported native WinPE; omit --winpe-from')
            extract(stage/'image.iso', copied['entries']['sources/setup.exe'], stage/'source-setup.exe')
            pe_x64(stage/'source-setup.exe')
            (stage/'source-setup.exe').unlink()
        for name,dest in [('sources/boot.wim','boot.wim'),('boot/boot.sdi','boot.sdi'),('efi/boot/bootx64.efi','bootx64.efi')]:
            extract(winpe_from if winpe_from is not None else stage/'image.iso',boot_facts['entries'][name],stage/dest)
        pe_x64(stage/'bootx64.efi');build=wim_info(stage/'boot.wim',runner)
        if winpe_from is not None and build > MAX_DONOR_WINPE_BUILD:
            raise FlexBootError('Borrowed WinPE currently requires a Windows 10-era build (15063–19045)')
        runner.run(['wimlib-imagex', 'dir', stage/'boot.wim', '2', '--path=/sources/setup.exe'])
        atomic_text(stage/'startup.bat',startup(state['token'],image_id,build,source_setup=True) if winpe_from is not None else startup(state['token'],image_id,build))
        atomic_text(stage/'winpeshl.ini','[LaunchApps]\r\n%SYSTEMROOT%\\System32\\cmd.exe, /c %SYSTEMROOT%\\System32\\startup.bat\r\n')
        commands=''.join(f'add "{path}" /Windows/System32/{name}\n' for path,name in [(stage/'startup.bat','startup.bat'),(stage/'winpeshl.ini','winpeshl.ini'),(paths.grub_dir/'windows/flexboot-win.exe','flexboot-win.exe')])
        # WIM command-language paths are generated owned paths; reject quoting characters.
        if any(c in str(stage)+str(paths.efi) for c in '\"\n\r'):raise SafetyError('Unsupported quoting in mounted media path')
        runner.run(['wimlib-imagex','update',stage/'boot.wim','2'],input_text=commands,mutate=True)
        # Boot the same validated image into which the startup program was added.
        runner.run(['wimlib-imagex','info',stage/'boot.wim','2','--boot'],mutate=True)
        runner.run(['wimlib-imagex','verify',stage/'boot.wim'])
        cpio({'boot.sdi':stage/'boot.sdi','bootx64.efi':stage/'bootx64.efi'},stage/'initrd.cpio')
        for name in ('boot.sdi','bootx64.efi','startup.bat','winpeshl.ini'):(stage/name).unlink()
        files={p.name:{'size':p.stat().st_size,'sha256':sha256_file(p)} for p in stage.iterdir()}
        if files['image.iso']['sha256'] != digest:raise MediaStateError('Staged ISO integrity changed')
        record={'id':image_id,'filename':source.name,'size':facts['size'],'build':build,'files':files}
        if winpe_from is not None:
            if _identity(winpe_from) != donor_identity:
                raise FlexBootError('WinPE source changed during preparation')
            record['winpe_source'] = {'filename': winpe_from.name, 'sha256': donor_digest, 'installer_build': installer_build}
            if allow_windows7_csm:
                record['requires_csm'] = True
            state['schema_version'] = max(state['schema_version'], 3 if allow_windows7_csm else 2)
        if previous:os.replace(destination,backup)
        os.replace(stage,destination);installed=True
        state['images']=[r for r in state['images'] if r['id']!=image_id]+[record]
        publish(paths,state,runner)
    except BaseException:
        if installed:shutil.rmtree(destination)
        if backup.exists():os.replace(backup,destination)
        atomic_text(state_path(paths),old_state);atomic_text(cfg,old_menu)
        raise
    finally:
        if stage.exists():shutil.rmtree(stage)
    if backup.exists():shutil.rmtree(backup)
    return record,'replaced' if previous else 'added'


def remove(paths, filename: str, runner: Runner) -> None:
    state=load(paths)
    if state is None:raise FlexBootError('Windows backend is not installed')
    record=next((r for r in state['images'] if r['filename']==filename),None)
    if record is None:raise FlexBootError('Windows ISO is not installed')
    original=state_path(paths).read_text();cfg=paths.grub_dir/'windows.cfg';old_menu=cfg.read_text()
    source=paths.windows/'windows'/record['id'];quarantine=source.with_name('.removing-'+uuid.uuid4().hex)
    if source.is_symlink() or not source.is_dir():raise SafetyError('Invalid installed Windows directory')
    if any(p.name not in record['files'] for p in source.iterdir()):
        raise SafetyError('Refusing to remove untracked files from the Windows image directory')
    os.replace(source,quarantine)
    try:
        state['images']=[r for r in state['images'] if r['id']!=record['id']]
        publish(paths,state,runner)
    except BaseException:
        os.replace(quarantine,source);atomic_text(state_path(paths),original);atomic_text(cfg,old_menu)
        raise
    shutil.rmtree(quarantine)


def build_helper(destination: Path, compiler: str = 'x86_64-w64-mingw32-gcc') -> None:
    if destination.exists():raise FlexBootError('Refusing to overwrite a Windows helper')
    source=Path(__file__).with_name('assets')/'windows_mount.c'
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='flexboot-helper-',dir=destination.parent) as raw:
        output=Path(raw)/'flexboot-win.exe'
        Runner().run([compiler,'-Wall','-Wextra','-Werror','-Wno-cast-function-type','-Os','-municode','-static','-s',source,'-o',output])
        pe_x64(output)
        copy_and_hash(output,destination)
