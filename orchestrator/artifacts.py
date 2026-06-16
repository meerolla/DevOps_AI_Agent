from __future__ import annotations

from pathlib import Path

from orchestrator.state import BuildPlan, PipelineState


def _workflow_ci() -> str:
    return """name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -q

  build-and-bump:
    if: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Resolve image repository from Helm values
        run: |
          repo=$(python .github/scripts/helm_values.py get-repository --file helm/values.yaml)
          echo "IMAGE_REPOSITORY=$repo" >> "$GITHUB_ENV"
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build and push image
        run: |
          docker build -t "${IMAGE_REPOSITORY}:${GITHUB_SHA}" .
          docker push "${IMAGE_REPOSITORY}:${GITHUB_SHA}"
      - name: Bump Helm image tag
        run: |
          python .github/scripts/helm_values.py set-tag --file helm/values.yaml --tag "${GITHUB_SHA}"
      - name: Commit and push image tag bump
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add helm/values.yaml
          git diff --cached --quiet && echo "No image tag change to commit" && exit 0
          git commit -m "chore(ci): bump image tag to ${GITHUB_SHA} [skip ci]"
          git push
"""


def _workflow_helm_values_helper() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines(keepends=True)


def _get_repository(path: Path) -> str:
    for line in _read_lines(path):
        stripped = line.strip()
        if stripped.startswith("repository:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    raise ValueError(f"repository not found in {path}")


def _set_tag(path: Path, tag: str) -> None:
    lines = _read_lines(path)
    updated = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("tag:"):
            prefix = line.split("tag:", 1)[0]
            lines[idx] = f"{prefix}tag: {tag}\\n"
            updated = True
            break
    if not updated:
        raise ValueError(f"tag not found in {path}")
    path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read and update helm/values.yaml image fields")
    sub = parser.add_subparsers(dest="command", required=True)

    get_repo = sub.add_parser("get-repository", help="Print image.repository")
    get_repo.add_argument("--file", required=True)

    set_tag = sub.add_parser("set-tag", help="Update image.tag")
    set_tag.add_argument("--file", required=True)
    set_tag.add_argument("--tag", required=True)

    args = parser.parse_args()
    values_path = Path(args.file)

    if args.command == "get-repository":
        print(_get_repository(values_path))
        return 0

    if args.command == "set-tag":
        _set_tag(values_path, args.tag)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _workflow_self_heal() -> str:
    return """name: ci-self-heal

on:
  workflow_run:
    workflows: [ci]
    types: [completed]

jobs:
  diagnose:
    if: ${{ github.event.workflow_run.conclusion == 'failure' }}
    runs-on: ubuntu-latest
    steps:
      - name: Placeholder self-heal hook
        run: echo 'Invoke stage-3 self-heal workflow here'
"""


def _helm_chart_yaml(app_name: str) -> str:
    return f"""apiVersion: v2
name: {app_name}
version: 0.1.0
appVersion: \"latest\"
"""


def _helm_values(registry: str, namespace: str) -> str:
    repo, tag = registry.rsplit(":", 1) if ":" in registry else (registry, "latest")
    return f"""image:
  repository: {repo}
  tag: {tag}

namespace: {namespace}

service:
  port: 8000
"""


def _helm_deployment(app_name: str, pull_secret_name: str) -> str:
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      imagePullSecrets:
      - name: {pull_secret_name}
      containers:
      - name: {app_name}
        image: \"{{{{ .Values.image.repository }}}}:{{{{ .Values.image.tag }}}}\"
        ports:
        - containerPort: 8000
---
apiVersion: v1
kind: Service
metadata:
  name: {app_name}
spec:
  selector:
    app: {app_name}
  ports:
  - port: 8000
    targetPort: 8000
"""


def _argocd_application(app_name: str, namespace: str) -> str:
    return f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {app_name}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: file://.
    targetRevision: HEAD
    path: helm
  destination:
    server: https://kubernetes.default.svc
    namespace: {namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""


def regenerate_helm_config(state: PipelineState) -> list[Path]:
    """Re-render helm/values.yaml and helm/templates/deployment.yaml from current state."""
    repo = Path(state.repo_ref)
    (repo / "helm" / "templates").mkdir(parents=True, exist_ok=True)
    values_path = repo / "helm" / "values.yaml"
    values_path.write_text(_helm_values(state.image_ref_for_registry(), state.namespace), encoding="utf-8")
    deployment_path = repo / "helm" / "templates" / "deployment.yaml"
    deployment_path.write_text(_helm_deployment(state.app_name, state.pull_secret_name), encoding="utf-8")
    return [values_path, deployment_path]


def regenerate_argocd_application(state: PipelineState) -> Path:
    """Re-render argocd/application.yaml from current state."""
    repo = Path(state.repo_ref)
    (repo / "argocd").mkdir(parents=True, exist_ok=True)
    argocd_path = repo / "argocd" / "application.yaml"
    argocd_path.write_text(_argocd_application(state.app_name, state.namespace), encoding="utf-8")
    return argocd_path


def generate_pipeline_artifacts(state: PipelineState, plan: BuildPlan) -> list[Path]:
    repo = Path(state.repo_ref)
    app_name = state.app_name

    workflow_dir = repo / ".github" / "workflows"
    workflow_scripts_dir = repo / ".github" / "scripts"
    helm_templates = repo / "helm" / "templates"
    argocd_dir = repo / "argocd"

    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_scripts_dir.mkdir(parents=True, exist_ok=True)
    helm_templates.mkdir(parents=True, exist_ok=True)
    argocd_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []

    dockerfile_path = repo / "Dockerfile"
    if not dockerfile_path.exists():
        dockerfile_path.write_text(
            "\n".join(
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
            ),
            encoding="utf-8",
        )
    files.append(dockerfile_path)

    ci_path = workflow_dir / "ci.yml"
    ci_path.write_text(_workflow_ci(), encoding="utf-8")
    files.append(ci_path)

    helm_values_helper_path = workflow_scripts_dir / "helm_values.py"
    helm_values_helper_path.write_text(_workflow_helm_values_helper(), encoding="utf-8")
    files.append(helm_values_helper_path)

    self_heal_path = workflow_dir / "ci-self-heal.yml"
    self_heal_path.write_text(_workflow_self_heal(), encoding="utf-8")
    files.append(self_heal_path)

    chart_path = repo / "helm" / "Chart.yaml"
    chart_path.write_text(_helm_chart_yaml(app_name), encoding="utf-8")
    files.append(chart_path)

    values_path = repo / "helm" / "values.yaml"
    values_path.write_text(_helm_values(state.image_ref_for_registry(), state.namespace), encoding="utf-8")
    files.append(values_path)

    deployment_path = helm_templates / "deployment.yaml"
    deployment_path.write_text(_helm_deployment(app_name, state.pull_secret_name), encoding="utf-8")
    files.append(deployment_path)

    argocd_path = argocd_dir / "application.yaml"
    argocd_path.write_text(_argocd_application(app_name, state.namespace), encoding="utf-8")
    files.append(argocd_path)

    return files
