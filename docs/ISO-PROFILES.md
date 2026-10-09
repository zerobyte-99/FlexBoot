# ISO profiles

FlexBoot matches filesystem structure, volume metadata, and bounded boot configuration text. It never selects a profile from the host filename. A match returns a distribution-neutral `BootPlan`; the GRUB backend renders either a Linux kernel/initrd command or a vendor `loopback.cfg` delegation.

## Supported layouts

- **Ubuntu/casper:** `/casper/vmlinuz` or `vmlinuz.efi`, a known casper initrd (including `.img` and `.xz`), and `filesystem.squashfs`. A single `*.live.squashfs` leaf with every dotted parent layer also matches and receives `layerfs-path=`. Manifest/size files alone do not qualify. Ubuntu Server keeps its inspected `iso-scan/filename=` and `---` form.
- **Debian Live / Kali Live:** a matching `/live/vmlinuz[SUFFIX]` and `/live/initrd.img[SUFFIX]` or `initrd[SUFFIX]`, plus `/live/filesystem.squashfs`, booted with live-boot `findiso=`. A canonical unversioned pair takes priority; otherwise multiple complete versioned pairs are rejected.
- **SystemRescue:** its `/sysresccd/boot/x86_64` kernel resources and `/boot/grub/loopback.cfg`. FlexBoot delegates to the vendor loopback menu and removes GRUB's TPM module as documented by SystemRescue.
- **Arch Linux archiso:** `/arch/x86_64/airootfs.sfs`, an archiso kernel, and `/boot/grub/loopback.cfg`. FlexBoot delegates to the ISO's loopback menu.
- **Rescuezilla:** a casper live layout plus the Rescuezilla volume or boot-config marker. Its boot plan includes the vendor-documented `toram` behavior.
- **Clonezilla Live:** the root `Clonezilla-Live-Version` marker plus a complete Debian Live layout. It receives Clonezilla's live parameters rather than the generic Debian menu.
- **Fedora Live:** `/LiveOS/squashfs.img`, a safe Fedora volume label, and a recognized dracut kernel/initrd layout. Both the current `/boot/x86_64/loader` and older pxeboot/isolinux locations are recognized.
- **Grml amd64:** a single matching `grml-{small,full,medium}-amd64` or older `grml64-*` live payload, corresponding `/boot/<flavour>/vmlinuz` and `initrd.img`, and a safe matching `/conf/bootid.txt`. Uses `findiso=`, `live-media-path=`, and `bootid=` directly. Its vendor GRUB configuration is not sourced.
- **Gentoo amd64 Live:** `/boot/gentoo`, `gentoo.igz`, `/image.squashfs`, `/livecd`, a safe Gentoo amd64 label, and a real vendor Linux command with matching dracut root and squashfs arguments. Uses dracut `iso-scan/filename=`. Legacy genkernel layouts do not qualify.

Installer-only Kali images, Fedora netinstall images, generic casper images that only resemble Rescuezilla, and incomplete layouts remain unsupported.

Use `flexboot profiles` to list families and `flexboot iso inspect FILE.iso --json`
to diagnose a source. Inspection is read-only and returns exit status 2 for an
unsupported layout. Installing xorriso/isoinfo preserves the same bounded volume,
allowlisted configuration text, and kernel-header metadata as the built-in reader.
External tools supply richer filenames where available; the built-in reader does
not implement all Rock Ridge or UDF features. A known 32-bit Linux boot-protocol
header rejects a direct Linux entry; unknown headers do not establish architecture.

The GRUB renderer quotes loopback paths and ISO-path argument substitutions.
Because some vendor initramfs parsers still split quoted kernel arguments on
spaces, filenames outside the simple ASCII set use deterministic symlinks under
`.flexboot/boot-isos/`. The visible menu and manifest retain the original name,
and the original ISO remains under `/iso/`. Links point only to the matching ISO,
are checked during verification, and are created before menu publication with
rollback on failure. Conflicting files/links and symlinked alias directories are
rejected. `inspect --json` reports each `boot_iso_path` for auditing.

QEMU login was verified for Grml small 2026.09 amd64 and Gentoo minimal
20260913T163055Z, both stored under filenames containing spaces through checked
boot aliases.
Other Grml flavours, layered Casper releases, and physical hardware still need
validation. Alpine remains excluded: its documented GRUB loopback procedure needs
manual recovery to rediscover the ISO. No generic entry is added for it.

After updating the installed FlexBoot application, `sudo flexboot sync /dev/sdX`
reinspects existing ISO files and refreshes their stored boot plans. Review the
target first; sync performs media writes and checks recorded content integrity.

## Adding a family

1. Create a module in `flexboot/profiles/` with a unique `profile_id` and description.
2. Implement `detect(ISOInspection)`. Require product-specific evidence and every boot resource.
3. Return a `BootPlan("linux", ...)` or `BootPlan("loopback-config", ...)`.
4. Register specific profiles before generic parent families in `profiles/__init__.py`.
5. Add positive, incomplete-layout, collision, unsafe-metadata, GRUB-rendering, and manifest tests.
6. Record primary documentation in `RESEARCH.md`.
7. Inspect a real vendor image and boot it under QEMU and representative hardware before describing it as hardware validated.

Filename matching and copied arguments from untrusted ISO text are prohibited. Text may establish a product marker, but generated arguments remain profile-controlled. A broad guess is worse than an unsupported diagnostic.
