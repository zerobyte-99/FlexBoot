# Architecture

FlexBoot is split along trust and lifecycle boundaries.

## Device backend

`devices.py` parses explicitly selected `lsblk --json --bytes` columns into immutable device models. `safety.py` walks both parent names and the returned dependency tree to protect the physical ancestors of `/`, `/boot`, `/boot/efi`, and swap. It snapshots resolved path, major/minor, size, serial, and a stable by-id path where available.

`targets.py` attaches sparse files through `losetup --partscan`; its context manager always attempts detach. `disk.py` creates the default two-partition GPT, waits for udev, and rediscovers children from block metadata. It never guesses `sdb1` or `nvme0n1p1`. The ESP uses the FAT-compatible label `FLEXBOOTEFI`; its GPT partition name is `FlexBoot EFI`. `mounts.py` creates private temporary mountpoints and unmounts them on normal exit, errors, or interruption.

## Bootloader backend

`grub.py` calls host `grub-install` with `x86_64-efi`, explicit EFI and boot directories, `--removable`, and `--no-nvram`. It checks for the standard `EFI/BOOT/BOOTX64.EFI` result. `grub.cfg` is stable and locates the ext4 data partition by UUID. `generated.cfg` contains the shared, ordered Linux and Windows ISO entries. Configuration is checked with `grub-script-check` when installed.

## ISO profiles

`iso.py` lists ISO contents read-only using xorriso, isoinfo, or the bounded built-in ISO 9660/Joliet reader. Profiles receive normalized paths, the volume ID, and selected bounded text files. They never match the host filename. Each profile returns a typed boot plan: either an explicit Linux kernel/initrd invocation or delegation to a vendor-supplied loopback GRUB configuration. The GRUB backend renders those generic plans and contains no distribution-specific branches.

All inspection backends also receive bounded kernel-header facts. Known 32-bit
direct Linux entries are rejected. Profile identifiers and aliases come from the
registry, so manifest validation does not duplicate a separate list of families.

## Media and UI

`manifest.py` owns atomic JSON writes, hashing, schema-1 migration, and partial-copy cleanup. Manifest schema 2 records the inspected boot plan so future menu regeneration does not need to guess from the profile name. `media.py` keeps files, manifest, and generated menu consistent. `builder.py` shares partitioning, formatting, mounting, and deployment between validated physical targets and attached raw images. `cli.py` handles presentation, confirmations, dry runs, JSON, and privilege boundaries.

`boot_paths.py` derives safe boot paths independently of profile selection. ISO
names with special characters retain their original file and receive a checked
relative symlink under `.flexboot/boot-isos/`. Media operations prepare these links
before publishing a menu, roll back new links on failure, and verify their exact
targets. This avoids vendor initramfs whitespace parsing problems without a second
copy, filename-based profile detection, or changes to the manifest schema.

No function builds a shell command. Every external command receives an argv list with `shell=False`.


## Optional Windows backend

`windows.py` inspects ISO9660/UDF resources with 7z, validates x64 boot-index-2
WinPE metadata and native Setup, prepares a WIM with wimlib, and writes a small
deterministic boot archive. Intact Windows ISOs remain on a separately reserved
NTFS partition. `windows.json` in ext4 metadata records filesystem identities,
boot partition role, runtime hashes, and per-image resource inventories.
`windows.cfg` retains a standalone Windows fragment for verification; the stable
configuration sources only `generated.cfg`, so entries appear once and can be
ordered across both families. Source files retain their original names; internal Windows paths
use hexadecimal IDs to avoid command-language filename interpretation.

The explicit Windows layout tags the FAT32 boot partition as Basic Data to avoid
adding an ESP candidate to Windows Setup's destination discovery. Its firmware
requirement is documented in the Windows guide; default Linux creation retains
an ESP. Creation validates the requested partition roles before formatting, and
existing-media access reconciles the actual role with Windows metadata.

The small `assets/windows_mount.c` helper dynamically loads the system virtdisk
API, attaches only the selected ISO read-only, and resolves its returned physical
CD-ROM device through storage-device numbers. WinPE requires exactly one source
marker, validates the selected payload through DISM, then launches native Setup
with an explicit installation WIM. Destination selection remains in Microsoft's
UI. Add/replace/remove use staged resources and rollback; full verification checks
recorded files, hashes, runtime, marker and generated menu.

## Menu presentation settings

`menu.py` owns schema-1 `.flexboot/menu.json`, with OS-qualified entry IDs,
optional labels and an explicit order list. It validates all settings and rejects
control characters and symlinked settings files. Labels are GRUB-quoted and do
not influence resource paths or boot parameters. Unlisted entries follow sorted
by display label with stable ID tie-breaking. Saved preferences for removed
images are retained for re-addition; reset clears them. Configuration publication
validates candidate files before writing, with rollback on failure. Windows
publication and Linux regeneration both rebuild the combined menu.
