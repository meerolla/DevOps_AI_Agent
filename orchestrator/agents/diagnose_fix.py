from __future__ import annotations

from pathlib import Path

from orchestrator.llm import get_llm
from orchestrator.state import FixProposal, PipelineState, StepName

# Only these paths (relative to repo root) may be written by Diagnose-Fix.
# Application source code, tests, and orchestrator code are never touched.
OWNED_ARTIFACT_DIRS = frozenset({"helm", ".github", "argocd"})
OWNED_ARTIFACT_FILES = frozenset({"Dockerfile"})

BLOCKED_PATTERNS = (
    "@pytest.mark.skip",
    "pytest.skip(",
    "xfail",
    "assert True",
    "--severity CRITICAL",
    "--exit-code 0",
)

# Output patterns that indicate an infrastructure problem, not a generated-artifact problem.
INFRA_ERROR_PATTERNS = (
    "ImagePullBackOff",
    "ErrImagePull",
    "CrashLoopBackOff",
    "OOMKilled",
    "Evicted",
    "connection refused",
    "permission denied",
    "unauthorized",
    "forbidden",
    "no such host",
    "dial tcp",
    "context deadline exceeded",
    "certificate",
)


def _assert_owned_artifact(path: Path, repo_path: Path) -> None:
    """Raise ValueError if path is not within the orchestrator-owned artifact set."""
    try:
        rel = path.relative_to(repo_path)
    except ValueError:
        raise ValueError(f"Diagnose-Fix refused to write outside repo: {path}")
    first_part = rel.parts[0] if rel.parts else ""
    if str(rel) not in OWNED_ARTIFACT_FILES and first_part not in OWNED_ARTIFACT_DIRS:
        raise ValueError(
            f"Diagnose-Fix refused to write outside owned artifacts: {rel}. "
            f"Allowed dirs: {OWNED_ARTIFACT_DIRS}, allowed files: {OWNED_ARTIFACT_FILES}"
        )


def is_test_scan_weakening_change(change_text: str) -> bool:
    lowered = change_text.lower()
    return any(pattern.lower() in lowered for pattern in BLOCKED_PATTERNS)


def _infra_error_in(output: str) -> str | None:
    for pattern in INFRA_ERROR_PATTERNS:
        if pattern.lower() in output.lower():
            return pattern
    return None


def apply_fix_for_failure(
    repo_path: Path,
    failed_step: StepName,
    failure_output: str,
    state: PipelineState,
) -> FixProposal:
    # ── test failures ────────────────────────────────────────────────────────
    # App-code bugs are the developer's job. Never auto-fix, always escalate.
    if failed_step == "test":
        return FixProposal(
            root_cause="Test failure requires developer attention — not a pipeline artifact issue",
            confidence=1.0,
            change_summary="Escalate to developer",
            retry_step="test",
            escalated=True,
            fix_type="escalate",
            hint="Review test output and fix application source code, then re-run the pipeline.",
        )

    # ── scan failures ─────────────────────────────────────────────────────────
    # Never disable or weaken the scan. Escalate with actionable hint.
    if failed_step == "scan":
        infra_err = _infra_error_in(failure_output)
        if infra_err:
            return FixProposal(
                root_cause=f"Scan tool or registry error: {infra_err}",
                confidence=0.9,
                change_summary="Escalate: scanner infrastructure issue",
                retry_step="scan",
                escalated=True,
                fix_type="infra_hint",
                hint="Check Trivy installation and image registry access.",
            )
        return FixProposal(
            root_cause="Vulnerability found in image — cannot auto-remediate",
            confidence=0.9,
            change_summary="Escalate: update base image or dependencies to resolve CVEs",
            retry_step="scan",
            escalated=True,
            fix_type="escalate",
            hint=(
                "Update the base image tag or pin safer dependency versions in the "
                "generated Dockerfile, then rebuild. Do not disable the scan."
            ),
        )

    # ── build failures ───────────────────────────────────────────────────────
    # Infra errors (daemon, auth) → escalate. Dockerfile errors → regenerate.
    if failed_step == "build":
        infra_err = _infra_error_in(failure_output)
        if infra_err:
            return FixProposal(
                root_cause=f"Docker daemon or registry error: {infra_err}",
                confidence=0.9,
                change_summary="Escalate: infrastructure issue, cannot auto-fix",
                retry_step="build",
                escalated=True,
                fix_type="infra_hint",
                hint=(
                    "Ensure Docker daemon is running and GITHUB_TOKEN/GHCR_TOKEN is set correctly. "
                    f"Details: {infra_err}"
                ),
            )
        if state.build_plan is not None:
            llm = get_llm()
            dockerfile_content = llm.dockerize(state.build_plan)
            dockerfile_path = repo_path / "Dockerfile"
            _assert_owned_artifact(dockerfile_path, repo_path)
            dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
            return FixProposal(
                root_cause="Dockerfile build error — regenerated from current build plan",
                confidence=0.8,
                change_summary="Regenerated Dockerfile using current build plan",
                retry_step="build",
                escalated=False,
                fix_type="tool_retry",
                hint="Dockerfile was regenerated. Build will retry automatically.",
            )
        return FixProposal(
            root_cause="Build failed and no build plan is available to regenerate Dockerfile",
            confidence=0.5,
            change_summary="Escalate: no build plan available",
            retry_step="build",
            escalated=True,
            fix_type="escalate",
            hint="Re-run the pipeline from the plan step.",
        )

    # ── deploy failures ───────────────────────────────────────────────────────
    # Infra/RBAC → escalate with hint. Config errors → regenerate ArgoCD manifest.
    if failed_step == "deploy":
        infra_err = _infra_error_in(failure_output)
        if infra_err:
            return FixProposal(
                root_cause=f"Deploy infrastructure error: {infra_err}",
                confidence=0.9,
                change_summary="Escalate: cluster auth or RBAC issue",
                retry_step="deploy",
                escalated=True,
                fix_type="infra_hint",
                hint=(
                    f"Check kubectl context '{state.cluster}' permissions for namespace "
                    f"'{state.namespace}'. Details: {infra_err}"
                ),
            )
        from orchestrator.artifacts import regenerate_argocd_application
        argocd_path = regenerate_argocd_application(state)
        _assert_owned_artifact(argocd_path, repo_path)
        return FixProposal(
            root_cause="ArgoCD application config may be incorrect — regenerated",
            confidence=0.7,
            change_summary="Regenerated argocd/application.yaml with current namespace and cluster config",
            retry_step="deploy",
            escalated=False,
            fix_type="config_hint",
            hint="ArgoCD application manifest was regenerated. Deploy will retry automatically.",
        )

    # ── healthcheck failures ──────────────────────────────────────────────────
    # Known infra pod states → escalate. Probe/port errors → re-render Helm config.
    if failed_step == "healthcheck":
        infra_err = _infra_error_in(failure_output)
        if infra_err:
            return FixProposal(
                root_cause=f"Deployment not ready: {infra_err}",
                confidence=0.95,
                change_summary=f"Escalate: {infra_err} detected in pod status",
                retry_step="healthcheck",
                escalated=True,
                fix_type="infra_hint",
                hint=(
                    f"kubectl -n {state.namespace} describe pods\n"
                    f"kubectl -n {state.namespace} get events --sort-by=.metadata.creationTimestamp"
                ),
            )
        from orchestrator.artifacts import regenerate_helm_config
        regenerate_helm_config(state)
        return FixProposal(
            root_cause="Helm config may have wrong port or probe path — regenerated",
            confidence=0.7,
            change_summary="Regenerated helm/values.yaml and helm/templates/deployment.yaml",
            retry_step="healthcheck",
            escalated=False,
            fix_type="config_hint",
            hint="Helm manifests were regenerated. Re-deploy and retry healthcheck.",
        )

    # ── provision failures ────────────────────────────────────────────────────
    # Cannot auto-apply infra changes without human approval — always escalate.
    if failed_step == "provision":
        return FixProposal(
            root_cause=f"Infrastructure provisioning failed: {failure_output[:200]}",
            confidence=0.8,
            change_summary="Escalate: manual kubectl action required",
            retry_step="provision",
            escalated=True,
            fix_type="infra_hint",
            hint=(
                f"kubectl create namespace {state.namespace} --dry-run=client -o yaml | kubectl apply -f -\n"
                f"kubectl -n {state.namespace} create secret docker-registry {state.pull_secret_name} "
                f"--docker-server=ghcr.io --docker-username=<github-user> --docker-password=$GITHUB_TOKEN"
            ),
        )

    # ── fallback: use LLM for any unhandled step ──────────────────────────────
    llm = get_llm()
    proposal = llm.diagnose(failed_step, failure_output)
    if proposal.escalated:
        return proposal
    if is_test_scan_weakening_change(proposal.change_summary):
        return FixProposal(
            root_cause="Proposed change weakens test/scan safeguards",
            confidence=1.0,
            change_summary="Rejected unsafe fix proposal",
            retry_step=failed_step,
            escalated=True,
            fix_type="escalate",
            hint="Do not weaken tests or scans. Address the root cause instead.",
        )
    return proposal
