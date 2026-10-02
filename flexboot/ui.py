from __future__ import annotations

import os
import sys
from typing import TextIO


class UI:
    def __init__(self, stream: TextIO = sys.stdout):
        self.stream = stream
        self.color = stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"

    def style(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def heading(self, text: str) -> None:
        print(self.style(text, "1;38;5;214"), file=self.stream)

    def ok(self, text: str) -> None:
        print(self.style("[OK]", "32") + " " + text, file=self.stream)

    def warn(self, text: str) -> None:
        print(self.style("[MISSING]", "33") + " " + text, file=self.stream)

    def banner(self, name: str, tagline: str) -> None:
        width = 48
        print("╭" + "─" * (width - 2) + "╮", file=self.stream)
        print("│" + name.center(width - 2) + "│", file=self.stream)
        print("│" + tagline.center(width - 2) + "│", file=self.stream)
        print("╰" + "─" * (width - 2) + "╯", file=self.stream)

