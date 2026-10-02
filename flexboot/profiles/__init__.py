from __future__ import annotations

from .archiso import ArchisoProfile
from .base import ISOInspection, ProfileMatch
from .clonezilla import ClonezillaProfile
from .debian_live import DebianLiveProfile
from .fedora_live import FedoraLiveProfile
from .rescuezilla import RescuezillaProfile
from .systemrescue import SystemRescueProfile
from .ubuntu_casper import UbuntuCasperProfile

PROFILES = (
    SystemRescueProfile(), ArchisoProfile(), RescuezillaProfile(), ClonezillaProfile(),
    FedoraLiveProfile(), UbuntuCasperProfile(), DebianLiveProfile(),
)


def detect_profile(value: set[str] | ISOInspection) -> ProfileMatch | None:
    if isinstance(value, ISOInspection):
        inspection = ISOInspection(
            frozenset("/" + path.lstrip("/") for path in value.paths),
            value.volume_id,
            {"/" + path.lstrip("/"): text for path, text in value.text_files.items()},
        )
    else:
        inspection = ISOInspection(frozenset("/" + path.lstrip("/") for path in value))
    for profile in PROFILES:
        match = profile.detect(inspection)
        if match:
            return match
    return None


def supported_descriptions() -> list[str]:
    return [profile.description for profile in PROFILES]
