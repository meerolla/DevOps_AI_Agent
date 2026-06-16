from pathlib import Path

from orchestrator import gitops


def test_create_draft_pr_requires_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    ok, message = gitops.create_draft_pr_for_generated_artifacts(
        repo_path=tmp_path,
        branch_name="orchestrator/app-pipeline-assets",
        title="title",
        body="body",
    )

    assert ok is False
    assert "GITHUB_TOKEN" in message
    assert "same shell/session" in message


def test_create_draft_pr_reports_auth_scope_issue(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")

    def fake_run(command: str, cwd: Path, env=None):
        if command == "git remote get-url origin":
            return True, "https://github.com/acme/app.git\n"
        if command.startswith("git checkout -b "):
            return True, ""
        if command.startswith("git push --dry-run -u origin"):
            return False, "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
        return False, f"unexpected command: {command}"

    monkeypatch.setattr(gitops, "run_command", fake_run)

    ok, message = gitops.create_draft_pr_for_generated_artifacts(
        repo_path=tmp_path,
        branch_name="orchestrator/app-pipeline-assets",
        title="title",
        body="body",
    )

    assert ok is False
    assert "non-interactive mode" in message
    assert "same shell/session" in message
    assert "Git output" in message


def test_create_draft_pr_success(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SANDBOX", "0")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")

    def fake_run(command: str, cwd: Path, env=None):
        if command == "git remote get-url origin":
            return True, "https://github.com/acme/app.git\n"
        if command.startswith("git checkout -b "):
            return True, ""
        if command.startswith("git push --dry-run -u origin"):
            return True, "Everything up-to-date"
        if command.startswith("git push -u origin"):
            return True, "branch set up"
        if command == "git symbolic-ref refs/remotes/origin/HEAD":
            return True, "refs/remotes/origin/main\n"
        if command.startswith("curl -sS -X POST "):
            return True, '{"html_url":"https://github.com/acme/app/pull/123"}'
        return False, f"unexpected command: {command}"

    monkeypatch.setattr(gitops, "run_command", fake_run)

    ok, output = gitops.create_draft_pr_for_generated_artifacts(
        repo_path=tmp_path,
        branch_name="orchestrator/app-pipeline-assets",
        title="title",
        body="body",
    )

    assert ok is True
    assert output == "https://github.com/acme/app/pull/123"
