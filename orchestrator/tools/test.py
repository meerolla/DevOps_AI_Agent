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


_NO_TESTS_COLLECTED_PATTERNS = (
    "no tests ran",
    "no tests were run",
    "collected 0 items",
    "no tests collected",
)


def _is_no_tests_collected(output: str) -> bool:
    """Return True if the runner found no test functions (pytest exit 5 etc.)."""
    lowered = output.lower()
    return any(pattern in lowered for pattern in _NO_TESTS_COLLECTED_PATTERNS)


def run_tests(
    repo_path: Path,
    test_command: str,
    image_ref: str | None = None,
    test_image_ref: str | None = None,
    require_tests: bool = False,
) -> ToolResult:
    # Prefer the dedicated test-stage image; fall back to the runtime image
    effective_image = test_image_ref or image_ref
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

    if not effective_image:
        return ToolResult(
            ok=False,
            step="test",
            details="test_execution_requires_docker",
            output="image_ref is not set; cannot run tests inside container. Ensure build step completed.",
        )

    # Mount the repo into the container so test files are available regardless
    # of what the Dockerfile chose to COPY. The image provides the runtime
    # (Python + installed dependencies); the host checkout provides the tests.
    # Run as the current user so pytest can write __pycache__ / .pytest_cache.
    repo_abs = str(repo_path.resolve())
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    command = (
        f"docker run --rm "
        f"--user {uid_gid} "
        f"-e PYTHONDONTWRITEBYTECODE=1 "
        f"-v {repo_abs}:/workspace "
        f"-w /workspace "
        f"{effective_image} "
        f"{test_command} -p no:cacheprovider"
    )
    ok, output = run_command(command, cwd=repo_path)

    if not ok and _is_no_tests_collected(output):
        if require_tests:
            return ToolResult(
                ok=False,
                step="test",
                details="tests_required_but_none_detected",
                output=output,
            )
        return ToolResult(
            ok=True,
            step="test",
            details="tests_skipped_no_tests_detected",
            output=output,
        )

    return ToolResult(
        ok=ok,
        step="test",
        details="tests executed in container",
        output=output,
    )
