from __future__ import annotations

import os
import re
from pathlib import Path

from orchestrator.state import BuildPlan, PipelineState
from orchestrator.tools._shell import run_command


def _resolve_port(plan: BuildPlan) -> int:
  if plan.ports:
    return int(plan.ports[0])
  return 8000


def _detect_health_path(repo: Path) -> str:
  candidates = [repo / "app" / "main.py", repo / "main.py", repo / "app.py", repo / "src" / "index.js"]
  for path in candidates:
    if not path.exists():
      continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for candidate in ("/health", "/healthz", "/status"):
      if candidate in text:
        return candidate
  return "/health"


def _git_remote_https_url(repo: Path) -> str:
  ok, output = run_command("git remote get-url origin", cwd=repo)
  if not ok or not output.strip():
    return "https://github.com/example/repo.git"
  remote = output.strip()
  if remote.startswith("git@github.com:"):
    owner_repo = remote.replace("git@github.com:", "")
    return f"https://github.com/{owner_repo}"
  return remote


def _git_branch(repo: Path) -> str:
  ok, output = run_command("git rev-parse --abbrev-ref HEAD", cwd=repo)
  branch = output.strip() if ok and output.strip() else "main"
  if branch == "HEAD":
    return "main"
  return branch


def _gitops_target_revision(repo: Path) -> str:
  configured = (Path(repo) / ".pipeline-setup.yaml")
  if configured.exists():
    text = configured.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?m)^\s*targetRevision\s*:\s*([\w./-]+)", text)
    if match:
      return match.group(1).strip()
  env_value = os.getenv("GITOPS_TARGET_REVISION", "").strip()
  if env_value:
    return env_value
  return "main"


def _git_short_sha(repo: Path) -> str:
  ok, output = run_command("git rev-parse --short HEAD", cwd=repo)
  if ok and output.strip():
    return output.strip()
  return "unknown"


def _ci_setup_steps(language: str) -> str:
    """Return YAML steps (indented 6 spaces) for env setup + dep install based on language."""
    lang = language.lower()
    if lang in ("node", "nodejs", "javascript", "typescript"):
        return """\
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install deps
        run: npm ci"""
    if lang == "java":
        return """\
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'"""
    # default: python
    return """\
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install deps
        run: pip install -r requirements.txt"""


def _ci_test_command(plan: BuildPlan) -> str:
    """Return the test command to use in CI."""
    if plan.test_command and plan.test_command not in ("unknown", ""):
        return plan.test_command
    lang = plan.language.lower()
    if lang in ("node", "nodejs", "javascript", "typescript"):
        return "npm test"
    if lang == "java":
        return "mvn test --no-transfer-progress"
    return "pytest -q"


def _ci_build_setup_steps(language: str) -> str:
    """Return YAML steps for the build-and-bump job's language setup (before docker steps)."""
    lang = language.lower()
    if lang in ("node", "nodejs", "javascript", "typescript"):
        return """\
      - uses: actions/setup-node@v4
        with:
          node-version: '20'"""
    if lang == "java":
        return """\
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'"""
    return """\
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'"""


def _workflow_ci(plan: BuildPlan) -> str:
    setup_steps = _ci_setup_steps(plan.language)
    test_cmd = _ci_test_command(plan)
    build_setup_steps = _ci_build_setup_steps(plan.language)
    return f"""name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    if: ${{{{ !contains((github.event.head_commit.message || github.event.pull_request.title || ''), '[skip ci]') }}}}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
{setup_steps}
      - name: Run tests
        run: {test_cmd}

  build-and-bump:
    if: ${{{{ github.event_name == 'push' && github.ref == 'refs/heads/main' && !contains((github.event.head_commit.message || ''), '[skip ci]') }}}}
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v4
{build_setup_steps}
      - name: Resolve image repository from Helm values
        run: |
          repo=$(python .github/scripts/helm_values.py get-repository --file deploy/helm/values.yaml)
          echo "IMAGE_REPOSITORY=$repo" >> "$GITHUB_ENV"
      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{{{ github.actor }}}}
          password: ${{{{ secrets.GHCR_TOKEN || secrets.GITHUB_TOKEN }}}}
      - name: Build test image
        run: |
          docker build --target test \
            -t "${{IMAGE_REPOSITORY}}:test-${{GITHUB_SHA}}" . || \
          docker build -t "${{IMAGE_REPOSITORY}}:test-${{GITHUB_SHA}}" .
      - name: Run tests inside container
        run: |
          docker run --rm \
            --user "$(id -u):$(id -g)" \
            -e PYTHONDONTWRITEBYTECODE=1 \
            -v "${{{{ github.workspace }}}}":/workspace \
            -w /workspace \
            "${{IMAGE_REPOSITORY}}:test-${{GITHUB_SHA}}" \
            {test_cmd} -p no:cacheprovider
      - name: Build and push image
        run: |
          docker build \
            --label "org.opencontainers.image.source=${{GITHUB_SERVER_URL}}/${{GITHUB_REPOSITORY}}" \
            -t "${{IMAGE_REPOSITORY}}:${{GITHUB_SHA}}" .
          docker push "${{IMAGE_REPOSITORY}}:${{GITHUB_SHA}}"
      - name: Bump Helm image tag
        run: |
          python .github/scripts/helm_values.py set-tag --file deploy/helm/values.yaml --tag "${{GITHUB_SHA}}"
      - name: Commit and push image tag bump
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add deploy/helm/values.yaml
          git diff --cached --quiet && echo "No image tag change to commit" && exit 0
          git commit -m "chore(ci): bump image tag to ${{GITHUB_SHA}} [skip ci]"
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
    lines = _read_lines(path)
    in_image = False
    for line in lines:
        stripped = line.strip()
        if not in_image and stripped == "image:":
            in_image = True
            continue
        if in_image:
            if stripped == "":
                continue
            if not line.startswith((" ", "\t")):
                break
            if stripped.startswith("repository:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    raise ValueError(f"image.repository not found in {path}")


def _get_tag(path: Path) -> str:
    lines = _read_lines(path)
    in_image = False
    for line in lines:
        stripped = line.strip()
        if not in_image and stripped == "image:":
            in_image = True
            continue
        if in_image:
            if stripped == "":
                continue
            if not line.startswith((" ", "\t")):
                break
            if stripped.startswith("tag:"):
                return stripped.split(":", 1)[1].strip().strip('"').strip("'")
    raise ValueError(f"image.tag not found in {path}")


def _set_tag(path: Path, tag: str) -> None:
    lines = _read_lines(path)
    in_image = False
    updated = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not in_image and stripped == "image:":
            in_image = True
            continue
        if in_image:
            if stripped == "":
                continue
            if not line.startswith((" ", "\t")):
                break
            if stripped.startswith("tag:"):
                indent = line[: len(line) - len(line.lstrip(" \t"))]
                newline = "\\n" if line.endswith("\\n") else ""
                lines[idx] = f"{indent}tag: {tag}{newline}"
                updated = True
                break
    if not updated:
        raise ValueError(f"image.tag not found in {path}")
    path.write_text("".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read and update helm/values.yaml image fields")
    sub = parser.add_subparsers(dest="command", required=True)

    get_repo = sub.add_parser("get-repository", help="Print image.repository")
    get_repo.add_argument("--file", required=True)

    get_tag = sub.add_parser("get-tag", help="Print image.tag")
    get_tag.add_argument("--file", required=True)

    set_tag = sub.add_parser("set-tag", help="Update image.tag")
    set_tag.add_argument("--file", required=True)
    set_tag.add_argument("--tag", required=True)

    args = parser.parse_args()
    values_path = Path(args.file)

    if args.command == "get-repository":
        print(_get_repository(values_path))
        return 0

    if args.command == "get-tag":
        print(_get_tag(values_path))
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
    # Stage-3 self-heal not yet implemented — this job intentionally skips.
    # When implemented: checkout repo, read failed run logs, open a GitHub issue with diagnosis.
    if: ${{ false }}
    runs-on: ubuntu-latest
    steps:
      - name: Self-heal placeholder
        run: echo 'Stage-3 self-heal not yet implemented'
"""


def _workflow_post_merge_activate() -> str:
    workflow = """name: post-merge-activate

on:
  workflow_run:
    workflows: [ci]
    types: [completed]
  workflow_dispatch:

jobs:
  activate:
    if: ${{ github.event_name != 'workflow_run' || (github.event.workflow_run.conclusion == 'success' && github.event.workflow_run.head_branch == 'main') }}
    runs-on: [self-hosted]
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Resolve image repository
        run: |
          repo=$(python .github/scripts/helm_values.py get-repository --file deploy/helm/values.yaml)
          echo "IMAGE_REPOSITORY=$repo" >> "$GITHUB_ENV"
      - name: Resolve image tag
        run: |
          tag=$(python .github/scripts/helm_values.py get-tag --file deploy/helm/values.yaml)
          echo "IMAGE_TAG=$tag" >> "$GITHUB_ENV"
      - name: Resolve application name
        run: |
          app_name=$(python -c "import yaml; print(yaml.safe_load(open('deploy/argocd/application.yaml'))['metadata']['name'])")
          echo "APP_NAME=$app_name" >> "$GITHUB_ENV"
      - name: Apply ArgoCD application
        run: kubectl --context "${{ vars.KUBE_CONTEXT }}" apply -f deploy/argocd/application.yaml
      - name: Optional ArgoCD sync
        run: |
          if command -v argocd >/dev/null 2>&1; then
            if [ -n "${ARGOCD_SERVER:-}" ]; then
              argocd app sync "$APP_NAME" --server "$ARGOCD_SERVER" --grpc-web || echo "argocd sync failed; relying on automated sync policy"
            else
              echo "ARGOCD_SERVER not set; skipping manual argocd sync and relying on automated sync policy"
            fi
          else
            echo "argocd CLI not found on runner; relying on automated sync policy"
          fi
"""
    return workflow


def _helm_chart_yaml(app_name: str, app_version: str) -> str:
    return f"""apiVersion: v2
name: {app_name}
version: 0.1.0
appVersion: \"{app_version}\"
"""


def _helm_values(registry: str, port: int, health_path: str, pull_secret_name: str = "ghcr-pull-secret") -> str:
    repo, tag = registry.rsplit(":", 1) if ":" in registry else (registry, "latest")
    return f"""image:
  repository: {repo}
  tag: {tag}

containerPort: {port}
healthPath: {health_path}
pullSecretName: {pull_secret_name}

service:
  type: ClusterIP
  port: {port}
"""


def _helm_deployment(app_name: str) -> str:
    return f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{{{ .Release.Name }}}}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: {{{{ .Release.Name }}}}
  template:
    metadata:
      labels:
        app: {{{{ .Release.Name }}}}
    spec:
      imagePullSecrets:
        - name: {{{{ .Values.pullSecretName }}}}
      containers:
        - name: {{{{ .Release.Name }}}}
          image: \"{{{{ .Values.image.repository }}}}:{{{{ .Values.image.tag }}}}\"
          ports:
            - containerPort: {{{{ .Values.containerPort }}}}
          livenessProbe:
            httpGet:
              path: {{{{ .Values.healthPath | default \"/health\" }}}}
              port: {{{{ .Values.containerPort }}}}
            initialDelaySeconds: 10
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: {{{{ .Values.healthPath | default \"/health\" }}}}
              port: {{{{ .Values.containerPort }}}}
            initialDelaySeconds: 5
            periodSeconds: 10
          resources:
            requests:
              memory: {{{{ .Values.resources.requests.memory | default \"64Mi\" }}}}
              cpu: {{{{ .Values.resources.requests.cpu | default \"50m\" }}}}
            limits:
              memory: {{{{ .Values.resources.limits.memory | default \"256Mi\" }}}}
              cpu: {{{{ .Values.resources.limits.cpu | default \"500m\" }}}}
---
apiVersion: v1
kind: Service
metadata:
  name: {{{{ .Release.Name }}}}
spec:
  type: {{{{ .Values.service.type | default \"ClusterIP\" }}}}
  selector:
    app: {{{{ .Release.Name }}}}
  ports:
    - port: {{{{ .Values.service.port | default .Values.containerPort }}}}
      targetPort: {{{{ .Values.containerPort }}}}
      protocol: TCP
      name: http
"""


def _argocd_application(app_name: str, namespace: str, repo_url: str, revision: str) -> str:
    return f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {app_name}
  namespace: argocd
spec:
  project: default
  source:
    repoURL: {repo_url}
    targetRevision: {revision}
    path: deploy/helm
  destination:
    server: https://kubernetes.default.svc
    namespace: {namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
"""


def regenerate_helm_config(state: PipelineState) -> list[Path]:
    """Re-render helm/values.yaml and helm/templates/deployment.yaml from current state."""
    repo = Path(state.repo_ref)
    (repo / "deploy" / "helm" / "templates").mkdir(parents=True, exist_ok=True)
    port = _resolve_port(state.build_plan) if state.build_plan else 8000
    health_path = _detect_health_path(repo)
    values_path = repo / "deploy" / "helm" / "values.yaml"
    values_path.write_text(_helm_values(state.image_ref_for_registry(), port, health_path, state.pull_secret_name), encoding="utf-8")
    deployment_path = repo / "deploy" / "helm" / "templates" / "deployment.yaml"
    deployment_path.write_text(_helm_deployment(state.app_name), encoding="utf-8")
    return [values_path, deployment_path]


def regenerate_argocd_application(state: PipelineState) -> Path:
    """Re-render argocd/application.yaml from current state."""
    repo = Path(state.repo_ref)
    (repo / "deploy" / "argocd").mkdir(parents=True, exist_ok=True)
    repo_url = _git_remote_https_url(repo)
    revision = _gitops_target_revision(repo)
    argocd_path = repo / "deploy" / "argocd" / "application.yaml"
    argocd_path.write_text(_argocd_application(state.app_name, state.namespace, repo_url, revision), encoding="utf-8")
    return argocd_path


def generate_pipeline_artifacts(state: PipelineState, plan: BuildPlan) -> list[Path]:
    repo = Path(state.repo_ref)
    app_name = state.app_name
    port = _resolve_port(plan)
    health_path = _detect_health_path(repo)
    app_version = _git_short_sha(repo)
    repo_url = _git_remote_https_url(repo)
    revision = _gitops_target_revision(repo)

    workflow_dir = repo / ".github" / "workflows"
    workflow_scripts_dir = repo / ".github" / "scripts"
    helm_templates = repo / "deploy" / "helm" / "templates"
    argocd_dir = repo / "deploy" / "argocd"

    workflow_dir.mkdir(parents=True, exist_ok=True)
    workflow_scripts_dir.mkdir(parents=True, exist_ok=True)
    helm_templates.mkdir(parents=True, exist_ok=True)
    argocd_dir.mkdir(parents=True, exist_ok=True)

    files: list[Path] = []

    dockerfile_path = repo / "Dockerfile"
    if dockerfile_path.exists():
        # Dockerfile was already created by the Dockerizer agent (re-run / resume path).
        # On a first run it doesn't exist yet — run_dockerizer in _node_build creates it.
        files.append(dockerfile_path)

    ci_path = workflow_dir / "ci.yml"
    ci_path.write_text(_workflow_ci(plan), encoding="utf-8")
    files.append(ci_path)

    helm_values_helper_path = workflow_scripts_dir / "helm_values.py"
    helm_values_helper_path.write_text(_workflow_helm_values_helper(), encoding="utf-8")
    files.append(helm_values_helper_path)

    self_heal_path = workflow_dir / "ci-self-heal.yml"
    self_heal_path.write_text(_workflow_self_heal(), encoding="utf-8")
    files.append(self_heal_path)

    activate_path = workflow_dir / "post-merge-activate.yml"
    activate_path.write_text(_workflow_post_merge_activate(), encoding="utf-8")
    files.append(activate_path)

    chart_path = repo / "deploy" / "helm" / "Chart.yaml"
    chart_path.write_text(_helm_chart_yaml(app_name, app_version), encoding="utf-8")
    files.append(chart_path)

    values_path = repo / "deploy" / "helm" / "values.yaml"
    values_path.write_text(_helm_values(state.image_ref_for_registry(), port, health_path, state.pull_secret_name), encoding="utf-8")
    files.append(values_path)

    deployment_path = helm_templates / "deployment.yaml"
    deployment_path.write_text(_helm_deployment(app_name), encoding="utf-8")
    files.append(deployment_path)

    argocd_path = argocd_dir / "application.yaml"
    argocd_path.write_text(_argocd_application(app_name, state.namespace, repo_url, revision), encoding="utf-8")
    files.append(argocd_path)

    return files
