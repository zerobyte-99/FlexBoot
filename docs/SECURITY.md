# Security model

## Known safety issues

This development version has unresolved issues and is not recommended for
production use:

- Failed unmount cleanup uses a recursively cleaned temporary directory, which
  could delete files on a filesystem that remains mounted.
- Failed raw-image creation can delete an existing image after refusing to
  overwrite it.
- System ancestry tracks one parent per device and can miss backing disks in
  shared LVM/RAID topologies.
- Manifest fields and writable-media identity require stronger validation before
  filesystem access or GRUB generation.

Passing unit tests do not establish physical-device safety. Fixes and regression
coverage for these cases are required before treating the software as stable.

## Protections implemented

The catastrophic failure FlexBoot is designed to prevent is erasing the wrong disk.

Before physical creation, FlexBoot resolves the path; requires an `lsblk` whole-disk node; rejects read-only, small, partition, or mounted targets; protects storage backing `/`, `/boot`, `/boot/efi`, and active swap; and requires USB transport by default. The removable bit alone is never accepted as evidence. LVM, dm-crypt, and similar ancestry is followed through the `lsblk` dependency tree.

An interactive operation displays the path, model, size, and serial, then requires the exact phrase `ERASE <path>`. An unattended operation requires both `--confirm-erase` and an exact identity from `--expect-identity`. Non-USB disks additionally require `--allow-non-usb`.

Immediately before `wipefs` and `sfdisk`, FlexBoot rediscovers the target. It aborts if the resolved path, major/minor, capacity, available serial, or by-id path changed. This reduces device-node reuse and selection/write race risk.

Automated image builds have a separate guard: after attaching a file, the builder accepts only a resolved `/dev/loop*` device. Tests never invoke a write path on physical storage.

ISO names containing path separators or control characters are rejected. External programs always receive argv arrays. ISO copies are hidden until flushed and atomically renamed. The manifest is operational state and is checked against files and generated configuration; it is never treated as a trusted authority.

Recorded SHA-256 values detect changes after installation. They do not authenticate an ISO or its publisher. FlexBoot does not download code, contact an update service, modify firmware NVRAM, or support Secure Boot in this release.

Residual risks include host utility bugs, malicious privileged host state, unusual storage topologies not represented accurately by `lsblk`, firmware-specific GRUB behavior, and a physical device changing in ways that preserve every collected identity field. Review `devices --verbose`, use dry-run, and keep valuable disks disconnected during first hardware validation.
