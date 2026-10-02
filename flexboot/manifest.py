"""Operational media manifest and integrity helpers."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .errors import FlexBootError
from .profiles.base import BootPlan, ProfileMatch


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ISORecord:
    filename: str
    size: int
    sha256: str
    profile: str
    kernel: str = ""
    initrd: str = ""
    boot_args: str = ""
    boot_kind: str = "linux"
    initrds: tuple[str, ...] = ()
    configfile: str = ""
    remove_tpm_module: bool = False

    @classmethod
    def from_match(cls, filename: str, size: int, sha256: str, match: ProfileMatch) -> "ISORecord":
        plan = match.boot
        return cls(
            filename, size, sha256, match.profile, plan.kernel,
            plan.initrds[0] if plan.initrds else "", plan.args, plan.kind,
            plan.initrds, plan.configfile, plan.remove_tpm_module,
        )

    def boot_plan(self) -> BootPlan:
        initrds = tuple(self.initrds) or ((self.initrd,) if self.initrd else ())
        args = self.boot_args
        # Schema-1 manifests did not store boot arguments. Preserve their
        # established behavior when they are loaded and next saved.
        if not args and self.boot_kind == "linux":
            if self.profile == "ubuntu-server-casper":
                args = "iso-scan/filename=${iso_path} ---"
            elif self.profile == "ubuntu-casper":
                args = "boot=casper iso-scan/filename=${iso_path} quiet splash --"
            else:
                args = "boot=live components findiso=${iso_path}"
        return BootPlan(
            self.boot_kind, self.kernel, initrds, args,
            self.configfile, self.remove_tpm_module,
        )


@dataclass
class Manifest:
    schema_version: int = 2
    flexboot_version: str = __version__
    created_utc: str = field(default_factory=utc_now)
    updated_utc: str = field(default_factory=utc_now)
    data_filesystem_uuid: str = ""
    isos: list[ISORecord] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema_version") not in (1, 2) or not isinstance(raw.get("isos"), list):
                raise ValueError("unsupported schema or invalid isos list")
            records = []
            for item in raw.pop("isos"):
                if "initrds" in item:
                    item["initrds"] = tuple(item["initrds"])
                records.append(ISORecord(**item))
            raw["schema_version"] = 2
            return cls(**raw, isos=records)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise FlexBootError(f"Malformed manifest {path}: {exc}") from exc

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_utc = utc_now()
        data = asdict(self)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_and_hash(source: Path, destination: Path, progress: Callable[[int, int], None] | None = None) -> str:
    total = source.stat().st_size
    digest = hashlib.sha256()
    copied = 0
    temporary = destination.with_name(f".{destination.name}.partial")
    try:
        with source.open("rb") as src, temporary.open("xb") as dst:
            for chunk in iter(lambda: src.read(4 * 1024 * 1024), b""):
                dst.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                if progress:
                    progress(copied, total)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return digest.hexdigest()
