# Troubleshooting

## A dependency is missing

Run `python3 -m flexboot doctor`. It prints the likely Debian/Ubuntu package without installing it.
Select `--for media` when only managing an existing drive. To preview and explicitly
install missing packages, use `install --dependencies --dry-run`, then run that
command with sudo and without dry-run. See [installation](INSTALLATION.md).

## Pip reports an externally managed environment

Use `sudo python3 -m flexboot install --system` for the isolated global command,
or install with pip in a virtual environment. Do not automatically add
`--break-system-packages` or remove Python's externally managed marker.

## An installed command does not reflect source edits

The global launcher uses an installed snapshot. Rerun `install --system` from the
updated checkout. Use `command -v flexboot` to check which launcher your PATH selects.

## Adding an existing ISO fails

Identical content is skipped. A different image with the same name requires
`add --replace`. If the installed file or manifest is inconsistent, verify the
drive before proceeding; batch continuation does not bypass media errors.

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
