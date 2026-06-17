from pathlib import Path

import orchestrator.tools.infra as infra
from orchestrator.main import _save_state
from orchestrator.state import PipelineState
from orchestrator.tools.deploy import deploy
from orchestrator.tools.infra import provision_infra


def test_provision_requires_approval_and_plan(tmp_path: Path) -> None:
    result_no_plan = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=True,
        plan_generated=False,
    )
    assert not result_no_plan.ok
    assert "plan" in result_no_plan.details

    result_no_approval = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=False,
        plan_generated=True,
    )
    assert not result_no_approval.ok
    assert "approval" in result_no_approval.details


def test_deploy_requires_approval(tmp_path: Path) -> None:
    result = deploy(
        repo_path=tmp_path,
        image_ref="ghcr.io/demo/sample:latest",
        namespace="demo",
        cluster="default",
        app_name="sample",
        approved=False,
    )
    assert not result.ok
    assert "approval" in result.details


def test_state_defaults_to_no_approvals(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    assert state.approvals.infra is False
    assert state.approvals.deploy is False


def test_state_persistence_for_pause(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path), paused_for="approve_infra")
    state_path = _save_state(state)
    assert state_path.exists()


def test_retry_from_step_resets_escalated_state(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    # Simulate pipeline that escalated at test
    state.step_status["plan"] = "ok"
    state.step_status["dockerize"] = "ok"
    state.step_status["build"] = "ok"
    state.step_status["test"] = "escalated"
    state.escalate_reason = "Test failure requires developer attention"
    state.retries["test"] = 2

    state.retry_from_step("test")

    # steps before test are preserved
    assert state.step_status["plan"] == "ok"
    assert state.step_status["build"] == "ok"
    # test and all subsequent steps are reset
    for step in ["test", "scan", "approve_infra", "provision", "approve_deploy", "deploy", "healthcheck"]:
        assert state.step_status[step] == "pending"
    assert state.escalate_reason is None
    assert state.retries.get("test") is None


def test_provision_private_repo_without_argocd_repo_creds_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    monkeypatch.delenv("ARGOCD_REPO_USERNAME", raising=False)
    monkeypatch.delenv("ARGOCD_REPO_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_USER", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def fake_run(command: str, cwd: Path, env=None):
        if "create namespace demo" in command:
            return True, "namespace applied"
        if "-n demo create secret generic ghcr-pull-secret" in command:
            return True, "pull secret applied"
        if command == "git remote get-url origin":
            return True, "https://github.com/acme/private-repo.git\n"
        if command.startswith("git ls-remote "):
            return False, "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
        if "-n argocd get secret argocd-repo-" in command:
            return False, "Error from server (NotFound): secrets \"argocd-repo-xxx\" not found"
        return False, f"unexpected command: {command}"

    monkeypatch.setattr(infra, "run_command", fake_run)

    result = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=True,
        plan_generated=True,
    )

    assert result.ok is False
    assert result.details == "argocd_repo_credentials_missing"
    assert "ARGOCD_REPO_USERNAME" in result.output


def test_provision_private_repo_with_argocd_repo_creds_ensures_secret(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    monkeypatch.setenv("ARGOCD_REPO_USERNAME", "octocat")
    monkeypatch.setenv("ARGOCD_REPO_TOKEN", "ghp_test_token")

    saw_repo_secret_apply = {"value": False}

    def fake_run(command: str, cwd: Path, env=None):
        if "create namespace demo" in command:
            return True, "namespace applied"
        if "-n demo create secret generic ghcr-pull-secret" in command:
            return True, "pull secret applied"
        if command == "git remote get-url origin":
            return True, "https://github.com/acme/private-repo.git\n"
        if command.startswith("git ls-remote "):
            return False, "fatal: repository is private"
        if "-n argocd create secret generic argocd-repo-" in command:
            saw_repo_secret_apply["value"] = True
            return True, "argocd repo secret applied"
        return False, f"unexpected command: {command}"

    monkeypatch.setattr(infra, "run_command", fake_run)

    result = provision_infra(
        repo_path=tmp_path,
        cluster="default",
        namespace="demo",
        secret_names=["ghcr-pull-secret"],
        approved=True,
        plan_generated=True,
    )

    assert result.ok is True
    assert saw_repo_secret_apply["value"] is True
    assert "argocd repo secret ensured" in result.output
