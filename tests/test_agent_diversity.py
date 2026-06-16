import os
from pathlib import Path

from orchestrator.agents.dockerizer import run_dockerizer
from orchestrator.agents.planner import run_planner


def test_planner_produces_different_plans() -> None:
    os.environ["LLM_MODE"] = "mock"
    fastapi_repo = Path("tests/fixtures/fastapi-app")
    node_repo = Path("tests/fixtures/node-express-app")

    fastapi_plan = run_planner(fastapi_repo)
    node_plan = run_planner(node_repo)

    assert fastapi_plan.language == "python"
    assert fastapi_plan.framework == "fastapi"
    assert node_plan.language == "node"
    assert node_plan.framework == "express"
    assert fastapi_plan.language != node_plan.language


def test_dockerizer_produces_different_dockerfiles() -> None:
    os.environ["LLM_MODE"] = "mock"
    os.environ["SANDBOX"] = "1"

    fastapi_repo = Path("tests/fixtures/fastapi-app")
    node_repo = Path("tests/fixtures/node-express-app")

    fastapi_plan = run_planner(fastapi_repo)
    node_plan = run_planner(node_repo)

    fastapi_dockerfile, _ = run_dockerizer(fastapi_repo, fastapi_plan, "ghcr.io/demo/fastapi:latest")
    node_dockerfile, _ = run_dockerizer(node_repo, node_plan, "ghcr.io/demo/node:latest")

    df_fastapi = Path(fastapi_dockerfile).read_text(encoding="utf-8")
    df_node = Path(node_dockerfile).read_text(encoding="utf-8")

    assert "uvicorn" in df_fastapi
    assert "node" in df_node.lower()
    assert df_fastapi != df_node


def test_dockerizer_never_uses_http_server_for_fastapi() -> None:
    os.environ["LLM_MODE"] = "mock"
    os.environ["SANDBOX"] = "1"

    fastapi_repo = Path("tests/fixtures/fastapi-app")
    fastapi_plan = run_planner(fastapi_repo)
    dockerfile_path, _ = run_dockerizer(fastapi_repo, fastapi_plan, "ghcr.io/demo/fastapi:latest")

    content = Path(dockerfile_path).read_text(encoding="utf-8")
    assert "http.server" not in content
    assert "uvicorn" in content
