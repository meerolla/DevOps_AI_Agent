from __future__ import annotations

import json
import os
from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def build_infra_plan(namespace: str, secret_names: list[str]) -> str:
    secrets = ", ".join(secret_names) if secret_names else "none"
    return f"Create/ensure namespace={namespace}; ensure imagePullSecrets={secrets}"


def _dockerconfigjson() -> str:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GHCR_TOKEN", "")
    payload = {
        "auths": {
            "ghcr.io": {
                "username": "oauth2",
                "password": token,
                "auth": "",
            }
        }
    }
    return json.dumps(payload)


def provision_infra(
    repo_path: Path,
    cluster: str,
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

    outputs: list[str] = []

    ns_ok, ns_output = run_command(
        f"kubectl --context {cluster} create namespace {namespace} --dry-run=client -o yaml | kubectl --context {cluster} apply -f -",
        cwd=repo_path,
    )
    outputs.append(ns_output)
    if not ns_ok:
        return ToolResult(ok=False, step="provision", details="namespace apply failed", output="\n".join(outputs))

    for secret_name in secret_names:
        secret_ok, secret_output = run_command(
            (
                f"kubectl --context {cluster} -n {namespace} create secret generic {secret_name} "
                f"--from-literal=.dockerconfigjson='{_dockerconfigjson()}' "
                "--type=kubernetes.io/dockerconfigjson --dry-run=client -o yaml "
                f"| kubectl --context {cluster} -n {namespace} apply -f -"
            ),
            cwd=repo_path,
        )
        outputs.append(secret_output)
        if not secret_ok:
            return ToolResult(ok=False, step="provision", details="secret apply failed", output="\n".join(outputs))

    merged_output = f"{plan}\n" + "\n".join(outputs)
    return ToolResult(ok=True, step="provision", details="infra provision command executed", output=merged_output)
