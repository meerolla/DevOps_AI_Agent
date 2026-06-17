"""Unit tests for ProviderLLM._execute_tool and REPO_TOOLS schema."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.llm import REPO_TOOLS, ProviderLLM


def _make_provider(tmp_path: Path) -> ProviderLLM:
    """Create a ProviderLLM with a mocked OpenAI client so no network calls happen."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        with patch("orchestrator.llm.ProviderLLM._build_client", return_value=MagicMock()):
            return ProviderLLM()


# ---------------------------------------------------------------------------
# REPO_TOOLS schema tests
# ---------------------------------------------------------------------------


def test_repo_tools_schema_has_two_entries() -> None:
    assert len(REPO_TOOLS) == 2
    names = {t["function"]["name"] for t in REPO_TOOLS}
    assert names == {"list_repo_files", "read_repo_file"}


def test_repo_tools_are_valid_openai_format() -> None:
    for tool in REPO_TOOLS:
        assert tool["type"] == "function"
        func = tool["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func
        assert func["parameters"]["type"] == "object"


# ---------------------------------------------------------------------------
# _execute_tool dispatch tests
# ---------------------------------------------------------------------------


def test_execute_tool_list_repo_files_root(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

    provider = _make_provider(tmp_path)
    result_json = provider._execute_tool("list_repo_files", {"relative_path": "."}, tmp_path)
    result = json.loads(result_json)

    assert "app.py" in result
    assert "requirements.txt" in result


def test_execute_tool_list_repo_files_default_path(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("", encoding="utf-8")

    provider = _make_provider(tmp_path)
    # Omit relative_path — should default to "."
    result_json = provider._execute_tool("list_repo_files", {}, tmp_path)
    result = json.loads(result_json)
    assert "main.py" in result


def test_execute_tool_read_repo_file(tmp_path: Path) -> None:
    content = "fastapi==0.111.0\nuvicorn\n"
    (tmp_path / "requirements.txt").write_text(content, encoding="utf-8")

    provider = _make_provider(tmp_path)
    result = provider._execute_tool("read_repo_file", {"relative_path": "requirements.txt"}, tmp_path)

    assert "fastapi" in result
    assert "uvicorn" in result


def test_execute_tool_read_missing_file_returns_error(tmp_path: Path) -> None:
    provider = _make_provider(tmp_path)
    result = provider._execute_tool("read_repo_file", {"relative_path": "does-not-exist.txt"}, tmp_path)
    assert result.startswith("Error:")


def test_execute_tool_path_traversal_returns_error(tmp_path: Path) -> None:
    provider = _make_provider(tmp_path)
    result = provider._execute_tool("read_repo_file", {"relative_path": "../../etc/passwd"}, tmp_path)
    assert result.startswith("Error:")


def test_execute_tool_unknown_tool_returns_error(tmp_path: Path) -> None:
    provider = _make_provider(tmp_path)
    result = provider._execute_tool("delete_all_files", {}, tmp_path)
    assert "unknown tool" in result
