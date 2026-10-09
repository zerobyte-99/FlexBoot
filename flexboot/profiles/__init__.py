from __future__ import annotations

from .archiso import ArchisoProfile
from .base import ISOInspection, ProfileMatch
from .clonezilla import ClonezillaProfile
from .debian_live import DebianLiveProfile
from .fedora_live import FedoraLiveProfile
from .rescuezilla import RescuezillaProfile
from .systemrescue import SystemRescueProfile
from .ubuntu_casper import UbuntuCasperProfile
from .gentoo_live import GentooLiveProfile
from .grml import GrmlLiveProfile

PROFILES = (
    GrmlLiveProfile(), GentooLiveProfile(), SystemRescueProfile(), ArchisoProfile(), RescuezillaProfile(), ClonezillaProfile(),
    FedoraLiveProfile(), UbuntuCasperProfile(), DebianLiveProfile(),
)


def detect_profile(value: set[str] | ISOInspection) -> ProfileMatch | None:
    if isinstance(value, ISOInspection):
        inspection = ISOInspection(
            frozenset("/" + path.lstrip("/") for path in value.paths),
            value.volume_id,
            {"/" + path.lstrip("/"): text for path, text in value.text_files.items()},
            {"/" + path.lstrip("/"): arch for path, arch in value.kernel_architectures.items()},
        )
    else:
        inspection = ISOInspection(frozenset("/" + path.lstrip("/") for path in value))
    for profile in PROFILES:
        match = profile.detect(inspection)
        if match:
            if match.boot.kind == "linux" and inspection.kernel_architectures.get(match.kernel) == "x86":
                return None
            return match
    return None


def supported_descriptions() -> list[str]:
    return [profile.description for profile in PROFILES]


def known_profile_ids() -> set[str]:
    return {name for profile in PROFILES for name in (profile.profile_id, *getattr(profile, "aliases", ()))}
