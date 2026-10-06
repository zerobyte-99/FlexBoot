"""Explicit host setup; ordinary runtime commands never install packages."""
from __future__ import annotations

import json
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from . import __version__
from .doctor import diagnose
from .errors import FlexBootError
from .process import Runner

LAUNCHER_MARKER = "# FlexBoot managed launcher"


def setup_report(profile: str, *, system: bool = False) -> dict[str, object]:
    report = diagnose(profile)
    if system and importlib.util.find_spec("venv") is None:
        report["required"]["venv"] = {"found": False, "package": "python3-venv"}
        report["capabilities"][profile]["missing"].append("Python venv module")
        report["capabilities"][profile]["ready"] = False
        report["ready"] = False
    return report


def distribution() -> dict[str, str]:
    values = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        return {}
    return values


def missing_packages(report: dict[str, object]) -> list[str]:
    packages = {item["package"] for item in report["required"].values() if not item["found"] or not item.get("usable", True)}
    if report["profile"] in ("create", "image"):
        if not report["grub_target_x86_64_efi"]:
            packages.add("grub-efi-amd64-bin")
        if not report["grub_unicode_font"]:
            packages.add("grub2-common")
    if report["profile"] == "qemu" and not report["optional"]["OVMF"]["found"]:
        packages.add("ovmf")
    return sorted(packages)


def dependency_plan(report: dict[str, object], *, yes: bool = False) -> list[str]:
    if report["host"]["system"] != "Linux" or (report["profile"] in ("create", "image") and report["host"]["architecture"].lower() not in ("x86_64", "amd64")):
        raise FlexBootError("The selected capability is not supported on this host; installing packages cannot fix its platform")
    packages = missing_packages(report)
    if not packages:
        return []
    distro = distribution()
    identities = {distro.get("ID", ""), *distro.get("ID_LIKE", "").split()}
    if not identities.intersection({"debian", "ubuntu", "kali"}) or not shutil.which("apt-get"):
        raise FlexBootError("Automatic dependency installation currently supports Debian/Ubuntu/Kali."
                            "\nUse doctor to find missing commands and install your distribution's packages.")
    return ["apt-get", "install", "--no-remove", *(["--yes"] if yes else []), *packages]


def validate_system_prefix(prefix: Path) -> None:
    for directory in (prefix.absolute(), *prefix.absolute().parents,
                      prefix.absolute() / "bin", prefix.absolute() / "lib",
                      prefix.absolute() / "lib/flexboot", prefix.absolute() / "lib/flexboot/releases"):
        if directory.is_symlink():
            raise FlexBootError(f"System installation path is a symlink: {directory}")
        if directory.exists():
            state = directory.stat()
            if not directory.is_dir() or state.st_uid != 0 or state.st_mode & 0o022:
                raise FlexBootError(f"System installation directories must be root-owned and not group/world writable: {directory}")
    launcher = prefix.absolute() / "bin/flexboot"
    if launcher.exists():
        state = launcher.stat()
        if state.st_uid != 0 or state.st_mode & 0o022:
            raise FlexBootError("An existing system launcher must be root-owned and not group/world writable")
    interpreter = Path(sys.executable).resolve()
    for path in (interpreter, *interpreter.parents):
        state = path.stat()
        if state.st_uid != 0 or state.st_mode & 0o022:
            raise FlexBootError("System installation requires a root-owned Python interpreter; use /usr/bin/python3")


def install_application(prefix: Path) -> Path:
    """Install an immutable local copy in a pip-free venv and publish a launcher.

    The CLI requires root for system installation. Tests use disposable prefixes.
    Old releases remain available; an update never deletes a running installation.
    """
    try:
        import venv
    except ImportError as exc:
        raise FlexBootError("Python venv module is unavailable; install python3-venv") from exc
    prefix = prefix.absolute()
    if any(path.is_symlink() for path in (prefix, *prefix.parents)):
        raise FlexBootError("Installation prefix and ancestors must not be symlinks")
    bindir = prefix / "bin"
    releases = prefix / "lib/flexboot/releases"
    for directory in (bindir, prefix / "lib", prefix / "lib/flexboot", releases):
        if directory.is_symlink():
            raise FlexBootError(f"Installation directory must not be a symlink: {directory}")
    launcher = bindir / "flexboot"
    managed = False
    if launcher.is_file() and not launcher.is_symlink():
        header = f"#!/bin/sh\n{LAUNCHER_MARKER}\n".encode()
        with launcher.open("rb") as existing:
            managed = existing.read(len(header)) == header
    if launcher.is_symlink() or (launcher.exists() and not managed):
        raise FlexBootError(f"Refusing to overwrite an unrelated launcher: {launcher}")
    # Do not let a permissive caller umask create writable system ancestors.
    for directory in (*reversed(releases.parents), releases, bindir):
        if not directory.exists():
            directory.mkdir(mode=0o755)
    release = releases / f"{__version__}-{uuid.uuid4().hex}"
    temporary_launcher: Path | None = None
    try:
        # Build privately so partially created venv directories are not exposed.
        release.mkdir(mode=0o700)
        venv.EnvBuilder(with_pip=False).create(release)
        python = release / "bin/python"
        site = Path(subprocess.run(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            check=True, text=True, capture_output=True).stdout.strip())
        if not site.is_relative_to(release):
            raise FlexBootError("Virtual environment reported an unexpected package directory")
        shutil.copytree(Path(__file__).parent, site / "flexboot",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for path in (release, *release.rglob("*")):
            if not path.is_symlink():
                path.chmod(path.stat().st_mode & ~0o022)
        release.chmod(0o755)
        # Do not execute source-checkout code as a root user's implicit import.
        # -I prevents PYTHONPATH, cwd and user-site injection into the launcher.
        subprocess.run([str(python), "-I", "-m", "flexboot", "--version"],
                       check=True, cwd="/", capture_output=True, text=True)
        fd, name = tempfile.mkstemp(prefix=".flexboot-", dir=bindir)
        temporary_launcher = Path(name)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"#!/bin/sh\n{LAUNCHER_MARKER}\nexec {shlex.quote(str(python))} -I -m flexboot \"$@\"\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_launcher.chmod(0o755)
        # Verify from outside the checkout before exposing this launcher.
        subprocess.run([str(temporary_launcher), "--version"], check=True, cwd="/",
                       capture_output=True, text=True)
        os.replace(temporary_launcher, launcher)
        temporary_launcher = None
        return launcher
    except BaseException:
        # This is a newly created, private venv tree, never a mountpoint.
        shutil.rmtree(release, ignore_errors=True)
        raise
    finally:
        if temporary_launcher is not None:
            temporary_launcher.unlink(missing_ok=True)


def run_install(args) -> int:
    from .builder import require_root
    report = setup_report(args.profile, system=args.system)
    package_command = dependency_plan(report, yes=args.yes) if args.dependencies else []
    payload = {"profile": args.profile, "ready": report["ready"],
               "missing": report["capabilities"][args.profile]["missing"],
               "dependency_command": package_command,
               "launcher": str(args.prefix.absolute() / "bin/flexboot") if args.system else None,
               "dry_run": args.dry_run}
    if args.dry_run or not (args.dependencies or args.system):
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Setup check for {args.profile}: " + ("ready" if report["ready"] else "missing " + ", ".join(payload["missing"])))
            if package_command:
                print("Would run: " + shlex.join(package_command))
            if args.system:
                print("Would install launcher: " + payload["launcher"])
            print("No changes made.")
        return 0 if args.dry_run or report["ready"] else 1
    require_root()
    if args.system:
        validate_system_prefix(args.prefix)
    if package_command:
        Runner().run(package_command, capture=False, mutate=True, output_to_stderr=args.json)
        importlib.invalidate_caches()
        report = setup_report(args.profile, system=args.system)
    if not report["ready"]:
        raise FlexBootError("Setup is still incomplete: " + ", ".join(report["capabilities"][args.profile]["missing"]))
    try:
        launcher = install_application(args.prefix) if args.system else None
    except subprocess.CalledProcessError as exc:
        raise FlexBootError("Isolated installation failed verification: " + (exc.stderr or str(exc))) from exc
    payload.update(ready=True, missing=[], launcher=str(launcher) if launcher else None)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Host verified for {args.profile}.")
        if launcher:
            print(f"Installed: {launcher}\nRun from any directory: {launcher} --help")
            if shutil.which("flexboot") != str(launcher):
                print(f"Add {launcher.parent} to PATH to use the short command 'flexboot'.")
    return 0
