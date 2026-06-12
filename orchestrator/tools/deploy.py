from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def deploy(repo_path: Path, image_ref: str, namespace: str, approved: bool) -> ToolResult:
    if not approved:
        return ToolResult(
            ok=False,
            step="deploy",
            details="approval_required",
            output="Refusing deploy without deploy approval",
        )

    if is_sandbox():
        return ToolResult(
            ok=True,
            step="deploy",
            details="sandbox deploy succeeded",
            output=f"Deployed {image_ref} to {namespace}",
            artifact_ref="manifests://sandbox",
        )

    ok, output = run_command(f"helm upgrade --install app ./chart --namespace {namespace}", cwd=repo_path)
    return ToolResult(
        ok=ok,
        step="deploy",
        details="deploy command executed",
        output=output,
        artifact_ref="manifests://helm" if ok else None,
    )
