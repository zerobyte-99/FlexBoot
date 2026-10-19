# Boot-time Linux ISO discovery and filesystem choices

FlexBoot 0.7.7 adds read-only discovery for selected Linux layouts. No FlexBoot
installation is needed on the computer used to copy those ISOs after the drive
has been prepared or upgraded once.

## Copy and boot

1. Use a drive created with 0.7.7, or upgrade its menu with
   `sudo flexboot sync /dev/sdX` using the updated application on Linux. This
   does not repartition or convert filesystems.
2. Copy a supported ISO directly into the lowercase `iso/` directory on the
   data partition. On Windows-enabled media, `iso/` on the NTFS Windows partition
   is also scanned; create that folder if it is absent on an older drive. Keep
   prepared Windows resources under `windows/` untouched.
3. Use names such as `ubuntu-server.iso`: ASCII letters, digits, dots,
   underscores, plus and minus signs. Extension matching is case-insensitive.
   Rename files containing spaces, quotes or other characters before copying.
4. Finish the copy, safely eject, and boot. Matching files appear after managed
   entries as `[Linux] filename.iso [discovered]`.

The next boot reflects added or removed unregistered files without updating a
manifest. Scanning is not recursive. It uses only the configured data filesystem
UUID and, when present, the configured Windows filesystem UUID. It does not
search every disk attached to the machine. Existing managed Linux paths are
excluded from discovery so their labels and ordering remain authoritative.

## Initial detection scope

| Layout | Required content |
|---|---|
| Classic Ubuntu/Casper | `/casper/vmlinuz` or `vmlinuz.efi`; a recognized canonical initrd; `/casper/filesystem.squashfs` |
| Ubuntu Server/Casper | Same kernel/initrd; `/casper/install-sources.yaml` and `/casper/ubuntu-server-minimal.squashfs` |
| Debian Live/Kali Live | `/live/vmlinuz`; `/live/initrd.img` or `/live/initrd`; `/live/filesystem.squashfs` |
| Clonezilla/GParted | Canonical Debian Live resources plus the product marker; dedicated boot arguments |

On exFAT, only the canonical Debian Live/Kali, Clonezilla and GParted discovery
paths are enabled. Casper-based discovery is excluded: Ubuntu Server 24.04.4
was observed failing to rediscover its ISO on exFAT. Use ext4 or the NTFS drop
folder for Casper images.

Kernels must pass GRUB's x86 Linux and x86-64 EFI image checks. Unknown images,
Windows installers and incomplete layouts receive no discovered entry. Parrot
is excluded by its volume label because its managed profile requires additional
vendor detection. Versioned-only Debian kernels, layered Ubuntu desktop roots,
Arch/SystemRescue vendor submenus, Fedora, Grml, Gentoo and Slax need the existing
host-side profiles instead. Discovery executes no GRUB configuration from an ISO.
Boot arguments are shared with the corresponding host profiles.

These are structural checks, not a full ISO integrity check or a guarantee for
all releases. A truncated copy may still contain recognizable resources. Always
finish copying before ejecting. [Measured results](TESTING-0.7.7.md) distinguish
synthetic menu tests from actual Linux userspace boots.

## Filesystem choices

| Storage | Windows copying | Current use |
|---|---|---|
| ext4 | Requires additional filesystem software | Default Linux data partition; existing managed aliases support filenames with spaces |
| exFAT | Native on modern Windows | Experimental Linux data partition selected at creation; the image's initramfs must support it |
| NTFS | Native on Windows | Existing optional Windows partition also accepts Linux files under `iso/`; Linux initramfs support is still required |

For a new exFAT drive, first inspect the target with `flexboot devices` and
`flexboot create /dev/sdX --data-filesystem exfat --dry-run`. Actual creation uses:

```bash
flexboot doctor --for create-exfat
sudo flexboot create /dev/sdX --data-filesystem exfat
```

Creation erases the selected drive and retains all normal identity/confirmation
protections. Dependencies include `mkfs.exfat` (usually `exfatprogs`) and the
host GRUB exFAT module. A disposable image uses the same builder:

```bash
sudo flexboot image create ./out/exfat.img --size 8G --data-filesystem exfat
```

`--data-filesystem ext4` explicitly selects the default. The optional Windows
installer partition remains NTFS even when Linux storage is exFAT. There is no
in-place conversion or unified exFAT Windows installer backend in this release.
Managed imports on exFAT are limited to the Debian Live, Clonezilla and GParted
profiles too. Other profiles are rejected before copying. Even within that
subset, older live images may lack exFAT in their initramfs. Ubuntu Server
24.04.4 failed in the measured test, so broader testing and a capability-aware
Casper solution are required before changing the default.

ExFAT cannot store the symbolic-link aliases used for filenames with spaces;
managed `add`/`sync` reject such ISO names before publishing changes. Custom
menu labels may still contain spaces. Discovery also requires simple names on
ext4 and NTFS because it cannot create aliases while booting read-only.

## Managed state and verification

Discovered entries are not persisted, hashed or editable through `menu label`
and `menu order`; those commands manage registered entries. Run `sync` on Linux
to register compatible files on the Linux data partition, or use `add` with a
source file in the normal workflow. `sync` does not import files from the NTFS
drop folder. Keep using `windows add` for Windows installers.

`verify` checks managed content: it reports untracked ISO files in the Linux
partition until `sync` registers them. Linux drop files on NTFS are outside the
Windows resource inventory and are not hashed by that verification. A passing
managed verification does not verify those dropped files. Discovery does not
change manifest hashes or accept modifications to existing managed images.
