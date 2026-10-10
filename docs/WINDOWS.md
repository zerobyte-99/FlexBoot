# Optional Windows installers

FlexBoot has an **experimental, opt-in x86-64 Windows installer backend**.
Linux ISO files and Windows ISO files share one GRUB menu. Windows images remain
intact on a separate NTFS partition; their prepared boot resources come from the
selected ISO. No Windows image, Microsoft boot binary, or third-party loader is
shipped in this repository.

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

## Validation and limits

See [extended loader experiments](WINDOWS-EXPERIMENTS.md) for measured results.
Validation includes real Windows 10/11 WinPE, exact ISO mounting, multiple Windows
entries, Windows installation on disposable virtual disks, Linux userspace on
Windows-enabled media, dependency and integrity failures, transactional rollback,
and rejection of duplicate source markers. Physical USB compatibility remains
unverified.

Current accepted sources are ISO9660/UDF installers with an x64 Setup boot image
at WIM index 2, WinPE build >=19041, and `sources/install.wim`. ESD, split WIM,
ARM64, BIOS, Secure Boot, Windows Server, older PE, arbitrary custom WinPE, and
all firmware variants are not claimed as supported. Boot WIM size is limited to
2 GiB. Detection by contents is an eligibility check, not a guarantee that every
new Windows release will install on every machine.
