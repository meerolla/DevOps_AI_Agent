from __future__ import annotations

from pathlib import Path
from typing import Iterable

from orchestrator.tools._shell import is_sandbox, run_command


def auto_commit_generated_artifacts(repo_path: Path, paths: Iterable[Path], message: str) -> tuple[bool, str]:
    if is_sandbox():
        return True, "sandbox auto-commit skipped"

    relative_paths = [str(p.relative_to(repo_path)).replace('\\', '/') for p in paths]
    add_cmd = "git add " + " ".join(relative_paths)

    ok_add, out_add = run_command(add_cmd, cwd=repo_path)
    if not ok_add:
        return False, out_add

    ok_commit, out_commit = run_command(f'git commit -m "{message}"', cwd=repo_path)
    if not ok_commit:
        return False, out_commit

    return True, out_commit
