from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .branding import BRAND
from .builder import build_attached, open_media, require_root
from .devices import Device, discover, find_device, format_size
from .disk import assert_loop_target
from .doctor import PROFILES as CAPABILITIES, diagnose, preflight
from .errors import CleanupError, FlexBootError
from .iso import inspect_iso, require_supported
from .profiles import PROFILES as ISO_PROFILES, supported_descriptions
from .media import (
    batch_add, available_layouts, available_themes, inspect as inspect_media, remove_iso,
    resolve_builtin_theme, resolve_theme_layout, set_theme, sync as sync_media,
    validate_background, verify,
)
from .process import Runner
from .safety import check_unattended_confirmation, protected_device_names, revalidate_identity, system_mount_sources, validate_physical_target
from .targets import attached_image, create_sparse, parse_size
from .ui import UI


def _add_output_options(parser: argparse.ArgumentParser, *, dry_run: bool = False) -> None:
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--verbose", action="store_true", help="show detailed diagnostics")
    if dry_run:
        parser.add_argument("--dry-run", action="store_true", help="plan without persistent modifications")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="flexboot", description=f"{BRAND.product_name} — {BRAND.tagline}")
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    profiles = commands.add_parser("profiles", help="list supported ISO boot families")
    _add_output_options(profiles)
    iso = commands.add_parser("iso", help="read-only source ISO diagnostics")
    iso_commands = iso.add_subparsers(dest="iso_command", required=True)
    iso_inspect = iso_commands.add_parser("inspect", help="inspect source contents and the selected boot recipe")
    iso_inspect.add_argument("path", type=Path)
    _add_output_options(iso_inspect)
    doctor = commands.add_parser("doctor", help="check host dependencies")
    doctor.add_argument("--for", dest="profile", choices=CAPABILITIES, default="create", help="capability to check (default: create)")
    _add_output_options(doctor)
    install = commands.add_parser("install", help="check setup; explicitly install dependencies or a global launcher")
    install.add_argument("--for", dest="profile", choices=CAPABILITIES, default="create")
    install.add_argument("--dependencies", action="store_true", help="install missing distribution packages (Debian/Ubuntu/Kali)")
    install.add_argument("--system", action="store_true", help="install an isolated system-wide FlexBoot command")
    install.add_argument("--prefix", type=Path, default=Path("/usr/local"))
    install.add_argument("--yes", action="store_true", help="allow the package manager to proceed without its prompt")
    _add_output_options(install, dry_run=True)
    devices = commands.add_parser("devices", help="list system storage and USB candidates")
    _add_output_options(devices)
    commands.add_parser("wizard", help="guided target selection")

    create = commands.add_parser("create", help="erase and create FlexBoot media")
    create.add_argument("target", type=Path)
    create.add_argument("--allow-non-usb", action="store_true")
    create.add_argument("--confirm-erase", action="store_true", help="allow non-interactive erase; requires --expect-identity")
    create.add_argument("--expect-identity", help="exact serial, by-id path, or major/minor:size fingerprint")
    _add_output_options(create, dry_run=True)

    for name, help_text in (
        ("list", "list installed ISOs"), ("status", "show media status"),
        ("inspect", "show detailed installed state"), ("verify", "verify media consistency"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("target", type=Path)
        if name == "verify":
            sub.add_argument("--quick", action="store_true", help="check structure and sizes without hashing ISO contents")
        _add_output_options(sub)
    add = commands.add_parser("add", help="inspect and add ISO files")
    add.add_argument("target", type=Path)
    add.add_argument("isos", nargs="+", type=Path)
    add.add_argument("--replace", action="store_true", help="transactionally replace an installed ISO with the same name")
    add.add_argument("--continue-on-error", action="store_true", help="continue after individual source errors; media failures still stop")
    _add_output_options(add, dry_run=True)
    remove = commands.add_parser("remove", help="remove an installed ISO")
    remove.add_argument("target", type=Path)
    remove.add_argument("iso_name")
    _add_output_options(remove, dry_run=True)
    sync = commands.add_parser("sync", help="reinspect files and regenerate metadata/menu")
    sync.add_argument("target", type=Path)
    _add_output_options(sync, dry_run=True)

    theme = commands.add_parser("theme", help="list or select a GRUB background")
    theme.add_argument("target", nargs="?", type=Path, help="FlexBoot disk, such as /dev/sdb")
    theme.add_argument("selection", nargs="?", help="built-in name, number, or custom PNG path")
    theme.add_argument("--list", action="store_true", help="list numbered built-in themes")
    _add_output_options(theme, dry_run=True)

    image = commands.add_parser("image", help="raw image operations")
    image_commands = image.add_subparsers(dest="image_command", required=True)
    image_create = image_commands.add_parser("create", help="create a sparse FlexBoot image")
    image_create.add_argument("path", type=Path)
    image_create.add_argument("--size", required=True)
    _add_output_options(image_create, dry_run=True)
    image_inspect = image_commands.add_parser("inspect", help="inspect a FlexBoot image")
    image_inspect.add_argument("path", type=Path)
    _add_output_options(image_inspect)
    image_boot = image_commands.add_parser("boot", help="boot an image in QEMU/OVMF")
    image_boot.add_argument("path", type=Path)
    image_boot.add_argument("--headless", action="store_true")
    return root


def _device_dict(device: Device, protected: set[str]) -> dict[str, object]:
    return {
        "path": str(device.path), "model": device.model, "vendor": device.vendor,
        "serial": device.serial, "transport": device.transport, "size": device.size,
        "type": device.type, "partition_table": device.pttype, "system": device.name in protected,
        "mountpoints": list(device.mountpoints), "children": [_device_dict(c, protected) for c in device.children],
        "identity": device.identity().fingerprint,
    }


def command_doctor(args: argparse.Namespace) -> int:
    result = diagnose(args.profile)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        ui = UI(); ui.heading(f"{BRAND.product_name} doctor")
        host = result["host"]
        print(f"\nHost:\n  {host['system']} {host['release']}\n  Architecture: {host['architecture']}\n")
        print("Required:")
        for name, item in result["required"].items():
            usable = item["found"] and item.get("usable", True)
            (ui.ok if usable else ui.warn)(f"{name}" + ("" if usable else f" (missing or unusable; package: {item['package']})"))
        print("\nGRUB:\n  version: " + (result["grub_version"] or "unavailable"))
        print("  x86_64-efi support: " + ("available" if result["grub_target_x86_64_efi"] else "missing (package: grub-efi-amd64-bin)"))
        print("  Unicode font: " + ("available" if result["grub_unicode_font"] else "missing (package: grub2-common)"))
        print("\nCapabilities:")
        for name, capability in result["capabilities"].items():
            (ui.ok if capability["ready"] else ui.warn)(name + ("" if capability["ready"] else ": " + ", ".join(capability["missing"])))
        print("\nOptional:")
        for name, item in result["optional"].items():
            (ui.ok if item["found"] else ui.warn)(f"{name}" + ("" if item["found"] else f" (package: {item['package']})"))
    return 0 if result["ready"] else 1


def device_inventory() -> tuple[list[Device], set[str]]:
    devices = discover()
    protected = protected_device_names(devices, system_mount_sources())
    return devices, protected


def command_devices(args: argparse.Namespace) -> int:
    devices, protected = device_inventory()
    disks = [d for d in devices if d.type == "disk"]
    if args.json:
        print(json.dumps([_device_dict(d, protected) for d in disks], indent=2))
        return 0
    for title, selected in (
        ("SYSTEM", [d for d in disks if d.name in protected]),
        ("CANDIDATE USB", [d for d in disks if d.name not in protected and d.transport.lower() == "usb"]),
        ("OTHER DISKS", [d for d in disks if d.name not in protected and d.transport.lower() != "usb"]),
    ):
        print(title)
        if not selected:
            print("  (none)")
        for d in selected:
            print(f"  {d.path}  {(d.vendor + ' ' + d.model).strip() or 'Unknown model'}  {format_size(d.size)}  {d.transport or 'unknown transport'}")
            if args.verbose:
                print(f"    serial={d.serial or 'unavailable'} identity={d.identity().fingerprint} mounted={d.mounted}")
        print()
    return 0


def command_wizard() -> int:
    ui = UI(); ui.banner(BRAND.product_name, BRAND.tagline)
    devices, protected = device_inventory()
    candidates = [d for d in devices if d.type == "disk" and d.name not in protected and d.transport.lower() == "usb"]
    if not candidates:
        print("\nNo candidate USB disks found. FlexBoot has made no changes.")
        return 1
    print("\nAvailable candidate devices:\n")
    for index, device in enumerate(candidates, 1):
        print(f"  [{index}] {(device.vendor + ' ' + device.model).strip() or 'Unknown model'}\n      {device.path}\n      {format_size(device.size)}\n      USB\n      Serial: {device.serial or 'unavailable'}")
    answer = input("\nSelect target (number, or blank to cancel): ").strip()
    if not answer:
        print("Cancelled; no changes made.")
        return 0
    try:
        selected = candidates[int(answer) - 1]
    except (ValueError, IndexError):
        raise FlexBootError("Invalid selection")
    print(f"\nSelected device\n  Path: {selected.path}\n  By-id/identity: {selected.identity().fingerprint}\n  Model: {selected.model or 'unknown'}\n  Vendor: {selected.vendor or 'unknown'}\n  Serial: {selected.serial or 'unavailable'}\n  Capacity: {format_size(selected.size)}\n  Partition table: {selected.pttype or 'none'}\n  Mounted: {selected.mounted}")
    print(f"\nProposed layout\n  1: 512 MiB FAT32 {BRAND.efi_label}\n  2: remaining space ext4 {BRAND.data_label}")
    print(f"\nReview with:\n  sudo flexboot create {selected.path} --dry-run\n\nThen create interactively with:\n  sudo flexboot create {selected.path}")
    print("\nThe wizard made no changes.")
    return 0


def _confirm_interactive(device: Device) -> None:
    phrase = f"ERASE {device.path}"
    print(f"THIS WILL ERASE THE ENTIRE DEVICE\n\nDevice : {device.path}\nModel  : {device.model or 'unknown'}\nSize   : {format_size(device.size)}\nSerial : {device.serial or 'unavailable'}\n\nType exactly:\n\n{phrase}\n")
    if input("> ") != phrase:
        raise FlexBootError("Confirmation did not match; no changes made")


def command_create(args: argparse.Namespace) -> int:
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    preflight("create")
    all_devices, protected = device_inventory()
    device = find_device(args.target)
    validate_physical_target(device, protected_names=protected, allow_non_usb=args.allow_non_usb)
    before = device.identity()
    if args.dry_run:
        plan = {"target": str(device.path), "identity": before.fingerprint, "erase": True, "layout": [f"512 MiB FAT32 {BRAND.efi_label}", f"remaining ext4 {BRAND.data_label}"], "persistent_changes": False}
        print(json.dumps(plan, indent=2) if args.json else f"Dry run: would erase {device.path}\nIdentity: {before.fingerprint}\nLayout: 512 MiB FAT32 + remaining ext4\nNo changes made.")
        return 0
    require_root()
    if args.confirm_erase or args.expect_identity:
        check_unattended_confirmation(before, args.expect_identity, args.confirm_erase)
    else:
        _confirm_interactive(device)
    def identity_check() -> None:
        current = find_device(args.target)
        _, current_protected = device_inventory()
        validate_physical_target(current, protected_names=current_protected, allow_non_usb=args.allow_non_usb)
        revalidate_identity(before, current.identity())
    build_attached(device.path, runner, identity_check=identity_check)
    print(f"Created {BRAND.product_name} media on {device.path}")
    return 0


def _read_command(args: argparse.Namespace, action: str) -> int:
    runner = Runner(verbose=args.verbose)
    target_device = find_device(args.target, runner)
    with open_media(args.target, runner, readonly=True) as paths:
        if action == "verify":
            problems = verify(paths, full_hash=not args.quick)
            payload = {"ok": not problems, "problems": problems, "iso_hashes_checked": not args.quick}
        else:
            payload = inspect_media(paths, full_hash=action == "inspect")
            payload["device"] = _device_dict(target_device, set())
            if action == "list":
                payload = payload["isos"]
    if args.json:
        print(json.dumps(payload, indent=2))
    elif action == "verify":
        if payload["ok"]:
            print("Quick checks passed: manifest, sizes, loader, and menu are consistent. ISO contents were not hashed." if args.quick else "Verification passed: manifest, files, local hashes, loader, and generated menu are consistent.")
        else:
            print("Verification failed:\n  " + "\n  ".join(payload["problems"]))
    elif action == "list":
        for item in payload: print(f"{item['filename']}  {format_size(item['size'])}  {item['profile']}")
        if not payload: print("No ISOs installed.")
    elif action == "status":
        problems = payload["verification"]
        print(f"{BRAND.product_name} {payload['version']}\n\nDevice\n  {args.target}\n  {target_device.model or 'Unknown model'}\n  {format_size(target_device.size)}\n\nBoot\n  UEFI x86_64\n  Removable loader: {'OK' if payload['bootloader_present'] else 'MISSING'}\n\nImages")
        if payload["isos"]:
            for item in payload["isos"]:
                print(f"  ✓ {item['filename']}\n    {item['profile']} · {format_size(item['size'])}")
        else:
            print("  (none)")
        print("\nStatus\n  " + ("✓ Manifest, menu, and files consistent" if not problems else "✗ " + "\n  ✗ ".join(problems)))
    else:
        print(json.dumps(payload, indent=2))
    return 0 if action != "verify" or payload["ok"] else 2


def _mutating_media(args: argparse.Namespace, action: str) -> int:
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    if args.dry_run:
        if action == "add":
            matches = []
            stopped = False
            for source in args.isos:
                if stopped:
                    matches.append({"file": str(source), "status": "not-attempted"})
                    continue
                try:
                    match = require_supported(source, runner)
                    matches.append({"file": str(source), "profile": match.profile, "status": "would-add-or-replace" if args.replace else "would-add-or-skip"})
                except (FlexBootError, OSError) as exc:
                    matches.append({"file": str(source), "status": "failed", "reason": str(exc)})
                    stopped = not args.continue_on_error
            payload = {"action": action, "target": str(args.target), "isos": matches, "persistent_changes": False, "target_validated": False, "free_space_checked": False}
            if args.json:
                print(json.dumps(payload, indent=2))
            else:
                for item in matches:
                    print(f"{item['status']}: {item['file']}" + (f" — {item['reason']}" if "reason" in item else ""))
                print("Source-only dry run; target, duplicates, and free space were not checked. No changes made.")
            return 2 if any(item["status"] == "failed" for item in matches) else 0
        else:
            print(json.dumps({"action": action, "target": str(args.target), "persistent_changes": False}, indent=2) if args.json else f"Dry run: would {action} {args.target}. No changes made.")
        return 0
    require_root()
    preflight("media")
    with open_media(args.target, runner) as paths:
        if action == "add":
            outcomes = batch_add(paths, args.isos, runner, replace=args.replace, continue_on_error=args.continue_on_error)
            counts = {status: sum(item["status"] == status for item in outcomes) for status in ("added", "replaced", "skipped", "failed", "not-attempted")}
            if args.json:
                print(json.dumps({"target": str(args.target), "isos": outcomes, "summary": counts}, indent=2))
            else:
                for item in outcomes:
                    print(f"{item['status']}: {item['file']}" + (f" — {item['reason']}" if "reason" in item else ""))
                print("Summary: " + ", ".join(f"{count} {status}" for status, count in counts.items() if count))
            return 2 if counts["failed"] else 0
        elif action == "remove":
            remove_iso(paths, args.iso_name, runner); print(f"Removed {args.iso_name}")
        else:
            manifest = sync_media(paths, runner); print(f"Synchronized {len(manifest.isos)} ISO(s)")
    return 0


def command_theme(args: argparse.Namespace) -> int:
    themes = available_themes()
    if args.list:
        payload = [{"number": index, "name": name} for index, name in enumerate(themes, 1)]
        if args.json:
            print(json.dumps({"layouts": available_layouts(), "backgrounds": payload}, indent=2))
        else:
            print("Layout themes:")
            for name in available_layouts():
                print(f"  {name}")
            print("\nBuilt-in backgrounds:")
            for item in payload:
                print(f"  {item['number']}. {item['name']}")
            print("\nA custom background must be a non-interlaced PNG up to 8192×8192 pixels.")
        return 0
    if args.target is None or args.selection is None:
        raise FlexBootError("Specify a target and theme selection, or use: flexboot theme --list")

    layout = resolve_theme_layout(args.selection)
    builtin = resolve_builtin_theme(args.selection)
    if layout is not None:
        preview = {"kind": "layout", "name": layout}
        selection = layout
    elif builtin is not None:
        preview: dict[str, object] = {"kind": "builtin", "name": builtin}
        selection: str | Path = builtin
    else:
        if args.selection.strip().isdigit():
            raise FlexBootError(f"Theme number is out of range: {args.selection}")
        custom = Path(args.selection).expanduser().resolve()
        width, height = validate_background(custom)
        preview = {"kind": "custom", "name": custom.name, "width": width, "height": height}
        selection = custom
    if args.dry_run:
        payload = {"action": "theme", "target": str(args.target), "theme": preview, "persistent_changes": False}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Dry run: would set {args.target} theme to {preview['name']}. No changes made.")
        return 0

    require_root()
    runner = Runner(verbose=args.verbose)
    preflight("media")
    with open_media(args.target, runner) as paths:
        setting = set_theme(paths, selection)
        problems = verify(paths, full_hash=False)
        if problems:
            raise FlexBootError("Theme was written but media verification failed:\n  " + "\n  ".join(problems))
    if args.json:
        print(json.dumps({"target": str(args.target), "theme": setting}, indent=2))
    else:
        print(f"Theme updated on {args.target}: layout={setting['layout']}, background={setting['name']}")
    return 0


def command_image(args: argparse.Namespace) -> int:
    runner = Runner(dry_run=getattr(args, "dry_run", False), verbose=getattr(args, "verbose", False))
    if args.image_command == "create":
        size = parse_size(args.size)
        if args.dry_run:
            create_sparse(args.path, size, runner=runner)
            print(f"Dry run: would create sparse image {args.path} ({format_size(size)}). No changes made.")
            return 0
        require_root()
        preflight("image")
        created = False
        try:
            create_sparse(args.path, size, runner=runner)
            created = True
            with attached_image(args.path, runner) as target:
                assert_loop_target(target.device)
                build_attached(target.device, runner)
        except CleanupError:
            # An active mount/loop may still need the image for recovery.
            raise
        except BaseException:
            if created:
                args.path.unlink(missing_ok=True)
            raise
        print(f"Created {args.path} ({format_size(size)})")
        return 0
    if args.image_command == "inspect":
        require_root()
        with attached_image(args.path, runner, readonly=True) as target, open_media(target.device, runner, readonly=True) as paths:
            payload = inspect_media(paths, full_hash=False)
        print(json.dumps(payload, indent=2))
        return 0
    return boot_image(args)


def boot_image(args: argparse.Namespace) -> int:
    import shutil
    from .doctor import find_ovmf
    qemu = shutil.which("qemu-system-x86_64"); firmware = find_ovmf()
    if not qemu or not firmware:
        raise FlexBootError("QEMU/OVMF unavailable; install qemu-system-x86 and ovmf")
    argv = [qemu, "-machine", "q35,accel=tcg", "-m", "1024", "-bios", firmware, "-drive", f"file={args.path.resolve()},format=raw,if=virtio", "-boot", "c"]
    if args.headless: argv += ["-nographic"]
    return Runner().run(argv, capture=False).returncode


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "profiles":
        payload = [{"id": profile.profile_id, "description": profile.description} for profile in ISO_PROFILES]
        print(json.dumps(payload, indent=2) if args.json else "\n".join(f"{item['id']}: {item['description']}" for item in payload))
        return 0
    if args.command == "iso":
        facts, match = inspect_iso(args.path, Runner(verbose=args.verbose))
        payload = {"file": str(args.path), "volume_id": facts.volume_id, "supported": bool(match),
                   "profile": match.profile if match else None, "boot": asdict(match.boot) if match else None,
                   "kernel_architectures": dict(facts.kernel_architectures),
                   "characteristics": sorted(path for path in facts.paths if path.count("/") <= 2)[:40],
                   "supported_families": supported_descriptions()}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"ISO: {args.path}\nVolume: {facts.volume_id or 'unknown'}\nProfile: {match.description if match else 'unsupported layout'}")
            if match:
                print(json.dumps(payload["boot"], indent=2))
            else:
                print("No supported boot recipe matched. Rename alone cannot add support.\nSupported families:\n  " + "\n  ".join(payload["supported_families"]))
        return 0 if match else 2
    if args.command == "install":
        from .installer import run_install
        return run_install(args)
    if args.command == "doctor": return command_doctor(args)
    if args.command == "devices": return command_devices(args)
    if args.command == "wizard": return command_wizard()
    if args.command == "create": return command_create(args)
    if args.command in {"list", "status", "inspect", "verify"}: return _read_command(args, args.command)
    if args.command in {"add", "remove", "sync"}: return _mutating_media(args, args.command)
    if args.command == "theme": return command_theme(args)
    if args.command == "image": return command_image(args)
    raise FlexBootError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        return dispatch(parser().parse_args(argv))
    except KeyboardInterrupt:
        print("Interrupted; cleanup attempted.", file=sys.stderr); return 130
    except (FlexBootError, OSError) as exc:
        print(f"flexboot: {exc}", file=sys.stderr); return 2
