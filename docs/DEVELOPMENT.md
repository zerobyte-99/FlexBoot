# Development

## Versioning

Increment the application version before every new commit that will be pushed.
Update both `flexboot/__init__.py` and `pyproject.toml` in that commit and verify
`python3 -m flexboot --version`. Use a patch increment by default unless a minor
or major release is explicitly chosen. Commit and push share the same version.
Historical version values in migration test fixtures should remain unchanged.

Run all standard-library tests and syntax checks:

```bash
python3 -m unittest discover -v
python3 -m compileall -q flexboot tests tools
python3 -m flexboot --help
python3 -m flexboot doctor
python3 -m flexboot devices --json
```

Tests use synthetic block-device JSON, temporary directories, mock loop commands, and synthetic ISO path sets. They do not write block devices.

The privileged integration path is opt-in. Review the test and ensure no valuable loop state is in use, then run:

```bash
sudo FLEXBOOT_RUN_IMAGE_TESTS=1 python3 -m unittest tests.test_integration_image -v
sudo python3 -m flexboot image create ./out/flexboot.img --size 2G
sudo python3 -m flexboot image inspect ./out/flexboot.img
```

Inspect active loops afterward with `losetup --list`. QEMU validation uses `python3 -m flexboot image boot ./out/flexboot.img`; hardware acceleration is not required.

Regenerate the classic F logo, selection graphics, and Classic Grid background with
`python3 tools/generate_assets.py`. The script uses only zlib and PNG primitives
from the standard library and preserves the generated background variants. The
default menu/fold logo is shipped artwork: the script preserves
`branding/logo.png` and synchronizes its runtime copy rather than replacing it
with the classic F.

## Boot-menu screenshots

Capture GRUB rendering the shipped theme and generated menu without root:

```bash
python3 tools/capture_boot_screen.py ./out/boot-menu.png
```

Requires `grub-mkstandalone`, `mkfs.ext4`, `qemu-system-x86_64`, and OVMF. The helper
uses host GRUB to create a temporary standalone removable EFI application,
deploys the production theme assets, and runs the production base configuration
and menu generator with illustrative ISO records. Its temporary ext4 filesystem
provides the UUID used by the base configuration. It does not copy or boot ISO
images, partition physical storage, attach loops, or mount host filesystems.

QEMU boots through OVMF with software emulation and networking disabled. A private
copy of OVMF variables and all temporary media are cleaned up after QEMU exits.
The PNG comes directly from QEMU's
[`screendump` command](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html#command-screendump),
with no composited menu or added text. The screenshot validates graphical menu
rendering; it does not establish ISO boot compatibility or validate a full USB
installation.

Use `--firmware /path/to/OVMF_CODE_4M.fd` for firmware outside the usual locations;
its matching `OVMF_VARS_4M.fd` must be alongside it. `--qemu` and `--qemu-data`
support a local QEMU executable and ROM directory. Use `--wait 30` on slower hosts.
The output must be a new file. Inspect it visually before replacing the README
image at `docs/images/boot-menu.png`.

## Real ISO boot tests without root

Supply an ISO you have obtained and checked against its publisher's checksum:

```bash
python3 tools/test_iso_boot.py ./grml-small.iso ./out/grml-test \
  --expect 'grml login:'
python3 tools/test_iso_boot.py ./gentoo.iso ./out/gentoo-test \
  --expect 'livecd login:' --timeout 300
```

Requires the same host tools as the screenshot helper. It uses production ISO
inspection, copy, metadata, theme, and menu generation, then adds a serial console
solely for the test and selects the first menu entry through QEMU's keyboard.
Host GRUB creates a standalone removable
EFI loader; `mkfs.ext4 -d` populates a disposable regular-file filesystem containing
the intact ISO. QEMU has no network, physical disks, or CD-ROM. Data-disk writes use
temporary snapshots. No host mounts, loop attachments, or elevated privileges are
needed. Temporary media and private firmware variables are cleaned up even when
QEMU fails. Allow several GiB of temporary disk space and 1.5 GiB guest memory.

The output directory must be new. It retains serial/QEMU logs, the tested GRUB
configuration, and a screenshot. Exit status is nonzero on timeout, kernel panic,
or QEMU failure. Choose a distro-specific userspace/login marker; an early kernel
message would produce a misleading success. Vendor loopback submenus require
manual testing and are excluded from this helper. Firmware/QEMU override options
are the same as the screenshot helper.

This verifies ISO rediscovery through the initramfs into userspace. It does not
replace the privileged full-GPT `grub-install` integration test or hardware tests.


## Optional Windows validation

The privileged image suite includes default two-partition media and explicit
Windows-enabled three-partition provisioning. The latter needs the Windows host
dependencies reported by doctor and uses generated handoff-header fixtures; it
tests formatting, metadata, inspection, and integrity checks, not Windows boot.
It reports a dependency skip when that host capability is absent. Neither test
uses a physical target.

Actual installer validation requires user-supplied ISOs and audited local runtime
files. Use only owned raw images for both the USB source and installation target,
private OVMF variables and TPM state, and QEMU source snapshots. Check the chosen
ISO, full image application, and a subsequent destination-only boot into first-run
setup. A language-selection screen alone is insufficient. Check missing and
duplicate source markers, damaged resources, replacement rollback, and Linux
userspace from the shared menu. Keep firmware compatibility claims limited to
the tested environment; physical media creation remains a human operation.

The [Windows experiment record](WINDOWS-EXPERIMENTS.md) documents the measured
results and the explicit Basic Data FAT boot-layout requirement.
