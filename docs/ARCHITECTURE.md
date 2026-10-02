# Architecture

FlexBoot is split along trust and lifecycle boundaries.

## Device backend

`devices.py` parses explicitly selected `lsblk --json --bytes` columns into immutable device models. `safety.py` walks both parent names and the returned dependency tree to protect the physical ancestors of `/`, `/boot`, `/boot/efi`, and swap. It snapshots resolved path, major/minor, size, serial, and a stable by-id path where available.

`targets.py` attaches sparse files through `losetup --partscan`; its context manager always attempts detach. `disk.py` creates a two-partition GPT, waits for udev, and rediscovers children from block metadata. It never guesses `sdb1` or `nvme0n1p1`. The ESP uses the FAT-compatible label `FLEXBOOTEFI`; its GPT partition name is `FlexBoot EFI`. `mounts.py` creates private temporary mountpoints and unmounts them on normal exit, errors, or interruption.

## Bootloader backend

`grub.py` calls host `grub-install` with `x86_64-efi`, explicit EFI and boot directories, `--removable`, and `--no-nvram`. It checks for the standard `EFI/BOOT/BOOTX64.EFI` result. `grub.cfg` is stable and locates the ext4 data partition by UUID. `generated.cfg` contains only sorted ISO entries. Configuration is checked with `grub-script-check` when installed.

## ISO profiles

`iso.py` lists ISO contents read-only using xorriso, isoinfo, or the bounded built-in ISO 9660/Joliet reader. Profiles receive normalized paths, the volume ID, and selected bounded text files. They never match the host filename. Each profile returns a typed boot plan: either an explicit Linux kernel/initrd invocation or delegation to a vendor-supplied loopback GRUB configuration. The GRUB backend renders those generic plans and contains no distribution-specific branches.

## Media and UI

`manifest.py` owns atomic JSON writes, hashing, schema-1 migration, and partial-copy cleanup. Manifest schema 2 records the inspected boot plan so future menu regeneration does not need to guess from the profile name. `media.py` keeps files, manifest, and generated menu consistent. `builder.py` shares partitioning, formatting, mounting, and deployment between validated physical targets and attached raw images. `cli.py` handles presentation, confirmations, dry runs, JSON, and privilege boundaries.

No function builds a shell command. Every external command receives an argv list with `shell=False`.
