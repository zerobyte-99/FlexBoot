# Troubleshooting

## A dependency is missing

Run `python3 -m flexboot doctor`. It prints the likely Debian/Ubuntu package without installing it.

## ISO inspection tools are absent

FlexBoot prefers `xorriso` or `isoinfo`, then uses its bounded read-only ISO 9660/Joliet reader. Source ISOs are never modified.

## A custom background is rejected

Use a non-interlaced RGB, RGBA, or grayscale PNG. The maximum dimensions are 8192×8192 and the maximum file size is 50 MiB. Use `flexboot theme /dev/sdX IMAGE.png --dry-run` to validate it without modifying the drive.

## A target is rejected as mounted

Unmount every child filesystem yourself, then rerun discovery. FlexBoot does not automatically unmount unrelated user data.

## A non-USB disk is rejected

This is intentional. After identifying the disk and reviewing a dry run, add `--allow-non-usb`. All other checks and typed/identity confirmation still apply.

## GRUB installation fails

Confirm `grub-install --version`, x86_64 EFI modules, a mounted FAT32 ESP, and sufficient space. FlexBoot does not download a replacement loader. Some distributions split the required files into `grub-efi-amd64-bin`.

## An ISO is unsupported

Use a live image rather than an installer image and inspect the diagnostic. Supported images need complete casper or Debian Live resources. Renaming a file cannot change its detected profile.

## Secure Boot refuses the loader

Secure Boot is outside the MVP. Disable it for this media. FlexBoot does not claim a shim or signed boot chain.

## QEMU cannot start

Install `qemu-system-x86` and `ovmf`, or validate on hardware. The QEMU check is optional and is reported as skipped when those tools are unavailable.
