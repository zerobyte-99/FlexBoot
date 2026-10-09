from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True)
class ISOInspection:
    """Bounded, read-only facts collected from an ISO image."""

    paths: frozenset[str]
    volume_id: str | None = None
    text_files: Mapping[str, str] = field(default_factory=dict)
    kernel_architectures: Mapping[str, str] = field(default_factory=dict)

    def combined_text(self) -> str:
        return "\n".join(self.text_files.values())


@dataclass(frozen=True)
class BootPlan:
    """A distribution-neutral recipe rendered by the GRUB backend."""

    kind: str
    kernel: str = ""
    initrds: tuple[str, ...] = ()
    args: str = ""
    configfile: str = ""
    remove_tpm_module: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {"linux", "loopback-config"}:
            raise ValueError(f"Unsupported boot plan kind: {self.kind}")
        if self.kind == "linux" and (not self.kernel or not self.initrds):
            raise ValueError("Linux boot plans require a kernel and at least one initrd")
        if self.kind == "loopback-config" and not self.configfile:
            raise ValueError("Loopback-config boot plans require a configfile")


@dataclass(frozen=True)
class ProfileMatch:
    profile: str
    description: str
    boot: BootPlan

    @property
    def kernel(self) -> str:
        return self.boot.kernel

    @property
    def initrd(self) -> str:
        return self.boot.initrds[0] if self.boot.initrds else ""

    @property
    def boot_args(self) -> str:
        return self.boot.args


class ISOProfile(Protocol):
    profile_id: str
    description: str

    def detect(self, inspection: ISOInspection) -> ProfileMatch | None: ...
