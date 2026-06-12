from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def healthcheck(repo_path: Path, cluster: str, namespace: str, app_name: str) -> ToolResult:
    if is_sandbox():
        return ToolResult(ok=True, step="healthcheck", details="sandbox healthcheck passed", output="healthy")

    for _ in range(5):
        ok, output = run_command(
            f"kubectl --context {cluster} -n {namespace} get deploy {app_name} -o jsonpath='{{.status.readyReplicas}}'",
            cwd=repo_path,
        )
        if ok and output.strip() not in {"", "0"}:
            return ToolResult(ok=True, step="healthcheck", details="deployment ready", output=output)

    return ToolResult(
        ok=False,
        step="healthcheck",
        details="deployment not ready",
        output="healthcheck failed after retries",
    )
