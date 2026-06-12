from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def healthcheck(repo_path: Path, cluster: str, namespace: str, app_name: str) -> ToolResult:
    if is_sandbox():
        return ToolResult(ok=True, step="healthcheck", details="sandbox healthcheck passed", output="healthy")

    rollout_ok, rollout_output = run_command(
        f"kubectl --context {cluster} -n {namespace} rollout status deploy/{app_name} --timeout=180s",
        cwd=repo_path,
    )
    if rollout_ok:
        return ToolResult(ok=True, step="healthcheck", details="deployment ready", output=rollout_output)

    pods_ok, pods_output = run_command(
        f"kubectl --context {cluster} -n {namespace} get pods -o wide",
        cwd=repo_path,
    )
    describe_ok, describe_output = run_command(
        f"kubectl --context {cluster} -n {namespace} describe deploy {app_name}",
        cwd=repo_path,
    )
    events_ok, events_output = run_command(
        f"kubectl --context {cluster} -n {namespace} get events --sort-by=.metadata.creationTimestamp",
        cwd=repo_path,
    )

    diagnostics = [f"rollout:\n{rollout_output}"]
    if pods_ok:
        diagnostics.append(f"pods:\n{pods_output}")
    if describe_ok:
        diagnostics.append(f"deployment describe:\n{describe_output}")
    if events_ok:
        diagnostics.append(f"events:\n{events_output}")

    return ToolResult(
        ok=False,
        step="healthcheck",
        details="deployment not ready",
        output="\n\n".join(diagnostics),
    )
