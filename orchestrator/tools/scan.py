from __future__ import annotations

import os
from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def scan_image(repo_path: Path, image_ref: str) -> ToolResult:
    if os.getenv("FORCE_SCAN_FAIL", "0") == "1":
        return ToolResult(ok=False, step="scan", details="forced scan failure", output="forced")

    if is_sandbox():
        return ToolResult(ok=True, step="scan", details="sandbox scan clean", output="no findings")

    ok, output = run_command(f"trivy image --severity HIGH,CRITICAL {image_ref}", cwd=repo_path)
    return ToolResult(ok=ok, step="scan", details="trivy scan executed", output=output)
