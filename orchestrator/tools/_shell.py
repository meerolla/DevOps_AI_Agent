from __future__ import annotations

import os
import subprocess
from pathlib import Path


def is_sandbox() -> bool:
    return os.getenv("SANDBOX", "0") == "1"


def run_command(command: str, cwd: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode == 0, proc.stdout
