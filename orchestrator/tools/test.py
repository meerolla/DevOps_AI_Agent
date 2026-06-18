from __future__ import annotations

import os
from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import is_sandbox, run_command

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")


def _has_test_surface(repo_path: Path, test_command: str) -> bool:
    """Return True if the repo has a detectable test surface."""
    if test_command == "unknown":
        return False
    # For pytest-style commands, look for test files or a tests/ directory
    if "pytest" in test_command:
        if (repo_path / "tests").is_dir() or (repo_path / "test").is_dir():
            return True
        for pattern in _TEST_FILE_PATTERNS:
            if any(repo_path.rglob(pattern)):
                return True
        return False
    # For other explicit commands (npm test, go test, etc.) trust the caller
    return True


def run_tests(
    repo_path: Path,
    test_command: str,
    image_ref: str | None = None,
    require_tests: bool = False,
) -> ToolResult:
    if not _has_test_surface(repo_path, test_command):
        if require_tests:
            return ToolResult(
                ok=False,
                step="test",
                details="tests_required_but_none_detected",
                output="No test surface detected and --require-tests is set.",
            )
        return ToolResult(
            ok=True,
            step="test",
            details="tests_skipped_no_tests_detected",
            output="No test surface detected; skipping test step.",
        )

    if is_sandbox():
        if os.getenv("FORCE_TEST_FAIL", "0") == "1":
            return ToolResult(ok=False, step="test", details="forced test failure", output="forced")
        return ToolResult(ok=True, step="test", details="sandbox test pass", output="sandbox: no tests run")

    if not image_ref:
        return ToolResult(
            ok=False,
            step="test",
            details="test_execution_requires_docker",
            output="image_ref is not set; cannot run tests inside container. Ensure build step completed.",
        )

    command = f"docker run --rm {image_ref} {test_command}"
    ok, output = run_command(command, cwd=repo_path)
    return ToolResult(
        ok=ok,
        step="test",
        details="tests executed in container",
        output=output,
    )
