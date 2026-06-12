from __future__ import annotations

from pathlib import Path

from orchestrator.state import ToolResult
from orchestrator.tools._shell import run_command


def run_tests(repo_path: Path, test_command: str) -> ToolResult:
    command = test_command if test_command != "unknown" else "pytest -q"
    ok, output = run_command(command, cwd=repo_path)
    return ToolResult(
        ok=ok,
        step="test",
        details="tests executed",
        output=output,
    )
