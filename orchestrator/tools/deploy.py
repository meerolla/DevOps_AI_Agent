from __future__ import annotations

import shutil
from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def deploy(
    repo_path: Path,
    image_ref: str,
    namespace: str,
    cluster: str,
    app_name: str,
    approved: bool,
) -> ToolResult:
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

    repo, tag = image_ref.rsplit(":", 1) if ":" in image_ref else (image_ref, "latest")
    helm_ok, helm_output = run_command(
        (
            f"helm upgrade --install {app_name} ./helm --namespace {namespace} --create-namespace "
            f"--kube-context {cluster} --set image.repository={repo} --set image.tag={tag}"
        ),
        cwd=repo_path,
    )
    if not helm_ok:
        return ToolResult(
            ok=False,
            step="deploy",
            details="helm deploy failed",
            output=helm_output,
            artifact_ref=None,
        )

    app_manifest = repo_path / "argocd" / "application.yaml"
    kubectl_ok, kubectl_output = run_command(
        f"kubectl --context {cluster} apply -f {app_manifest}",
        cwd=repo_path,
    )
    if not kubectl_ok:
        return ToolResult(
            ok=False,
            step="deploy",
            details="argocd application apply failed",
            output=f"{helm_output}\n{kubectl_output}",
            artifact_ref=None,
        )

    # If argocd CLI is unavailable, rely on automated sync policy in the Application manifest.
    # This keeps local environments functional while still applying the ArgoCD resource.
    if shutil.which("argocd") is None:
        output = (
            f"{helm_output}\n{kubectl_output}\n"
            "argocd CLI not found; skipping manual app sync and relying on ArgoCD automated sync policy"
        )
        return ToolResult(
            ok=True,
            step="deploy",
            details="deploy executed without argocd cli",
            output=output,
            artifact_ref="manifests://helm-argocd",
        )

    sync_ok, sync_output = run_command(f"argocd app sync {app_name} --grpc-web", cwd=repo_path)
    output = f"{helm_output}\n{kubectl_output}\n{sync_output}"
    return ToolResult(
        ok=sync_ok,
        step="deploy",
        details="deploy command executed",
        output=output,
        artifact_ref="manifests://helm-argocd" if sync_ok else None,
    )
