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

No Ventoy source, scripts, binaries, or behavior were used.
