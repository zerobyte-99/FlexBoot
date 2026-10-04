# Windows and other boot families

Windows installer ISO boot is currently unsupported. This document explains the
boot requirements and the available extension paths; it does not describe an
implemented Windows feature.

## Why a Linux-style entry is insufficient

GRUB can read an ISO stored on ext4, but that does not make the ISO available to
the next bootloader or operating system. Linux live profiles arrange rediscovery
through parameters such as `findiso=`. Windows requires a different mechanism.
Chainloading an EFI executable from GRUB's loopback device alone is not sufficient
evidence that Windows Boot Manager can load its BCD, boot image, and installation
payload after handoff. See the
[GRUB loopback documentation](https://www.gnu.org/software/grub/manual/grub/html_node/Loopback-booting.html).

Successful validation must reach Windows Setup and demonstrate access to the
intended installation image, not merely display Windows Boot Manager or WinPE.
Windows must also be able to read the source media; the existing ext4 data
partition cannot simply be assumed accessible to stock Windows PE.

## What Ventoy documents

Ventoy's normal boot path emulates an ISO as a CD-ROM. Its
[WIMBOOT mode](https://www.ventoy.net/en/doc_wimboot.html) is an alternative for
official Windows installer images and some WinPE images. These are boot mechanisms,
not filename-based GRUB templates.

The separate [WIM-file plugin](https://www.ventoy.net/en/plugin_wimboot.html)
requires an auxiliary image containing Windows boot files. That plugin should
not be confused with the Windows ISO WIMBOOT mode. FlexBoot will not redistribute
Microsoft boot files or introduce a Ventoy runtime dependency.

This comparison uses public documentation only. No Ventoy code, scripts, binaries,
or plugins have been copied, adapted, downloaded, or executed.

## Native installer partition

A conservative implementation can retain FlexBoot's FAT32 ESP and ext4 Linux ISO
storage, adding an explicitly requested FAT32 Windows installer partition.

- Extract installation files from the user's own x86-64 Windows ISO into that
  partition, including the native EFI loader, BCD, SDI, and `sources/boot.wim`.
- Locate the installer partition by its filesystem identity and chainload its
  Microsoft EFI loader from the FlexBoot menu.
- Split `sources/install.wim` into `install.swm`, `install2.swm`, and further parts
  when it exceeds FAT32's file-size limit. On Linux this would require an optional
  host-provided WIM utility, such as wimlib, with its output validated.
- Reject other oversized files unless a documented conversion is explicitly
  implemented; splitting WIM is not a generic solution for oversized ESD files.
- Initially use one installer per partition. Putting several installers in
  subdirectories without reviewing BCD and Setup path resolution is not a reliable
  multiboot solution.

Microsoft documents both FAT32 installer media and Setup's automatic use of split
WIM files in its [USB installation guide](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/install-windows-from-a-usb-flash-drive?view=windows-11).

This design needs an opt-in layout at media creation. Adding a partition to an
existing drive must not silently shrink or repartition it. The original two-partition
Linux layout remains valid. Firmware boot selection across multiple FAT partitions
and GRUB-to-Microsoft handoff must be tested, rather than assumed.

## Intact-ISO alternative

[iPXE wimboot](https://ipxe.org/wimboot) can boot a Windows PE WIM and is a separate,
open-source project. It is a candidate for an explicit, user-supplied runtime;
it is not built into FlexBoot or supplied by ordinary GRUB installation.

Its [architecture documentation](https://ipxe.org/appnote/wimboot_architecture)
explains the boot-file virtual filesystem. That boot mechanism does not by itself
prove that Setup can access the original ISO and its installation payload on the
USB. An intact-ISO design must also solve source storage, ISO mounting in WinPE,
and lifecycle after firmware handoff. It may require Windows-readable storage and
prepared WinPE startup logic, which expands the dependency and audit surface.

## Validation requirements

Before advertising Windows support:

- Recognize the actual installer structure and EFI architecture, including UDF
  images, rather than matching ISO names.
- Validate extraction paths, case-insensitive collisions, sizes, free space,
  metadata, and target identity before writing.
- Stage changes so a failed preparation cannot leave a boot menu claiming a valid
  installer. Track extracted files and split-image output for verification/removal.
- Fix the existing mount-cleanup and ancestry issues described in
  [Security](SECURITY.md#known-safety-issues) before broadening privileged writes.
- Test a user-supplied Windows ISO in disposable QEMU media with no physical disks
  exposed, then deliberately test representative hardware.
- Distinguish Windows installer, WinPE recovery, and installed-Windows/VHD boot.
  Secure Boot, ARM64, old BIOS-only media, and arbitrary customized ISOs require
  separate validation and must not inherit support claims.

Other operating systems also need individual profiles or native-loader backends.
BSD installers, hypervisors, and recovery tools should each be evaluated against
vendor boot mechanisms and actual images. A generic “boot any ISO” entry is not
a substitute for that work.
