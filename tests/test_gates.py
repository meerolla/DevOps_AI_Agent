from pathlib import Path

import orchestrator.tools.infra as infra
import orchestrator.tools.test as test_mod
from orchestrator.main import _save_state
from orchestrator.state import PipelineState
from orchestrator.tools.deploy import deploy
from orchestrator.tools.infra import provision_infra
from orchestrator.tools.test import run_tests


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


# ---------------------------------------------------------------------------
# Test execution isolation
# ---------------------------------------------------------------------------

def test_run_tests_skips_when_no_test_surface(tmp_path: Path) -> None:
    # Repo with no tests/ dir and no test_*.py files
    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is True
    assert result.details == "tests_skipped_no_tests_detected"


def test_run_tests_require_tests_fails_when_no_surface(tmp_path: Path) -> None:
    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest", require_tests=True)
    assert result.ok is False
    assert result.details == "tests_required_but_none_detected"


def test_run_tests_skips_when_command_is_unknown(tmp_path: Path) -> None:
    # Even with a tests/ dir, command="unknown" means no tests
    (tmp_path / "tests").mkdir()
    result = run_tests(tmp_path, "unknown", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is True
    assert result.details == "tests_skipped_no_tests_detected"


def test_run_tests_sandbox_returns_ok(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "1")
    (tmp_path / "tests").mkdir()
    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is True
    assert "sandbox" in result.details


def test_run_tests_uses_docker_run_with_image_ref(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "tests").mkdir()

    captured = {}

    def fake_run(command: str, cwd: Path, env=None):
        captured["command"] = command
        return True, "1 passed"

    monkeypatch.setattr(test_mod, "run_command", fake_run)

    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:sha-abc123")
    assert result.ok is True
    assert f"docker run --rm -v {tmp_path.resolve()}:/workspace -w /workspace ghcr.io/demo/app:sha-abc123 pytest -q" == captured["command"]
    assert result.details == "tests executed in container"


def test_run_tests_propagates_container_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "tests").mkdir()

    def fake_run(command: str, cwd: Path, env=None):
        return False, "FAILED tests/test_app.py::test_foo - AssertionError"

    monkeypatch.setattr(test_mod, "run_command", fake_run)

    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is False
    assert "AssertionError" in result.output


def test_run_tests_fails_without_image_ref(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "tests").mkdir()

    result = run_tests(tmp_path, "pytest -q", image_ref=None)
    assert result.ok is False
    assert result.details == "test_execution_requires_docker"


def test_state_require_tests_defaults_false(tmp_path: Path) -> None:
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    assert state.require_tests is False


def test_run_tests_detects_test_files_in_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "test_app.py").write_text("def test_x(): pass")

    captured = {}

    def fake_run(command: str, cwd: Path, env=None):
        captured["command"] = command
        return True, "1 passed"

    monkeypatch.setattr(test_mod, "run_command", fake_run)

    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is True
    assert "docker run" in captured["command"]


def test_run_tests_skips_when_container_reports_no_tests_collected(monkeypatch, tmp_path: Path) -> None:
    """pytest exit 5 ('no tests ran') inside container should skip, not fail."""
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "tests").mkdir()

    def fake_run(command: str, cwd: Path, env=None):
        return False, "no tests ran in 0.00s\n"

    monkeypatch.setattr(test_mod, "run_command", fake_run)

    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest")
    assert result.ok is True
    assert result.details == "tests_skipped_no_tests_detected"


def test_run_tests_require_tests_fails_on_container_no_tests_collected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    (tmp_path / "tests").mkdir()

    def fake_run(command: str, cwd: Path, env=None):
        return False, "collected 0 items\n\nno tests ran in 0.00s\n"

    monkeypatch.setattr(test_mod, "run_command", fake_run)

    result = run_tests(tmp_path, "pytest -q", image_ref="ghcr.io/demo/app:latest", require_tests=True)
    assert result.ok is False
    assert result.details == "tests_required_but_none_detected"
