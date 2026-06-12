from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from orchestrator.state import BuildPlan, FixProposal


@dataclass
class LLMConfig:
    mode: str
    provider: str


class MockLLM:
    def plan_repo(self, repo_path: Path) -> BuildPlan:
        language = "python" if (repo_path / "app.py").exists() else "unknown"
        framework = "pytest-app" if (repo_path / "tests").exists() else "unknown"
        entrypoint = "app.py" if (repo_path / "app.py").exists() else "unknown"
        test_cmd = "pytest -q" if (repo_path / "tests").exists() else "unknown"
        notes = []
        if language == "unknown":
            notes.append("language_unknown_needs_human")
        return BuildPlan(
            language=language,
            framework=framework,
            entrypoint=entrypoint,
            ports=[8000],
            dependencies=[],
            stateful=False,
            needs_db=False,
            test_command=test_cmd,
            notes=notes,
        )

    def dockerize(self, plan: BuildPlan) -> str:
        return "\n".join(
            [
                "FROM python:3.12.3-slim AS runtime",
                "WORKDIR /app",
                "RUN useradd -m appuser",
                "COPY . /app",
                "RUN pip install --no-cache-dir pytest==8.2.2",
                "USER appuser",
                "CMD [\"python\", \"-m\", \"http.server\", \"8000\"]",
                "",
            ]
        )

    def diagnose(self, failed_step: str, failure_output: str) -> FixProposal:
        if failed_step == "test" and "Expected 5" in failure_output:
            return FixProposal(
                root_cause="Bug in add implementation in app.py",
                confidence=0.95,
                change_summary="Replace subtraction with addition in app.py",
                retry_step="test",
            )
        return FixProposal(
            root_cause="Unknown deterministic failure",
            confidence=0.2,
            change_summary="Escalate to human",
            retry_step="test",
            escalated=True,
        )


class ProviderLLM(MockLLM):
    """A minimal provider placeholder that intentionally remains deterministic for this demo."""


def get_llm() -> MockLLM:
    mode = os.getenv("LLM_MODE", "mock").lower()
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    config = LLMConfig(mode=mode, provider=provider)
    if config.mode == "mock":
        return MockLLM()
    return ProviderLLM()
