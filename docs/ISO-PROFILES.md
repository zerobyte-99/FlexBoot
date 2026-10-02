# ISO profiles

FlexBoot matches filesystem structure, volume metadata, and bounded boot configuration text. It never selects a profile from the host filename. A match returns a distribution-neutral `BootPlan`; the GRUB backend renders either a Linux kernel/initrd command or a vendor `loopback.cfg` delegation.

## Supported layouts

- **Ubuntu/casper:** `/casper/vmlinuz`, a known casper initrd, and a casper root filesystem. Ubuntu Server uses its inspected `iso-scan/filename=` and `---` form.
- **Debian Live / Kali Live:** `/live/vmlinuz*`, `/live/initrd*`, and `/live/filesystem.squashfs`, booted with live-boot `findiso=`.
- **SystemRescue:** its `/sysresccd/boot/x86_64` kernel resources and `/boot/grub/loopback.cfg`. FlexBoot delegates to the vendor loopback menu and removes GRUB's TPM module as documented by SystemRescue.
- **Arch Linux archiso:** `/arch/x86_64/airootfs.sfs`, an archiso kernel, and `/boot/grub/loopback.cfg`. FlexBoot delegates to the ISO's loopback menu.
- **Rescuezilla:** a casper live layout plus the Rescuezilla volume or boot-config marker. Its boot plan includes the vendor-documented `toram` behavior.
- **Clonezilla Live:** the root `Clonezilla-Live-Version` marker plus a complete Debian Live layout. It receives Clonezilla's live parameters rather than the generic Debian menu.
- **Fedora Live:** `/LiveOS/squashfs.img`, a safe Fedora volume label, and a recognized dracut kernel/initrd layout. Both the current `/boot/x86_64/loader` and older pxeboot/isolinux locations are recognized.

Installer-only Kali images, Fedora netinstall images, generic casper images that only resemble Rescuezilla, and incomplete layouts remain unsupported.

## Adding a family

1. Create a module in `flexboot/profiles/` with a unique `profile_id` and description.
2. Implement `detect(ISOInspection)`. Require product-specific evidence and every boot resource.
3. Return a `BootPlan("linux", ...)` or `BootPlan("loopback-config", ...)`.
4. Register specific profiles before generic parent families in `profiles/__init__.py`.
5. Add positive, incomplete-layout, collision, unsafe-metadata, GRUB-rendering, and manifest tests.
6. Record primary documentation in `RESEARCH.md`.
7. Inspect a real vendor image and boot it under QEMU and representative hardware before describing it as hardware validated.

Filename matching and copied arguments from untrusted ISO text are prohibited. Text may establish a product marker, but generated arguments remain profile-controlled. A broad guess is worse than an unsupported diagnostic.
