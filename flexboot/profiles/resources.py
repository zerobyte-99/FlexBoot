"""Deterministic resource selection shared by related live profiles."""
from __future__ import annotations

import re


def live_kernel_pair(paths: frozenset[str]) -> tuple[str, str] | None:
    pairs = []
    for kernel in sorted(paths):
        if not re.fullmatch(r"/live/vmlinuz(?:[-.][A-Za-z0-9_.+-]+)?", kernel):
            continue
        suffix = kernel.removeprefix("/live/vmlinuz")
        initrd = next((path for path in (f"/live/initrd.img{suffix}", f"/live/initrd{suffix}") if path in paths), None)
        if initrd:
            pairs.append((kernel, initrd))
    canonical = next((pair for pair in pairs if pair[0] == "/live/vmlinuz"), None)
    return canonical or (pairs[0] if len(pairs) == 1 else None)
