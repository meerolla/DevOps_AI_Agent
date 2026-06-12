import os
import shutil
from pathlib import Path

from orchestrator.graph import run_pipeline
from orchestrator.state import PipelineState


def test_full_run_mock_sandbox_recovers_seeded_failure(tmp_path: Path) -> None:
    os.environ["SANDBOX"] = "1"
    os.environ["LLM_MODE"] = "mock"

    fixture_repo = Path("tests/fixtures/sample-repo")
    repo_copy = tmp_path / "sample-repo"
    shutil.copytree(fixture_repo, repo_copy)

    state = PipelineState(goal="set up CI/CD and deploy", repo_ref=str(repo_copy))
    final_state = run_pipeline(state, auto_approve=True)

    assert final_state.step_status["test"] == "ok"
    assert final_state.step_status["deploy"] == "ok"
    assert final_state.step_status["healthcheck"] == "ok"
    assert final_state.approvals.infra is True
    assert final_state.approvals.deploy is True
    assert final_state.retries.get("test", 0) >= 1

    app_text = (repo_copy / "app.py").read_text(encoding="utf-8")
    assert "return a + b" in app_text

    for entry in final_state.audit:
        assert "ghp_" not in entry.details
