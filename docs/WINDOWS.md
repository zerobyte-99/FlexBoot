# Optional Windows installers

FlexBoot has an **experimental, opt-in x86-64 Windows installer backend**.
Linux ISO files and Windows ISO files share one GRUB menu. Windows images remain
intact on a separate NTFS partition; their prepared boot resources come from the
selected ISO. No Windows image, Microsoft boot binary, or third-party loader is
shipped in this repository.

The [14-image USB test report](TESTING-0.7.5.md) covers the Server 2012 R2,
2016, 2019, 2022 and 2025 collection. Server 2025 reached native Setup and
detected a blank destination; a completed installation is not yet verified.

## Firmware and layout requirements

The default Linux layout remains GPT, a 512 MiB FAT32 EFI System Partition, and
ext4 data storage. Windows creation requires **both** `--windows-size` and
`--windows-boot-layout basic-fat`. Its layout is:

| Partition | Filesystem | GPT role | Contents |
|---|---|---|---|
| 1 | FAT32, 512 MiB | Microsoft Basic Data | Removable UEFI GRUB, theme, local Windows runtime |
| 2 | ext4 | Linux filesystem | Linux ISOs and FlexBoot metadata |
| 3 | NTFS, requested reserve | Microsoft Basic Data | Intact Windows ISOs and per-image prepared resources |

The Windows boot partition deliberately uses Basic Data rather than the ESP GUID.
An additional USB ESP caused Windows Setup to fail when creating the destination
ESP in extended tests. The Basic Data layout avoids that extra system-partition
candidate, while retaining `EFI/BOOT/BOOTX64.EFI` and host-provided GRUB.

**Your firmware must support booting a FAT partition without the ESP GUID.**
OVMF does; support is optional in the [UEFI specification, section 13.3.3](https://uefi.org/specs/UEFI/2.11/13_Protocols_Media_Access.html).
A successful virtual-machine test does not establish support on your USB hardware.
Secure Boot must remain disabled. Windows 11 still requires suitable hardware
and firmware; FlexBoot supplies no requirement bypass.

An existing Linux-only drive cannot acquire Windows storage through `add`.
Creation erases the selected target with the usual safeguards; FlexBoot never
silently shrinks or repartitions existing media.

## Host requirements and local runtime

Run `flexboot doctor --for windows`. In addition to normal creation tools, this
backend needs `7z`, `wimlib-imagex`, `mkfs.ntfs`, `ntfs-3g`, and host GRUB >= 2.12
with its x86-64 EFI NTFS module. Explicit dependency installation is available:

```bash
sudo flexboot install --for windows --dependencies
```

Supply an audited local x86-64 hybrid [NTloader](https://github.com/grub4dos/ntloader)
and its expected SHA-256 from trusted provenance. The tested runtime was v3.0.7,
revision `744a6108d32ea47df95e9fd1ab42884525685985`. FlexBoot checks the supplied
hash and handoff headers, and copies the local executable. It never downloads a
loader or its auxiliary archive. The NTloader [stock-GRUB menu guide](https://github.com/grub4dos/ntloader/blob/main/docs/menu.md)
describes the handoff.

Build FlexBoot's small ISO-mount helper locally with an installed x86-64 MinGW
compiler. Its source ships as `flexboot/assets/windows_mount.c`:

```bash
flexboot windows build-helper ./flexboot-win.exe
# A non-default compiler can be supplied with --cc /path/to/compiler
```

A locally calculated checksum tracks integrity; it does not establish a binary's
or an ISO's authenticity. Audit runtime provenance and supply trusted ISOs.

## Safe image-first workflow

Set `NTLOADER_SHA256` to the expected 64-character digest of your local loader.
For two large Windows ISOs, a 32 GiB reserve leaves useful staging space:

```bash
sudo flexboot image create ./out/windows.img --size 40G \
  --windows-size 32G --windows-boot-layout basic-fat \
  --ntloader ./ntloader --ntloader-sha256 "$NTLOADER_SHA256" \
  --windows-helper ./flexboot-win.exe --dry-run

sudo flexboot image create ./out/windows.img --size 40G \
  --windows-size 32G --windows-boot-layout basic-fat \
  --ntloader ./ntloader --ntloader-sha256 "$NTLOADER_SHA256" \
  --windows-helper ./flexboot-win.exe

sudo flexboot windows add ./out/windows.img windows10.iso windows11.iso
sudo flexboot add ./out/windows.img "Grml with spaces.iso"
sudo flexboot status ./out/windows.img
sudo flexboot verify ./out/windows.img
```

From a checkout, substitute `python3 -m flexboot` for `flexboot`. The same creation
options work with `create /dev/sdX`; use `devices`, inspect the identity, and preview
with `--dry-run` before a human chooses a physical target.

Ordinary `list`, `status`, `inspect`, `verify`, and `sync` include Windows state.
Windows images have their own add/remove commands:

```bash
sudo flexboot windows add /dev/sdX "Windows 11.iso"
sudo flexboot windows add /dev/sdX "Windows 11.iso" --replace
sudo flexboot windows remove /dev/sdX "Windows 11.iso"
```

Adding or replacing needs space for staged copies and WIM work files. Failed
preparation does not publish an installed image; an existing entry is retained
when replacement fails. `sync` can repair stale generated menus but refuses to
bless changed prepared resources.

## Boot and source selection

Each menu entry selects that image's prepared boot-index-2 WIM by filesystem UUID
and a generated hexadecimal ID. Preparation validates x64 WinPE and its native
Setup program, inserts a startup script and the independently written helper,
and verifies the resulting WIM. The source ISO is unchanged.

WinPE initializes devices and requires exactly one accessible volume containing
its installation marker. The helper attaches only the selected ISO read-only,
uses Microsoft's [physical-device query](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-getvirtualdiskphysicalpath)
and [storage-device numbers](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_storage_get_device_number)
to identify that attachment's drive letter, and rejects ambiguity. DISM checks the
selected installation WIM before native WinPE Setup receives its explicit
`/InstallFrom:` path. The startup layer does not scan other ISOs or choose an
installation destination.

Select the destination in Microsoft's Setup UI. After its first installation
reboot, boot the destination's Windows Boot Manager; continuing to boot the USB
returns to the FlexBoot menu. Startup diagnostics are in
`X:\Windows\Temp\flexboot.log` and Microsoft's `X:\Windows\Panther` logs.

## Older installers with a newer WinPE (experimental)

The optional `--winpe-from` argument supplies the temporary boot environment
from a local Windows 10 ISO while retaining the older installer ISO intact:

```bash
sudo flexboot windows add ./out/windows.img server2012r2.iso \
  --winpe-from windows10.iso --dry-run
sudo flexboot windows add ./out/windows.img server2012r2.iso \
  --winpe-from windows10.iso
```

The donor must provide x64 Setup WinPE at WIM index 2, build 15063–19045.
The older source must provide an x64 index-2 boot image, build 9200–15062, and a native
`sources/setup.exe`, together with `sources/install.wim`. Disk images renamed
as `.iso` remain rejected. The source ISO may omit the USB EFI fallback file
because boot resources come from the donor.

Preparation checks the older Setup executable's architecture, records the donor
filename and SHA-256 plus the older installer build, and hashes the prepared
resources. The complete donor ISO is not stored on the USB. It is needed only
during preparation; the older ISO and its prepared boot resources suffice at boot.

The borrowed WinPE initializes storage and mounts the selected older ISO. It
launches that ISO's own `sources/setup.exe` with its explicit installation WIM.
There is no automatic fallback to the donor's installer or another ISO.
Destination selection remains in Microsoft's Setup UI.

Changing the donor for an existing image requires `--replace`. A failed
replacement retains the installed resources and menu. Dry-run checks source
layouts only; it does not extract WIMs, validate their builds, or check Setup
compatibility. Actual preparation performs those checks.

Using this mode upgrades Windows metadata to schema 2. FlexBoot 0.7.2 and older
cannot manage that media; use the updated application for subsequent operations.
No partition-layout migration is performed.

See [older Windows experiments](TESTING-0.7.3.md) and the
[Server 2012 / Windows 7 follow-up](TESTING-0.7.4.md) for measured installation
and boot results. Eligibility alone does not establish support for every release.

## Windows 7 x64 with CSM (experimental)

Windows 7 remains rejected by default. To prepare an x64 WIM installer with
index-2 boot build 7600 or 7601, explicitly opt in and supply a Windows 10 donor:

```bash
sudo flexboot windows add ./out/windows.img windows7.iso \
  --winpe-from windows10.iso --allow-windows7-csm
```

The target must boot in **UEFI mode with CSM enabled and Secure Boot off**.
FlexBoot cannot check another machine's firmware during preparation. This does
not add BIOS boot support, and FlexBoot does not supply a CSM or modify firmware.
The newer WinPE initializes the installer; the installed Windows 7 system still
needs its own compatible storage, graphics and USB drivers.

The tested image is a private ISO derived from supplied Windows 7 Enterprise
x64 RTM installer files, with a Windows 10 1803 donor. It completed installation
and reached account setup on a GPT destination in a fresh CSM-enabled QEMU VM
without installer media. SP1 eligibility is implemented but SP1 and native
hardware installation have not been tested. Supply a real ISO9660/UDF installer;
renaming a raw USB disk image to `.iso` does not convert it.

These records upgrade Windows metadata to schema 3, require FlexBoot 0.7.4 or
newer, and preserve their firmware requirement across custom labels and menu
ordering. The boot menu always appends `[CSM required]`. Adding other installers
does not downgrade the schema. Replacing a Windows 7 entry requires the explicit
flag again. No runtime components are downloaded or bundled by this option.

## Validation and limits

See [extended loader experiments](WINDOWS-EXPERIMENTS.md) for measured results.
Validation includes real Windows 10/11 WinPE, exact ISO mounting, multiple Windows
entries, Windows installation on disposable virtual disks, Linux userspace on
Windows-enabled media, dependency and integrity failures, transactional rollback,
and rejection of duplicate source markers. The user also reported a native
hardware boot of the supplied Windows 10 image; this was not a full hardware
installation test. See the [compatibility expansion](TESTING-0.7.2.md) for the
additional client and Server tests.

Current accepted sources are ISO9660/UDF installers with an x64 Setup boot image
at WIM index 2, WinPE build >=15063 (Windows 10 version 1703), and
`sources/install.wim`. This minimum follows Microsoft's requirement for
[multiple partitions on removable USB media](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpe--use-a-single-usb-key-for-winpe-and-a-wim-file---wim?view=windows-11).
Older native WinPE exposes only the first boot partition in this layout, so it
cannot find the NTFS source. The default path excludes Windows 7/8/8.1 and Server
2016 or earlier PE. The explicit borrowed-WinPE mode above is a separate
experimental path; consult its test matrix before use.
ESD, split WIM, ARM64, BIOS, Secure Boot, arbitrary custom WinPE, and all firmware
variants are not claimed as supported. Boot WIM size is limited to
2 GiB. Detection by contents is an eligibility check, not a guarantee that every
new Windows release will install on every machine.
