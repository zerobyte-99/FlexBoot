#!/usr/bin/env python3
"""Opt-in real-ISO boot test using only disposable files and QEMU/OVMF.

Validates Linux ISO rediscovery, not the GPT/grub-install builder or hardware.
The caller supplies a serial-console success marker appropriate to the image.
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
import uuid
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flexboot.doctor import find_ovmf
from flexboot.errors import FlexBootError
from flexboot.grub import base_config, generated_config, validate_config
from flexboot.media import MediaPaths, add_iso, initialize
from flexboot.process import Runner
from tools.capture_boot_screen import qmp_command


def run_test(args: argparse.Namespace) -> None:
    code = Path(args.firmware or "").resolve()
    variables = code.with_name(code.name.replace("CODE", "VARS"))
    if not code.is_file() or not variables.is_file() or code == variables:
        raise RuntimeError("Specify OVMF CODE firmware with matching VARS alongside it")
    for command in (args.qemu, "grub-mkstandalone", "mkfs.ext4"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing command: {command}")
    source = args.iso.resolve()
    if not source.is_file():
        raise RuntimeError("Supply a regular ISO file")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    success = False
    with tempfile.TemporaryDirectory(prefix="flexboot-iso-test-") as raw:
        work = Path(raw)
        paths = MediaPaths(work / "media", work / "tree")
        identity = str(uuid.uuid4())
        initialize(paths, identity, Runner())
        record = add_iso(paths, source)
        if record.boot_kind != "linux":
            raise RuntimeError("This helper instruments Linux entries only; vendor submenus need manual testing")
        record = replace(record, boot_args=record.boot_args + " console=ttyS0,115200")
        config = paths.grub_dir / "grub.cfg"
        config.write_text("set root=(memdisk)\ninsmod serial\nserial --unit=0 --speed=115200\n"
                          "terminal_output serial\n" + base_config(identity) +
                          "terminal_output gfxterm serial\necho FLEXBOOT_ISO_TEST_READY\n")
        menu = paths.grub_dir / "generated.cfg"
        menu.write_text(generated_config([record]))
        validate_config(config)
        validate_config(menu)
        for path in (config, menu):
            shutil.copyfile(path, output / path.name)
        loader = work / "esp/EFI/BOOT/BOOTX64.EFI"
        loader.parent.mkdir(parents=True)
        grafts = [f"{path.relative_to(paths.efi)}={path}" for path in sorted(paths.efi.rglob("*")) if path.is_file()]
        subprocess.run(["grub-mkstandalone", "-O", "x86_64-efi", "--locales=", "--themes=", "-o", str(loader), *grafts], check=True)
        data = work / "data.img"
        with data.open("xb") as handle:
            handle.truncate(max(2 * 1024**3, source.stat().st_size * 2 + 512 * 1024**2))
        subprocess.run(["mkfs.ext4", "-q", "-F", "-U", identity, "-d", str(paths.data), str(data)], check=True)
        writable_variables = work / "OVMF_VARS.fd"
        shutil.copyfile(variables, writable_variables)
        monitor = work / "qmp.sock"
        serial = output / "serial.log"
        command = [args.qemu, "-machine", "q35,accel=tcg", "-m", "1536", "-display", "none", "-nic", "none", "-no-reboot",
                   "-drive", f"if=pflash,format=raw,readonly=on,file={code}",
                   "-drive", f"if=pflash,format=raw,file={writable_variables}",
                   "-drive", f"file=fat:ro:{work / 'esp'},format=raw,if=ide,snapshot=on",
                   "-drive", f"file={data},format=raw,if=virtio,snapshot=on",
                   "-serial", f"file:{serial}", "-monitor", "none",
                   "-qmp", f"unix:{monitor},server=on,wait=off"]
        if args.qemu_data:
            command += ["-L", str(args.qemu_data)]
        with (output / "qemu.log").open("w") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(10)
                    deadline = time.monotonic() + 15
                    while True:
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise RuntimeError(f"QEMU failed to start; see {output / 'qemu.log'}")
                        try:
                            connection.connect(str(monitor))
                            break
                        except (FileNotFoundError, ConnectionRefusedError):
                            time.sleep(0.1)
                    with connection.makefile("rwb") as stream:
                        json.loads(stream.readline())
                        qmp_command(stream, "qmp_capabilities")
                        deadline = time.monotonic() + args.timeout
                        while True:
                            text = serial.read_text(errors="replace") if serial.exists() else ""
                            if "FLEXBOOT_ISO_TEST_READY" in text:
                                break
                            if process.poll() is not None or time.monotonic() > deadline:
                                raise RuntimeError(f"GRUB did not reach its menu; inspect {serial}")
                            time.sleep(1)
                        time.sleep(2)
                        qmp_command(stream, "screendump", {"filename": str(output / "menu.png"), "format": "png"})
                        qmp_command(stream, "send-key", {"keys": [{"type": "qcode", "data": "ret"}]})
                        deadline = time.monotonic() + args.timeout
                        while process.poll() is None and time.monotonic() < deadline:
                            text = serial.read_text(errors="replace") if serial.exists() else ""
                            if "Kernel panic" in text:
                                break
                            if args.expect in text:
                                success = True
                                break
                            time.sleep(1)
                        if process.poll() is None:
                            qmp_command(stream, "screendump", {"filename": str(output / "screen.png"), "format": "png"})
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
    if not success:
        raise RuntimeError(f"Boot did not reach {args.expect!r}; inspect {serial}")
    print(f"PASS: serial console reached {args.expect!r}; evidence in {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    parser.add_argument("output", type=Path, help="new evidence directory")
    parser.add_argument("--expect", required=True, help="serial userspace/login marker; choose carefully")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    parser.add_argument("--qemu-data", type=Path)
    parser.add_argument("--firmware", default=find_ovmf())
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        run_test(args)
    except (FlexBootError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"ISO boot test failed: {exc}\n")


if __name__ == "__main__":
    main()
