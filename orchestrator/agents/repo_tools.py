from __future__ import annotations

from pathlib import Path


def list_repo_files(repo_path: Path, relative_path: str = ".") -> list[str]:
    target = (repo_path / relative_path).resolve()
    root = repo_path.resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Path escapes repo root: {relative_path}")
    if not target.exists():
        return []
    if target.is_file():
        return [str(target.relative_to(root)).replace("\\", "/")]

    entries: list[str] = []
    for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
        rel = str(child.relative_to(root)).replace("\\", "/")
        if child.is_dir():
            entries.append(rel + "/")
        else:
            entries.append(rel)
    return entries


def read_repo_file(repo_path: Path, relative_path: str, max_chars: int = 8000) -> str:
    target = (repo_path / relative_path).resolve()
    root = repo_path.resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"Path escapes repo root: {relative_path}")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative_path)
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...<truncated>..."
