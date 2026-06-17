from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path
from urllib.parse import urlsplit

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command


_GIT_NON_INTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "Never",
}


def build_infra_plan(namespace: str, secret_names: list[str]) -> str:
    secrets = ", ".join(secret_names) if secret_names else "none"
    return f"Create/ensure namespace={namespace}; ensure imagePullSecrets={secrets}; ensure ArgoCD repository access"


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


def _resolve_origin_https_url(repo_path: Path) -> tuple[bool, str]:
    ok, output = run_command("git remote get-url origin", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok:
        return False, f"failed to resolve git origin: {output.strip()}"

    remote = output.strip()
    if not remote:
        return False, "git origin URL is empty"

    if remote.startswith("https://"):
        return True, remote
    if remote.startswith("http://"):
        return True, "https://" + remote[len("http://"):]

    if remote.startswith("git@") and ":" in remote:
        host_part, repo_part = remote.split(":", 1)
        host = host_part.split("@", 1)[1]
        return True, f"https://{host}/{repo_part}"

    if remote.startswith("ssh://"):
        parsed = urlsplit(remote)
        if parsed.hostname:
            path = parsed.path.lstrip("/")
            return True, f"https://{parsed.hostname}/{path}"

    return False, f"unsupported git origin URL format: {remote}"


def _is_repo_publicly_readable(repo_path: Path, repo_url: str) -> tuple[bool, str]:
    cmd = f"git ls-remote {shlex.quote(repo_url)} HEAD"
    return run_command(cmd, cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)


def _argocd_repo_secret_name(repo_url: str) -> str:
    digest = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:12]
    return f"argocd-repo-{digest}"


def _resolve_repo_credentials() -> tuple[str, str]:
    username = (os.getenv("ARGOCD_REPO_USERNAME") or os.getenv("GITHUB_USER") or "").strip()
    token = (os.getenv("ARGOCD_REPO_TOKEN") or os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    if token and not username:
        username = "oauth2"
    return username, token


def _argocd_repo_secret_exists(repo_path: Path, cluster: str, secret_name: str) -> tuple[bool, str]:
    cmd = f"kubectl --context {cluster} -n argocd get secret {secret_name} -o name"
    return run_command(cmd, cwd=repo_path)


def _ensure_argocd_repo_secret(
    repo_path: Path,
    cluster: str,
    secret_name: str,
    repo_url: str,
    username: str,
    token: str,
) -> tuple[bool, str]:
    cmd = (
        f"kubectl --context {cluster} -n argocd create secret generic {secret_name} "
        "--from-literal=type=git "
        f"--from-literal=url={shlex.quote(repo_url)} "
        f"--from-literal=username={shlex.quote(username)} "
        f"--from-literal=password={shlex.quote(token)} "
        "--dry-run=client -o yaml "
        f"| kubectl --context {cluster} -n argocd label -f - argocd.argoproj.io/secret-type=repository --local -o yaml "
        f"| kubectl --context {cluster} -n argocd apply -f -"
    )
    return run_command(cmd, cwd=repo_path)


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

    outputs: list[str] = [plan]

    ns_ok, ns_output = run_command(
        f"kubectl --context {cluster} create namespace {namespace} --dry-run=client -o yaml | kubectl --context {cluster} apply -f -",
        cwd=repo_path,
    )
    if not ns_ok:
        outputs.append(ns_output.strip())
        return ToolResult(ok=False, step="provision", details="namespace apply failed", output="\n".join(outputs))
    outputs.append(f"namespace ensured: {namespace}")

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
        if not secret_ok:
            outputs.append(secret_output.strip())
            return ToolResult(ok=False, step="provision", details="secret apply failed", output="\n".join(outputs))
        outputs.append(f"image pull secret ensured: {secret_name}")

    repo_ok, repo_url_or_err = _resolve_origin_https_url(repo_path)
    if not repo_ok:
        outputs.append(repo_url_or_err)
        return ToolResult(
            ok=False,
            step="provision",
            details="argocd_repo_url_resolution_failed",
            output="\n".join(outputs),
        )

    repo_url = repo_url_or_err
    repo_secret_name = _argocd_repo_secret_name(repo_url)
    outputs.append(f"repo origin resolved: {repo_url}")
    outputs.append(f"argocd repo secret: {repo_secret_name}")

    public_ok, public_probe_output = _is_repo_publicly_readable(repo_path, repo_url)
    if public_probe_output.strip() and not public_ok:
        outputs.append(public_probe_output.strip())

    username, token = _resolve_repo_credentials()
    has_repo_creds = bool(username and token)

    if has_repo_creds:
        apply_ok, apply_output = _ensure_argocd_repo_secret(
            repo_path=repo_path,
            cluster=cluster,
            secret_name=repo_secret_name,
            repo_url=repo_url,
            username=username,
            token=token,
        )
        if not apply_ok:
            outputs.append(apply_output.strip())
            return ToolResult(
                ok=False,
                step="provision",
                details="argocd_repo_secret_apply_failed",
                output="\n".join(outputs),
            )
        outputs.append(f"argocd repo secret ensured: {repo_secret_name}")
    else:
        exists_ok, exists_output = _argocd_repo_secret_exists(repo_path, cluster, repo_secret_name)
        if exists_ok:
            outputs.append(f"argocd repo secret already exists: {repo_secret_name}")
        elif public_ok:
            outputs.append("argocd repo credentials not required: repository is publicly readable")
        else:
            if exists_output.strip():
                outputs.append(exists_output.strip())
            outputs.append(
                "set ARGOCD_REPO_USERNAME and ARGOCD_REPO_TOKEN (or GITHUB_USER with GITHUB_TOKEN/GH_TOKEN)"
            )
            return ToolResult(
                ok=False,
                step="provision",
                details="argocd_repo_credentials_missing",
                output="\n".join(outputs),
            )

    return ToolResult(ok=True, step="provision", details="infra provision command executed", output="\n".join(outputs))
