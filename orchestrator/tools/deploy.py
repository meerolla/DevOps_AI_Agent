from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


def _argocd_source_info(app_manifest: Path) -> tuple[str, str] | None:
    if not app_manifest.exists():
        return None
    payload = yaml.safe_load(app_manifest.read_text(encoding="utf-8"))
    source = (((payload or {}).get("spec") or {}).get("source") or {})
    revision = str(source.get("targetRevision") or "main").strip() or "main"
    path = str(source.get("path") or "deploy/helm").strip() or "deploy/helm"
    return revision, path


def _resolve_git_ref(repo_path: Path, revision: str) -> str | None:
    candidates = [revision, f"origin/{revision}"]
    for ref in candidates:
        ok, _ = run_command(f"git rev-parse --verify {ref}", cwd=repo_path)
        if ok:
            return ref
    return None


def _ensure_gitops_source_exists(repo_path: Path, app_manifest: Path) -> tuple[bool, str]:
    source = _argocd_source_info(app_manifest)
    if source is None:
        return False, "ArgoCD application manifest not found"

    revision, path = source
    run_command("git fetch --all --prune", cwd=repo_path)
    ref = _resolve_git_ref(repo_path, revision)
    if ref is None:
        return False, f"artifacts_not_on_target_revision: revision '{revision}' not found"

    ok_tree, tree_output = run_command(f"git ls-tree --name-only {ref} {path}", cwd=repo_path)
    if not ok_tree or not tree_output.strip():
        return False, f"artifacts_not_on_target_revision: '{path}' not found at '{revision}'"
    return True, "ok"


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
            f"helm upgrade --install {app_name} ./deploy/helm --namespace {namespace} --create-namespace "
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

    app_manifest = repo_path / "deploy" / "argocd" / "application.yaml"
    source_ok, source_message = _ensure_gitops_source_exists(repo_path, app_manifest)
    if not source_ok:
        return ToolResult(
            ok=False,
            step="deploy",
            details="artifacts_not_on_target_revision",
            output=f"{helm_output}\n{source_message}",
            artifact_ref=None,
        )

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
