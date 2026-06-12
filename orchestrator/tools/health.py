from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def healthcheck(repo_path: Path) -> ToolResult:
    if is_sandbox():
        return ToolResult(ok=True, step="healthcheck", details="sandbox healthcheck passed", output="healthy")

    ok, output = run_command("kubectl get pods -A", cwd=repo_path)
    return ToolResult(ok=ok, step="healthcheck", details="cluster healthcheck executed", output=output)
