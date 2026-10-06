"""Small read-only ISO 9660/Joliet reader used when host tools are absent.

It intentionally implements only directory walking and bounded file reads.
Booting, extraction, Rock Ridge permissions, and image modification are out of
scope. Official images from the supported families provide ISO 9660 or Joliet
names for the paths FlexBoot inspects.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import FlexBootError


SECTOR = 2048


@dataclass(frozen=True)
class Entry:
    path: str
    extent: int
    size: int
    directory: bool


class ISO9660Reader:
    def __init__(self, path: Path):
        self.path = path
        self._handle = path.open("rb")
        try:
            self.volume_id, self._root, self._joliet = self._read_descriptors()
        except BaseException:
            self._handle.close()
            raise

    def __enter__(self) -> "ISO9660Reader":
        return self

    def __exit__(self, *_: object) -> None:
        self._handle.close()

    def _read_descriptors(self) -> tuple[str, bytes, bool]:
        primary: bytes | None = None
        joliet: bytes | None = None
        for sector in range(16, 256):
            self._handle.seek(sector * SECTOR)
            descriptor = self._handle.read(SECTOR)
            if len(descriptor) != SECTOR or descriptor[1:6] != b"CD001":
                raise FlexBootError(f"Invalid ISO 9660 descriptor in {self.path}")
            kind = descriptor[0]
            if kind == 1:
                primary = descriptor
            elif kind == 2 and descriptor[88:91] in (b"%/@", b"%/C", b"%/E"):
                joliet = descriptor
            elif kind == 255:
                break
        if primary is None:
            raise FlexBootError(f"ISO has no primary volume descriptor: {self.path}")
        chosen = joliet or primary
        volume_id = primary[40:72].decode("ascii", "replace").rstrip(" \0")
        return volume_id, chosen[156:190], joliet is not None

    @staticmethod
    def _numbers(record: bytes) -> tuple[int, int, bool]:
        return (
            int.from_bytes(record[2:6], "little"),
            int.from_bytes(record[10:14], "little"),
            bool(record[25] & 2),
        )

    def _name(self, raw: bytes) -> str:
        if raw in (b"\0", b"\1"):
            return "." if raw == b"\0" else ".."
        name = raw.decode("utf-16-be" if self._joliet else "ascii", "replace")
        return name.rsplit(";", 1)[0]

    def entries(self, limit: int = 200_000) -> list[Entry]:
        root_extent, root_size, _ = self._numbers(self._root)
        pending = [("", root_extent, root_size)]
        visited: set[tuple[int, int]] = set()
        result: list[Entry] = []
        while pending:
            parent, extent, size = pending.pop()
            if size > 64 * 1024 * 1024:
                raise FlexBootError(f"ISO directory exceeds the 64 MiB inspection limit: {self.path}")
            if extent < 0 or extent * SECTOR + size > self.path.stat().st_size:
                raise FlexBootError(f"ISO directory extent is outside the image: {self.path}")
            if (extent, size) in visited:
                continue
            visited.add((extent, size))
            self._handle.seek(extent * SECTOR)
            data = self._handle.read(size)
            offset = 0
            while offset < len(data):
                length = data[offset]
                if length == 0:
                    offset = ((offset // SECTOR) + 1) * SECTOR
                    continue
                record = data[offset:offset + length]
                if len(record) < 34:
                    raise FlexBootError(f"Malformed ISO directory record in {self.path}")
                name_length = record[32]
                name = self._name(record[33:33 + name_length])
                child_extent, child_size, directory = self._numbers(record)
                if name not in (".", ".."):
                    child_path = f"{parent}/{name}"
                    entry = Entry(child_path, child_extent, child_size, directory)
                    result.append(entry)
                    if len(result) > limit:
                        raise FlexBootError(f"ISO contains more than {limit} directory entries")
                    if directory:
                        pending.append((child_path, child_extent, child_size))
                offset += length
        return result

    def read(self, entry: Entry, maximum: int = 256 * 1024) -> str:
        if entry.directory or entry.size > maximum:
            return ""
        self._handle.seek(entry.extent * SECTOR)
        return self._handle.read(entry.size).decode("utf-8", "replace")
