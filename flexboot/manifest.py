"""Operational media manifest and integrity helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
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
        for path in (self.kernel, *initrds, self.configfile):
            if path and (not re.fullmatch(r"/[A-Za-z0-9_./+@:-]+", path) or ".." in path.split("/")):
                raise FlexBootError("Unsafe boot resource path in manifest")
        if not isinstance(args, str) or not re.fullmatch(r"[A-Za-z0-9_ =.,:+/@-]*", args.replace("${iso_path}", "")):
            raise FlexBootError("Unsafe boot arguments in manifest")
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
            if not isinstance(raw, dict):
                raise ValueError("expected a JSON object")
            if raw.get("schema_version") not in (1, 2) or not isinstance(raw.get("isos"), list):
                raise ValueError("unsupported schema or invalid isos list")
            records = []
            for item in raw.pop("isos"):
                if not isinstance(item, dict):
                    raise ValueError("expected an ISO record object")
                if "initrds" in item:
                    if not isinstance(item["initrds"], list) or not all(isinstance(value, str) for value in item["initrds"]):
                        raise ValueError("invalid initrds")
                    item["initrds"] = tuple(item["initrds"])
                record = ISORecord(**item)
                from .iso import validate_filename
                validate_filename(record.filename)
                if type(record.size) is not int or record.size < 0 or not isinstance(record.sha256, str) or not re.fullmatch("[0-9a-f]{64}", record.sha256):
                    raise ValueError("invalid size or SHA-256")
                if record.profile not in {"ubuntu-casper", "ubuntu-server-casper", "debian-live", "clonezilla-live", "rescuezilla", "fedora-live", "systemrescue", "archiso"}:
                    raise ValueError("unknown boot profile")
                if not all(isinstance(value, str) for value in (record.filename, record.kernel, record.initrd, record.boot_kind, record.boot_args, record.configfile)) or type(record.remove_tpm_module) is not bool:
                    raise ValueError("invalid boot record types")
                record.boot_plan()
                records.append(record)
            if len({record.filename for record in records}) != len(records):
                raise ValueError("duplicate ISO records")
            if not isinstance(raw.get("data_filesystem_uuid"), str) or not raw["data_filesystem_uuid"]:
                raise ValueError("missing data UUID")
            raw["schema_version"] = 2
            return cls(**raw, isos=records)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise FlexBootError(f"Malformed manifest {path}: {exc}") from exc

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_utc = utc_now()
        data = asdict(self)
        from .grub import atomic_text
        atomic_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


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
    fd, raw = tempfile.mkstemp(prefix=f".{destination.name}.partial-", dir=destination.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as dst, source.open("rb") as src:
            before = os.fstat(src.fileno())
            for chunk in iter(lambda: src.read(4 * 1024 * 1024), b""):
                dst.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                if progress:
                    progress(copied, total)
            dst.flush()
            os.fsync(dst.fileno())
            after = os.fstat(src.fileno())
            if copied != before.st_size or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise FlexBootError("Source ISO changed while copying")
        temporary.chmod(0o644)
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
