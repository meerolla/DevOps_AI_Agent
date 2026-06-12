from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def build_infra_plan(namespace: str, secret_names: list[str]) -> str:
    secrets = ", ".join(secret_names) if secret_names else "none"
    return f"Create/ensure namespace={namespace}; ensure imagePullSecrets={secrets}"


def provision_infra(
    repo_path: Path,
    namespace: str,
    secret_names: list[str],
    approved: bool,
    plan_generated: bool,
) -> ToolResult:
    if not plan_generated:
        return ToolResult(
            ok=False,
            step="provision",
            details="plan_not_generated",
            output="Refusing apply before plan",
        )
    if not approved:
        return ToolResult(
            ok=False,
            step="provision",
            details="approval_required",
            output="Refusing apply without infra approval",
        )

    plan = build_infra_plan(namespace, secret_names)
    if is_sandbox():
        return ToolResult(ok=True, step="provision", details="sandbox infra applied", output=plan)

    ok, output = run_command(f"kubectl create namespace {namespace} --dry-run=client -o yaml", cwd=repo_path)
    merged_output = f"{plan}\n{output}"
    return ToolResult(ok=ok, step="provision", details="infra provision command executed", output=merged_output)
