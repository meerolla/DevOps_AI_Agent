from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from orchestrator.tools._shell import is_sandbox, run_command


_GIT_NON_INTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GCM_INTERACTIVE": "Never",
}


def _is_probable_git_auth_failure(output: str) -> bool:
    text = output.lower()
    markers = [
        "authentication failed",
        "could not read username",
        "could not read password",
        "terminal prompts disabled",
        "permission denied",
        "repository not found",
        "fatal: unable to access",
    ]
    return any(marker in text for marker in markers)


def _auth_remediation_message(remote: str) -> str:
    remote_type = "https" if remote.startswith("http") else "ssh" if remote.startswith("git@") else "unknown"
    return (
        "git push preflight failed in non-interactive mode. "
        f"Remote type: {remote_type}. "
        "Ensure credentials are configured in the same shell/session where orchestrator runs. "
        "If using HTTPS, provide repo write access with a token-backed credential helper. "
        "If using SSH, ensure the SSH key is loaded and authorized for the repository. "
        "If GITHUB_TOKEN was exported in a different shell/repo context, export it again before running orchestrator."
    )


def auto_commit_generated_artifacts(repo_path: Path, paths: Iterable[Path], message: str) -> tuple[bool, str]:
    if is_sandbox():
        return True, "sandbox auto-commit skipped"

    relative_paths = [str(p.relative_to(repo_path)).replace('\\', '/') for p in paths]
    add_cmd = "git add " + " ".join(relative_paths)

    ok_add, out_add = run_command(add_cmd, cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok_add:
        return False, out_add

    ok_commit, out_commit = run_command(f'git commit -m "{message}"', cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok_commit:
        if "nothing to commit" in out_commit.lower():
            return True, "nothing to commit"
        return False, out_commit

    return True, out_commit


def _detect_default_branch(repo_path: Path) -> tuple[bool, str]:
    ok, output = run_command("git symbolic-ref refs/remotes/origin/HEAD", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if ok and output.strip():
        # output like: refs/remotes/origin/main
        return True, output.strip().split("/")[-1]
    # fallback to common default branch
    ok_main, _ = run_command("git rev-parse --verify origin/main", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if ok_main:
        return True, "main"
    ok_master, _ = run_command("git rev-parse --verify origin/master", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if ok_master:
        return True, "master"
    return False, "could not detect default branch"


def create_draft_pr_for_generated_artifacts(
    repo_path: Path,
    branch_name: str,
    title: str,
    body: str,
) -> tuple[bool, str]:
    if is_sandbox():
        return True, "sandbox draft-pr skipped"

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        return (
            False,
            "GITHUB_TOKEN (or GH_TOKEN) is required to create a draft PR. "
            "Export it in the same shell/session where orchestrator runs.",
        )

    ok_remote, remote_url = run_command("git remote get-url origin", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok_remote:
        return False, remote_url
    remote = remote_url.strip()

    ok_branch, out_branch = run_command(f"git checkout -b {branch_name}", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok_branch and "already exists" not in out_branch.lower():
        return False, out_branch
    if "already exists" in out_branch.lower():
        ok_switch, out_switch = run_command(f"git checkout {branch_name}", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
        if not ok_switch:
            return False, out_switch

    ok_preflight, out_preflight = run_command(
        f"git push --dry-run -u origin {branch_name}",
        cwd=repo_path,
        env=_GIT_NON_INTERACTIVE_ENV,
    )
    if not ok_preflight:
        if _is_probable_git_auth_failure(out_preflight):
            return False, f"{_auth_remediation_message(remote)}\n\nGit output:\n{out_preflight}"
        return False, out_preflight

    ok_push, out_push = run_command(
        f"git push -u origin {branch_name}",
        cwd=repo_path,
        env=_GIT_NON_INTERACTIVE_ENV,
    )
    if not ok_push:
        if _is_probable_git_auth_failure(out_push):
            return False, f"{_auth_remediation_message(remote)}\n\nGit output:\n{out_push}"
        return False, out_push

    ok_default, default_branch = _detect_default_branch(repo_path)
    if not ok_default:
        return False, default_branch

    owner_repo = ""
    if remote.startswith("git@github.com:"):
        owner_repo = remote.replace("git@github.com:", "").replace(".git", "")
    elif "github.com/" in remote:
        owner_repo = remote.split("github.com/")[-1].replace(".git", "")
    if not owner_repo or "/" not in owner_repo:
        return False, f"could not parse GitHub owner/repo from origin URL: {remote}"

    payload = json.dumps(
        {
            "title": title,
            "head": branch_name,
            "base": default_branch,
            "body": body,
            "draft": True,
        }
    )
    api_url = f"https://api.github.com/repos/{owner_repo}/pulls"
    cmd = (
        "curl -sS -X POST "
        f"-H \"Authorization: Bearer {token}\" "
        "-H \"Accept: application/vnd.github+json\" "
        f"{api_url} "
        f"-d '{payload}'"
    )
    ok_pr, out_pr = run_command(cmd, cwd=repo_path)
    if not ok_pr:
        return False, out_pr

    try:
        data = json.loads(out_pr)
    except Exception:
        return False, out_pr

    if "html_url" in data:
        return True, data["html_url"]
    message = data.get("message", "unknown GitHub API error")
    return False, message


def set_github_repo_variables(repo_path: Path, cluster: str, namespace: str) -> list[str]:
    """Create or update GitHub Actions repository variables KUBE_CONTEXT and DEPLOY_NAMESPACE.

    Returns a list of warning strings for any variable that could not be set (caller should log them).
    On sandbox, skips all API calls and returns an empty list.
    """
    if is_sandbox():
        return []

    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        return [
            "⚠ GITHUB_TOKEN not set — skipping GitHub variable provisioning. "
            "Set variables manually: Settings → Secrets and variables → Actions → Variables: "
            f"KUBE_CONTEXT = {cluster} | DEPLOY_NAMESPACE = {namespace}"
        ]

    ok_remote, remote_url = run_command("git remote get-url origin", cwd=repo_path, env=_GIT_NON_INTERACTIVE_ENV)
    if not ok_remote:
        return [f"⚠ Could not determine git remote: {remote_url}"]

    remote = remote_url.strip()
    owner_repo = ""
    if remote.startswith("git@github.com:"):
        owner_repo = remote.replace("git@github.com:", "").replace(".git", "")
    elif "github.com/" in remote:
        owner_repo = remote.split("github.com/")[-1].replace(".git", "")
    if not owner_repo or "/" not in owner_repo:
        return [f"⚠ Could not parse GitHub owner/repo from remote: {remote}"]

    warnings: list[str] = []
    variables = {"KUBE_CONTEXT": cluster, "DEPLOY_NAMESPACE": namespace}

    for name, value in variables.items():
        base_url = f"https://api.github.com/repos/{owner_repo}/actions/variables"
        auth_header = f"-H \"Authorization: Bearer {token}\""
        accept_header = "-H \"Accept: application/vnd.github+json\""

        # Check if variable already exists
        ok_get, out_get = run_command(
            f"curl -sS -o /dev/null -w \"%{{http_code}}\" {auth_header} {accept_header} {base_url}/{name}",
            cwd=repo_path,
        )
        exists = ok_get and out_get.strip() == "200"

        if exists:
            payload = json.dumps({"value": value})
            ok_set, out_set = run_command(
                f"curl -sS -X PATCH {auth_header} {accept_header} {base_url}/{name} -d '{payload}'",
                cwd=repo_path,
            )
        else:
            payload = json.dumps({"name": name, "value": value})
            ok_set, out_set = run_command(
                f"curl -sS -X POST {auth_header} {accept_header} {base_url} -d '{payload}'",
                cwd=repo_path,
            )

        if not ok_set:
            warnings.append(
                f"⚠ Could not set GitHub variable {name}. "
                f"Set it manually: Settings → Secrets and variables → Actions → Variables → "
                f"New variable: {name} = {value}"
            )
            continue

        # A successful PATCH returns 204 (no body); POST returns 201 with body
        try:
            if out_set.strip():
                parsed = json.loads(out_set)
                if "message" in parsed:
                    warnings.append(
                        f"⚠ Could not set GitHub variable {name} ({parsed['message']}). "
                        f"Set it manually: Settings → Secrets and variables → Actions → Variables → "
                        f"New variable: {name} = {value}"
                    )
        except Exception:
            pass  # empty body on 204 is expected

    return warnings
