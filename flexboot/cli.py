from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .branding import BRAND
from .builder import build_attached, open_media, require_root
from .devices import Device, discover, find_device, format_size
from .disk import assert_loop_target
from .doctor import diagnose
from .errors import FlexBootError
from .iso import inspect_iso
from .media import (
    add_iso, available_layouts, available_themes, inspect as inspect_media, remove_iso,
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
    doctor = commands.add_parser("doctor", help="check host dependencies")
    _add_output_options(doctor)
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
        _add_output_options(sub)
    add = commands.add_parser("add", help="inspect and add ISO files")
    add.add_argument("target", type=Path)
    add.add_argument("isos", nargs="+", type=Path)
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
    result = diagnose()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        ui = UI(); ui.heading(f"{BRAND.product_name} doctor")
        host = result["host"]
        print(f"\nHost:\n  {host['system']} {host['release']}\n  Architecture: {host['architecture']}\n")
        print("Required:")
        for name, item in result["required"].items():
            (ui.ok if item["found"] else ui.warn)(f"{name}" + ("" if item["found"] else f" (install package: {item['package']})"))
        print("\nGRUB:\n  version: " + (result["grub_version"] or "unavailable"))
        print("  x86_64-efi support: " + ("available" if result["grub_target_x86_64_efi"] else "missing (package: grub-efi-amd64-bin)"))
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
        revalidate_identity(before, find_device(args.target).identity())
    build_attached(device.path, runner, identity_check=identity_check)
    print(f"Created {BRAND.product_name} media on {device.path}")
    return 0


def _read_command(args: argparse.Namespace, action: str) -> int:
    require_root()
    runner = Runner(verbose=args.verbose)
    target_device = find_device(args.target, runner)
    with open_media(args.target, runner, readonly=True) as paths:
        if action == "verify":
            problems = verify(paths)
            payload = {"ok": not problems, "problems": problems}
        else:
            payload = inspect_media(paths, full_hash=action == "inspect")
            payload["device"] = _device_dict(target_device, set())
            if action == "list":
                payload = payload["isos"]
    if args.json:
        print(json.dumps(payload, indent=2))
    elif action == "verify":
        if payload["ok"]: print("Verification passed: manifest, files, local hashes, loader, and generated menu are consistent.")
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
            for source in args.isos:
                _, match = inspect_iso(source, runner)
                if not match: raise FlexBootError(f"Unsupported ISO: {source}")
                matches.append({"file": str(source), "profile": match.profile})
            print(json.dumps({"action": action, "target": str(args.target), "isos": matches, "persistent_changes": False}, indent=2) if args.json else "Dry run passed; supported ISO(s) would be copied. No changes made.")
        else:
            print(json.dumps({"action": action, "target": str(args.target), "persistent_changes": False}, indent=2) if args.json else f"Dry run: would {action} {args.target}. No changes made.")
        return 0
    require_root()
    with open_media(args.target, runner) as paths:
        if action == "add":
            for source in args.isos:
                record = add_iso(paths, source, runner); print(f"Added {record.filename} ({record.profile})")
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
        try:
            create_sparse(args.path, size, runner=runner)
            with attached_image(args.path, runner) as target:
                assert_loop_target(target.device)
                build_attached(target.device, runner)
        except BaseException:
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
    except FlexBootError as exc:
        print(f"flexboot: {exc}", file=sys.stderr); return 2
