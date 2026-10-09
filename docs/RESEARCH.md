# Research

Primary and project-maintained sources reviewed on 2026-09-30:

- [GNU GRUB 2.14 manual: installing with grub-install](https://www.gnu.org/software/grub/manual/grub/html_node/Installing-GRUB-using-grub_002dinstall.html) documents that removable EFI installation requires `--removable` with explicit EFI and boot directories.
- [GNU GRUB 2.14 manual](https://www.gnu.org/software/grub/manual/grub/grub.html) documents loopback boot, UUID search, direct configuration, and warns against depending on disk ordering.
- [lsblk(8)](https://man7.org/linux/man-pages/man8/lsblk.8.html) says scripts should explicitly select output columns, explains JSON dependency trees and `MOUNTPOINTS`, and recommends `udevadm settle` after device changes.
- [findmnt(8)](https://man7.org/linux/man-pages/man8/findmnt.8.html) documents `--target` and explicit output columns used to identify mounted system storage.
- [Debian Live manual](https://live-team.pages.debian.net/live-manual/html/live-manual.en.html) describes `/live/vmlinuz`, `/live/initrd.img`, `filesystem.squashfs`, `boot=live`, and QEMU testing.
- [Debian live-boot(7)](https://manpages.debian.org/bookworm/live-boot-doc/live-boot.7.en.html) documents live-boot parameters and the `findiso=/PATH/TO/IMAGE` mechanism.
- [Ubuntu LiveISO documentation](https://help.ubuntu.com/community/LiveISO) documents GRUB loopback with casper and `iso-scan/filename=`. This is community-maintained Ubuntu documentation; real-release boot validation remains required.
- The supplied Ubuntu Server 26.04.1 image's own `/boot/grub/loopback.cfg` was inspected read-only. It uses `/casper/vmlinuz`, `/casper/initrd`, `iso-scan/filename=${iso_path}`, and `---`; its casper squashfs files are named `ubuntu-server-minimal*.squashfs`.
- [Kali image selection](https://www.kali.org/docs/introduction/what-image-to-download/) distinguishes live-capable images from installer images. FlexBoot therefore recognizes Kali only through Debian Live structure.
- [Kali official image downloads](https://www.kali.org/docs/introduction/download-official-kali-linux-images/) identifies the supported live ISO class and architecture scope.
- [Kali's official GRUB theme](https://gitlab.com/kalilinux/packages/kali-themes/-/raw/kali/master/share/grub/themes/kali/theme.txt) uses GRUB's standard font, relative image paths, a frameless `boot_menu`, 36-pixel menu rows, zero-width icons, and a nine-slice selected-item image. FlexBoot follows this conservative structure after hardware testing exposed unreliable custom-font fallback behavior.
- [GNU GRUB theme documentation](https://www.gnu.org/software/grub/manual/grub/html_node/Theme-file-format.html) defines the graphical menu components and nine-slice pixmap convention. GRUB's standard theme behavior resolves the relative asset names used by Kali from the theme directory.
- [SystemRescue disk installation](https://www.system-rescue.org/manual/Installing_SystemRescue_on_the_disk/) documents intact-ISO GRUB boot through `/boot/grub/loopback.cfg`, including `iso_path` export and removal of the TPM module.
- [ArchWiki multiboot USB](https://wiki.archlinux.org/title/Multiboot_USB_drive) documents exporting `iso_path` and delegating Arch installation media to `/boot/grub/loopback.cfg`.
- [Clonezilla live-boot parameters](https://clonezilla.org/clonezilla-live/boot-parameters/live-boot.php) documents Debian live-boot and `findiso=`. Clonezilla source also supplies the root `Clonezilla-Live-Version` product marker.
- [Rescuezilla rescue partition instructions](https://github.com/rescuezilla/rescuezilla/wiki/Installing-Rescuezilla-as-a-rescue-partition) document casper loopback boot, `iso-scan/filename=`, and the required `toram` argument.
- [Dracut command-line documentation](https://github.com/dracut-ng/dracut/blob/main/man/dracut.cmdline.7.adoc) documents Fedora Live ISO loopback use with `iso-scan/filename=`, `root=live:LABEL=`, and `rd.live.image`. Fedora 44's real ISO was inspected and uses `/boot/x86_64/loader/linux`, `/boot/x86_64/loader/initrd`, and `root=live:CDLABEL=Fedora-WS-Live-44`.

## Real image inspection, 2026-10-01

- Fedora Workstation Live 44-1.7: label `Fedora-WS-Live-44`; required LiveOS and loader files present; SHA-256 `1620295f6a00c27c3208f0c00b8ece4eab1ec69b9002152d97488bf26a426ddf` matches the signed Fedora checksum value.
- Clonezilla Live 3.3.3-37 amd64: product marker and complete `/live` layout present; SHA-256 `3079458d926a37d3533e5d5caeb61b6e49c2dc69e2c97e0332ef37986bb3414f` matches the publisher checksum.
- Rescuezilla 2.6.2 Resolute: label `Rescuezilla` and complete casper layout present; SHA-256 `20dfdad31d3da56b8dd3978159721f19071916f65e123003a850fdecec85ae3f` matches the GitHub release asset digest.

## Windows boot mechanisms

- [Microsoft: installing Windows from a USB flash drive](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/install-windows-from-a-usb-flash-drive?view=windows-11) documents native installer files, FAT32, and splitting oversized WIM files for Windows Setup.
- [GNU GRUB: loopback booting](https://www.gnu.org/software/grub/manual/grub/html_node/Loopback-booting.html) explains that reading an image in GRUB does not arrange the operating system's own access to that image.
- [iPXE wimboot](https://ipxe.org/wimboot) and its [architecture](https://ipxe.org/appnote/wimboot_architecture) document WinPE WIM boot and the virtual boot-file filesystem.
- At the user's request, [Ventoy's Windows ISO WIMBOOT mode](https://www.ventoy.net/en/doc_wimboot.html) and [separate WIM plugin](https://www.ventoy.net/en/plugin_wimboot.html) were compared at the documentation level. The former describes normal ISO CD-ROM emulation and an alternative boot mode; the latter uses an auxiliary image containing Microsoft boot files.

See [Windows and other boot families](WINDOWS.md) for the implications for FlexBoot.
No Ventoy source, scripts, binaries, or plugins have been copied, adapted,
downloaded, or executed. FlexBoot has no Ventoy runtime dependency.

## Compatibility expansion, 2026-10-09

- [Grml cheatcodes](https://grml.org/cheatcodes/) document `findiso=`, the required
  `live-media-path=`, and the matching boot ID. Grml's
  [loopback configuration](https://github.com/grml/grml-live/blob/master/config/media-files/GRMLBASE/boot/grub/loopback.cfg)
  sources its main configuration using GRUB's prefix. FlexBoot instead uses its
  own direct Linux entry with Grml's documented parameters.
- [Gentoo installation alternatives](https://wiki.gentoo.org/wiki/Installation_alternatives)
  describe legacy genkernel ISO booting. The current official amd64 minimal image
  instead contains dracut and `iso-scan` in its initramfs, and declares a CDLABEL
  live root plus `rd.live.squashimg=image.squashfs` in its own GRUB configuration.
  Only that current mechanism is implemented.
- [Casper's manual](https://manpages.ubuntu.com/manpages/focal/man7/casper.7.html)
  documents `layerfs-path=`. Its
  [source](https://git.launchpad.net/casper/tree/scripts/casper) derives dotted
  parent layers and aborts when one is missing; detection now requires the full
  hierarchy rather than merely a manifest or leaf file.
- [Linux x86 boot protocol](https://docs.kernel.org/arch/x86/boot.html)
  defines `HdrS`, protocol version, and `xloadflags` bit 0. Bounded header reads
  reject known 32-bit kernels without treating unrecognized headers as verified
  architecture.
- [Alpine's direct ISO boot instructions](https://wiki.alpinelinux.org/wiki/Directly_booting_an_ISO_file)
  describe an initramfs recovery path with manual ISO mounting. Its current
  [initramfs source](https://gitlab.alpinelinux.org/alpine/mkinitfs/-/blob/master/initramfs-init.in)
  does not provide a demonstrated equivalent to Debian's `findiso=` mechanism.
  Alpine support is deferred.
- Windows references above were revisited. Microsoft's
  [Setup command-line reference](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/windows-setup-command-line-options?view=windows-11#installfrom)
  documents WIM and first-part SWM selection. iPXE's
  [wimboot injected-files interface](https://ipxe.org/wimboot#injected_files)
  offers a possible per-image WinPE startup mechanism; local GRUB/UEFI handoff
  was an untested design boundary before the lab comparison recorded below.
  See `WINDOWS-EXPERIMENTS.md` for the subsequent results.

### Real ISO boot evidence

Grml small 2026.09 amd64 reached `grml login:` and Gentoo minimal
20260913T163055Z reached `livecd login:` under QEMU/OVMF software emulation.
Both also reached login with spaced filenames through checked boot aliases.
Each intact ISO was stored on disposable ext4 media. No physical disks, host
mounts, networking, or virtual optical drives were used. The host's standalone
GRUB loader ran production generated entries with serial-console instrumentation
and automated menu selection. This validates ISO rediscovery into userspace, not physical
hardware or the full GPT/grub-install builder.

A real Grml image with spaces in its filename exposed two distinct failures:
unquoted GRUB variable expansion split the loopback path, and Grml's initramfs
`Cmdline_old` split quoted kernel arguments again. Quoting the renderer fixes the
first issue; checked boot-path symlinks avoid the second without changing the
vendor initramfs or duplicating ISO data. The reusable helper waits for an explicit
GRUB readiness marker before sending Enter; a failed test preserves logs and
screenshots and returns a failure status.

Grml's SHA-256 was
`81062142e320b158dcac541506e74e1b4d77f409e72bf7ef52820fc881d72c33`, matching
the [publisher's checksum list](https://ftp-master.grml.org/SHA256SUMS-2026.09).
Gentoo's SHA-512 was
`7bc150d92d330d90135683e8b430e03fde7f7284e8d868923ebf66b0f94c2b77a0ae9db51696e51704ed0a05769c31939bf26cf7af96a3829608ab2479519047`,
matching its [official DIGESTS file](https://distfiles.gentoo.org/releases/amd64/autobuilds/20260913T163055Z/install-amd64-minimal-20260913T163055Z.iso.DIGESTS).
These were publisher checksum comparisons over HTTPS; OpenPGP signatures were
not verified during this pass.

## Windows loader lab, 2026-10-09

- [NTloader](https://github.com/grub4dos/ntloader) and its
  [menu guide](https://github.com/grub4dos/ntloader/blob/master/docs/menu.md)
  document WIM selection through a stock-GRUB handoff and boot volume identity.
- Microsoft's [OpenVirtualDisk](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-openvirtualdisk)
  and [AttachVirtualDisk](https://learn.microsoft.com/en-us/windows/win32/api/virtdisk/nf-virtdisk-attachvirtualdisk)
  define the native ISO API tested in stock Windows 10/11 WinPE.
- [Winpeshl.ini](https://learn.microsoft.com/en-us/windows-hardware/manufacture/desktop/winpeshlini-reference-launching-an-app-when-winpe-starts?view=windows-11)
  defines startup application injection into a prepared WinPE image.
- [ImDisk](https://github.com/LTRData/ImDisk), the official signed 2.1.2 package,
  and [GRUB2 File Manager](https://github.com/a1ive/grub2-filemanager) were compared
  in disposable guests. iPXE wimboot was built from source and its direct
  stock-GRUB handoff was attempted; the documented iPXE network route was not.

See [actual results, pinned revisions and limitations](WINDOWS-EXPERIMENTS.md).
NTloader plus native ISO attachment is preferred for a future optional backend.
No Ventoy dependency was introduced and no downloaded runtime is shipped.
