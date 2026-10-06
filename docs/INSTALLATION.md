# Installation and host setup

FlexBoot requires Linux and Python 3.11 or newer. Creation requires an x86-64 host.
Run from a checkout with `python3 -m flexboot`; neither pip nor a global installation
is needed for that workflow.

## Check capabilities

```bash
python3 -m flexboot doctor --for discovery
python3 -m flexboot doctor --for media
python3 -m flexboot doctor --for create
python3 -m flexboot doctor --for image
python3 -m flexboot doctor --for qemu
python3 -m flexboot install --json
```

Doctor reports all readiness tiers but its exit status follows the selected tier.
The default is `create`. Creation checks include the backend commands, required
EFI modules, the Unicode font, and whether `grub-install` can execute. These checks
run before erasure. Raw-image creation additionally requires `losetup`.

`media` checks the tools used to access existing FlexBoot filesystems. It does not
require the host's EFI GRUB installation modules. GRUB syntax checking and external
ISO inspection tools remain optional; the bounded built-in ISO reader is available.
No performance advantage is assumed without measuring the particular images.

## Explicit dependency installation

```bash
python3 -m flexboot install --dependencies --dry-run
sudo python3 -m flexboot install --dependencies
```

The supported package-manager backend is `apt-get` on Debian, Ubuntu, and Kali.
Only missing packages for the selected capability are requested; `--no-remove`
disallows package removals. The package manager retains its own confirmation
prompt unless `--yes` is supplied. FlexBoot does not run `apt-get update` or change
repositories. If package indexes are stale, update them explicitly and rerun setup.
Use your distribution's package manager manually on other distributions.

Setup repeats capability checks after package installation and fails if the host
is still incomplete. An installed package is not proof of successful booting.
Optional QEMU dependencies can be requested with `--for qemu` separately.

## Run FlexBoot from anywhere

```bash
sudo python3 -m flexboot install --dependencies --system
flexboot --version
sudo flexboot doctor --for create
```

The installer creates a fresh, pip-free virtual environment under
`/usr/local/lib/flexboot/releases/`, copies only the application package and its
assets, and verifies it from outside the source checkout. It publishes
`/usr/local/bin/flexboot` only after that succeeds. Python's isolated mode ignores
`PYTHONPATH`, the working directory, and user site packages.

Setup checks for the Python venv module when `--system` is requested and includes
its distribution package when it is missing.

System directories must be root-owned and not writable by other users. An unrelated
existing launcher or a symlink is rejected. The installer uses distribution Python
without modifying its packages, so PEP 668 does not need to be bypassed. A missing
venv module must be installed through the distribution, usually `python3-venv`.

`--prefix /absolute/path` selects an alternative system prefix; the launcher is
placed under its `bin` directory. Use its absolute path or add that directory to
PATH. The installer does not edit shell profiles or sudo's PATH policy.

Updates create a new release and replace the launcher atomically. Existing releases
are retained. Source edits do not update an installed snapshot automatically.
For removal, an administrator can remove the managed launcher and release directory
after checking their paths; no automatic uninstall or old-release pruning is provided.

## Read-only media commands

`list`, `status`, `inspect`, and `verify` can reuse accessible existing read-only
mounts whose device identity, partition roles, filesystem labels, and manifest UUID
match. Otherwise they require root to create private read-only mounts. They do not
silently elevate, unmount user filesystems, or add anyone to the `disk` group.

`verify` hashes ISO contents and reinspects boot profiles by default. `verify --quick` checks structure, sizes,
metadata, and configuration without establishing ISO-content integrity. Locally
recorded hashes do not prove vendor authenticity.
