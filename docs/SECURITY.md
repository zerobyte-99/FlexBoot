# Security model

## Validation limits

Regression tests cover failed-unmount preservation, existing-image refusal,
multi-parent ancestry, transactional replacement, space checks, and boot-metadata
validation. Automated tests use disposable files and mocked devices. They do not
establish physical-device safety or cover every storage topology, firmware, or
failure timing. Representative hardware validation is still required.

## Protections implemented

The catastrophic failure FlexBoot is designed to prevent is erasing the wrong disk.

Before physical creation, FlexBoot resolves the path; requires an `lsblk` whole-disk node; rejects read-only, small, partition, or mounted targets; protects storage backing `/`, `/boot`, `/boot/efi`, and active swap; and requires USB transport by default. The removable bit alone is never accepted as evidence. LVM, dm-crypt, and similar ancestry is followed through the `lsblk` dependency tree.

An interactive operation displays the path, model, size, and serial, then requires the exact phrase `ERASE <path>`. An unattended operation requires both `--confirm-erase` and an exact identity from `--expect-identity`. Non-USB disks additionally require `--allow-non-usb`.

Immediately before `wipefs` and `sfdisk`, FlexBoot rediscovers the target. It aborts if the resolved path, major/minor, capacity, available serial, or by-id path changed. This reduces device-node reuse and selection/write race risk.
The mounted/system/non-USB checks are also repeated after confirmation, and shared
logical devices protect every discovered physical ancestor. Ext4 subvolume source
suffixes are normalized, and swap files are resolved to their backing filesystem.

Automated image builds have a separate guard: after attaching a file, the builder accepts only a resolved `/dev/loop*` device. Tests never invoke a write path on physical storage.

ISO names containing path separators or control characters are rejected. External programs always receive argv arrays. ISO copies are hidden until flushed and atomically renamed. The manifest is operational state and is checked against files and generated configuration; it is never treated as a trusted authority.
Existing-media access requires the GPT EFI/data roles, expected filesystem types
and labels, and a manifest UUID matching the real data filesystem. Writable access
rejects mounted or protected targets. Predictable temporary-file symlinks are not
followed when writing metadata. Failed mount cleanup never recursively removes a
mountpoint; it preserves the path for administrator recovery.

Installation is explicit. Only `install --dependencies` invokes the distribution
package manager. A system-wide launcher uses root-owned isolated code and does not
import from the source checkout, user site packages, or `PYTHONPATH`. No ordinary
runtime operation installs dependencies or silently elevates privileges.

Recorded SHA-256 values detect changes after installation. They do not authenticate an ISO or its publisher. FlexBoot does not download code, contact an update service, modify firmware NVRAM, or support Secure Boot in this release.

Residual risks include host utility bugs, malicious privileged host state, unusual storage topologies not represented accurately by `lsblk`, firmware-specific GRUB behavior, and a physical device changing in ways that preserve every collected identity field. Review `devices --verbose`, use dry-run, and keep valuable disks disconnected during first hardware validation.
