#!/usr/bin/env python3
"""Capture the real GRUB theme in QEMU, using illustrative ISO menu entries.

Requires host GRUB, mkfs.ext4, QEMU and OVMF. Runs unprivileged, touches only
temporary regular files, and does not test ISO boot compatibility.
"""
from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flexboot.doctor import find_ovmf
from flexboot.grub import base_config, generated_config, validate_config
from flexboot.manifest import ISORecord
from flexboot.media import deploy_theme


def qmp_command(stream, command: str, arguments: dict | None = None) -> dict:
    stream.write((json.dumps({"execute": command, "arguments": arguments or {}}) + "\n").encode())
    stream.flush()
    while True:
        line = stream.readline()
        if not line:
            raise RuntimeError("QEMU closed its monitor connection")
        response = json.loads(line)
        if "error" in response:
            raise RuntimeError(str(response["error"]))
        if "return" in response:
            return response["return"]


def capture(args: argparse.Namespace) -> None:
    if not args.firmware or not Path(args.firmware).is_file():
        raise RuntimeError("Specify an OVMF CODE firmware file with --firmware")
    variables = Path(args.firmware).with_name(Path(args.firmware).name.replace("CODE", "VARS"))
    if not variables.is_file() or variables == Path(args.firmware):
        raise RuntimeError("OVMF CODE firmware needs its matching VARS file alongside it")
    for command in (args.qemu, "grub-mkstandalone", "mkfs.ext4"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing command: {command}")
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError(f"Refusing to overwrite {output}")

    with tempfile.TemporaryDirectory(prefix="flexboot-capture-") as raw:
        work = Path(raw)
        media = work / "media"
        deploy_theme(media)
        uuid = "47ab4ee9-ced8-4a70-af6b-3f9ce4e0dd34"
        records = [
            ISORecord("ubuntu-desktop.iso", 0, "0" * 64, "ubuntu-casper", "/casper/vmlinuz", "/casper/initrd"),
            ISORecord("kali-live.iso", 0, "0" * 64, "debian-live", "/live/vmlinuz", "/live/initrd.img"),
            ISORecord("debian-live.iso", 0, "0" * 64, "debian-live", "/live/vmlinuz", "/live/initrd.img"),
            ISORecord("clonezilla-live.iso", 0, "0" * 64, "clonezilla-live", "/live/vmlinuz", "/live/initrd.img"),
        ]
        config = media / "boot/grub/grub.cfg"
        # The standalone EFI application's memdisk replaces the ESP for this
        # visual fixture. Everything after root selection is production config.
        config.write_text("set root=(memdisk)\n" + base_config(uuid))
        menu = media / "boot/grub/generated.cfg"
        menu.write_text(generated_config(records))
        validate_config(config)
        validate_config(menu)
        efi = work / "esp/EFI/BOOT/BOOTX64.EFI"
        efi.parent.mkdir(parents=True)
        grafts = [f"{path.relative_to(media)}={path}" for path in sorted(media.rglob("*")) if path.is_file()]
        subprocess.run(["grub-mkstandalone", "-O", "x86_64-efi", "--locales=", "--themes=", "-o", str(efi), *grafts], check=True)
        data = work / "data.img"
        with data.open("xb") as handle:
            handle.truncate(64 * 1024 * 1024)
        subprocess.run(["mkfs.ext4", "-q", "-F", "-U", uuid, str(data)], check=True)

        monitor = work / "qmp.sock"
        writable_variables = work / "OVMF_VARS.fd"
        shutil.copyfile(variables, writable_variables)
        command = [args.qemu, "-machine", "q35,accel=tcg", "-m", "512",
                   "-drive", f"if=pflash,format=raw,readonly=on,file={args.firmware}",
                   "-drive", f"if=pflash,format=raw,file={writable_variables}",
                   "-display", "none", "-vga", "none",
                   "-device", "VGA,xres=1920,yres=1080", "-nic", "none",
                   "-serial", "none", "-monitor", "none", "-no-reboot",
                   "-drive", f"file=fat:ro:{work / 'esp'},format=raw,if=ide,snapshot=on",
                   "-drive", f"file={data},format=raw,if=virtio,readonly=on",
                   "-qmp", f"unix:{monitor},server=on,wait=off"]
        if args.qemu_data:
            command += ["-L", str(args.qemu_data)]
        with (work / "qemu.log").open("w+") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(10)
                    deadline = time.monotonic() + 15
                    while True:
                        if process.poll() is not None or time.monotonic() > deadline:
                            log.seek(0)
                            raise RuntimeError("QEMU did not start: " + log.read())
                        try:
                            connection.connect(str(monitor))
                            break
                        except (FileNotFoundError, ConnectionRefusedError):
                            time.sleep(0.1)
                    with connection.makefile("rwb") as stream:
                        json.loads(stream.readline())  # QMP greeting
                        qmp_command(stream, "qmp_capabilities")
                        time.sleep(args.wait)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        qmp_command(stream, "screendump", {"filename": str(output), "format": "png"})
                        qmp_command(stream, "quit")
                process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    print(f"Captured {output}; visually verify the menu before publication.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new PNG output file")
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    parser.add_argument("--firmware", default=find_ovmf())
    parser.add_argument("--qemu-data", type=Path, help="optional QEMU firmware/ROM directory")
    parser.add_argument("--wait", type=int, choices=range(5, 61), default=20, metavar="5..60", help="seconds to wait for GRUB")
    capture(parser.parse_args())


if __name__ == "__main__":
    main()
