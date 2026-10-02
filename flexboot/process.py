"""Small, auditable subprocess boundary."""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .errors import DependencyError, FlexBootError


@dataclass
class Runner:
    dry_run: bool = False
    verbose: bool = False
    planned: list[list[str]] = field(default_factory=list)

    def require(self, command: str) -> str:
        found = shutil.which(command)
        if not found:
            raise DependencyError(f"Required command not found: {command}")
        return found

    def run(
        self,
        argv: Iterable[str | Path],
        *,
        check: bool = True,
        capture: bool = True,
        input_text: str | None = None,
        mutate: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        args = [str(value) for value in argv]
        self.planned.append(args)
        if mutate and self.dry_run:
            return subprocess.CompletedProcess(args, 0, "", "")
        try:
            return subprocess.run(
                args,
                check=check,
                text=True,
                input=input_text,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE if capture else None,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise DependencyError(f"Required command not found: {args[0]}") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise FlexBootError(f"Command failed ({exc.returncode}): {' '.join(args)}" + (f"\n{detail}" if detail else "")) from exc

