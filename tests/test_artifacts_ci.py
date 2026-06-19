from pathlib import Path
import subprocess
import sys

import yaml

from orchestrator.artifacts import generate_pipeline_artifacts
from orchestrator.state import BuildPlan, PipelineState


def _make_state(tmp_path: Path) -> PipelineState:
    return PipelineState(
        goal="test",
        repo_ref=str(tmp_path),
        cluster="default",
        registry="ghcr.io/demo/sample",
        namespace="my-app",
        app_name="sample",
    )


def test_generated_ci_workflow_has_pr_and_main_tracks(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    ci_path = tmp_path / ".github" / "workflows" / "ci.yml"
    ci_text = ci_path.read_text(encoding="utf-8")

    assert "pull_request:" in ci_text
    assert "build-and-bump:" in ci_text
    assert "github.event_name == 'push'" in ci_text
    assert "docker/login-action@v3" in ci_text
    assert "username: ${{ github.actor }}" in ci_text
    assert "password: ${{ secrets.GHCR_TOKEN || secrets.GITHUB_TOKEN }}" in ci_text
    assert "org.opencontainers.image.source=${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}" in ci_text
    assert "helm_values.py set-tag" in ci_text
    assert "deploy/helm/values.yaml" in ci_text
    assert "[skip ci]" in ci_text
    # [skip ci] guard on both jobs
    assert ci_text.count("[skip ci]") >= 2
    # in-container test step in build-and-bump
    assert "--target test" in ci_text
    assert "github.workspace" in ci_text
    # Python-specific
    assert "setup-python" in ci_text
    assert "pip install -r requirements.txt" in ci_text
    assert "pytest -q" in ci_text
    assert "setup-node" not in ci_text
    assert "setup-java" not in ci_text


def test_ci_workflow_node_language(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="node", test_command="npm test")

    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "setup-node" in ci_text
    assert "node-version: '20'" in ci_text
    assert "npm ci" in ci_text
    assert "npm test" in ci_text
    assert "setup-python" not in ci_text
    assert "pip install" not in ci_text
    assert "pytest" not in ci_text


def test_ci_workflow_java_language(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="java", test_command="mvn test --no-transfer-progress")

    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "setup-java" in ci_text
    assert "temurin" in ci_text
    assert "mvn test" in ci_text
    assert "setup-python" not in ci_text
    assert "pip install" not in ci_text
    assert "npm" not in ci_text


def test_ci_workflow_unknown_language_defaults_to_python(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="unknown", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "setup-python" in ci_text
    assert "pip install -r requirements.txt" in ci_text


def test_generated_post_merge_activation_workflow(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    workflow_path = tmp_path / ".github" / "workflows" / "post-merge-activate.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    assert "name: post-merge-activate" in workflow_text
    assert "workflow_run:" in workflow_text
    assert "workflows: [ci]" in workflow_text
    assert "github.event.workflow_run.conclusion == 'success'" in workflow_text
    assert "github.event.workflow_run.head_branch == 'main'" in workflow_text
    assert "runs-on: [self-hosted]" in workflow_text
    assert "helm_values.py get-tag --file deploy/helm/values.yaml" in workflow_text
    assert "helm upgrade --install" not in workflow_text
    assert "kubectl --context \"${{ vars.KUBE_CONTEXT }}\" apply -f deploy/argocd/application.yaml" in workflow_text
    assert "argocd app sync \"$APP_NAME\" --server \"$ARGOCD_SERVER\" --grpc-web" in workflow_text
    assert "ARGOCD_SERVER not set; skipping manual argocd sync" in workflow_text
    assert "--kube-context" not in workflow_text
    assert "--namespace" not in workflow_text
    assert "vars.KUBE_CONTEXT" in workflow_text
    assert "vars.APP_NAMESPACE" not in workflow_text


def test_generated_helm_values_helper_updates_tag(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    helper_path = tmp_path / ".github" / "scripts" / "helm_values.py"
    assert helper_path.exists()

    values_path = tmp_path / "deploy" / "helm" / "values.yaml"
    original = values_path.read_text(encoding="utf-8")
    assert "tag: latest" in original

    subprocess.check_call(
        [
            sys.executable,
            str(helper_path),
            "set-tag",
            "--file",
            str(values_path),
            "--tag",
            "abc123",
        ]
    )

    updated = values_path.read_text(encoding="utf-8")
    assert "tag: abc123" in updated


def test_generated_helm_values_helper_reads_tag(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    helper_path = tmp_path / ".github" / "scripts" / "helm_values.py"
    values_path = tmp_path / "deploy" / "helm" / "values.yaml"

    output = subprocess.check_output(
        [
            sys.executable,
            str(helper_path),
            "get-tag",
            "--file",
            str(values_path),
        ],
        text=True,
    ).strip()

    assert output == "latest"


def test_generated_yaml_is_valid_for_non_template_files(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", framework="fastapi", ports=[8080], test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    for file_path in [
        tmp_path / "deploy" / "helm" / "Chart.yaml",
        tmp_path / "deploy" / "helm" / "values.yaml",
        tmp_path / "deploy" / "argocd" / "application.yaml",
        tmp_path / ".github" / "workflows" / "ci.yml",
        tmp_path / ".github" / "workflows" / "ci-self-heal.yml",
        tmp_path / ".github" / "workflows" / "post-merge-activate.yml",
    ]:
        yaml.safe_load(file_path.read_text(encoding="utf-8"))


def test_generated_argocd_repo_url_is_git(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", framework="fastapi", ports=[8080], test_command="pytest -q")

    subprocess.check_call(["git", "init"], cwd=tmp_path)
    subprocess.check_call(["git", "remote", "add", "origin", "https://github.com/acme/demo.git"], cwd=tmp_path)

    generate_pipeline_artifacts(state, plan)
    app = yaml.safe_load((tmp_path / "deploy" / "argocd" / "application.yaml").read_text(encoding="utf-8"))
    repo_url = app["spec"]["source"]["repoURL"]
    assert not repo_url.startswith("file://")
    assert "github.com" in repo_url


def test_generated_ports_are_consistent(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", framework="fastapi", ports=[8080], test_command="pytest -q")

    generate_pipeline_artifacts(state, plan)

    values_text = (tmp_path / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8")
    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")

    assert "containerPort: 8080" in values_text
    assert "port: 8080" in values_text
    assert "containerPort: {{ .Values.containerPort }}" in deployment_text
    # Dockerfile is created by the Dockerizer agent, not by generate_pipeline_artifacts


def test_generated_deployment_has_health_probes(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", framework="fastapi", ports=[8080], test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    assert "livenessProbe:" in deployment_text
    assert "readinessProbe:" in deployment_text
    assert "path: {{ .Values.healthPath | default \"/health\" }}" in deployment_text


def test_helm_values_helper_updates_only_image_tag(tmp_path: Path) -> None:
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", framework="fastapi", ports=[8080], test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    helper_path = tmp_path / ".github" / "scripts" / "helm_values.py"
    values_path = tmp_path / "deploy" / "helm" / "values.yaml"
    values_path.write_text(
        """image:
  repository: ghcr.io/demo/sample
  tag: old-tag

sidecar:
  tag: should-stay
""",
        encoding="utf-8",
    )

    subprocess.check_call(
        [
            sys.executable,
            str(helper_path),
            "set-tag",
            "--file",
            str(values_path),
            "--tag",
            "new-tag",
        ]
    )
    updated = values_path.read_text(encoding="utf-8")
    assert "tag: new-tag" in updated
    assert "tag: should-stay" in updated


def test_generated_deployment_uses_release_name_not_hardcoded(tmp_path: Path) -> None:
    """Helm deployment template must use .Release.Name, not a hardcoded app name."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    assert "{{ .Release.Name }}" in deployment_text
    # The literal app name must not appear as a hardcoded resource name
    assert "name: sample" not in deployment_text
    assert "app: sample" not in deployment_text


def test_generated_ci_has_in_container_test_step(tmp_path: Path) -> None:
    """build-and-bump job must build test stage and run tests inside the container."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--target test" in ci_text
    assert "github.workspace" in ci_text
    assert "-v" in ci_text  # volume mount


def test_generated_ci_skip_ci_guard_on_both_jobs(tmp_path: Path) -> None:
    """Both test and build-and-bump jobs must guard against [skip ci] commits."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert ci_text.count("[skip ci]") >= 2


def test_generated_post_merge_no_helm_upgrade(tmp_path: Path) -> None:
    """post-merge-activate must not contain helm upgrade --install (ArgoCD is the deploy mechanism)."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    workflow_text = (tmp_path / ".github" / "workflows" / "post-merge-activate.yml").read_text(encoding="utf-8")
    assert "helm upgrade" not in workflow_text
    assert "kubectl" in workflow_text  # ArgoCD apply is still present


def test_generate_artifacts_does_not_create_fallback_dockerfile(tmp_path: Path) -> None:
    """generate_pipeline_artifacts must NOT create a Dockerfile — that is the Dockerizer's job."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    # No fallback Dockerfile should have been written
    assert not (tmp_path / "Dockerfile").exists()


def test_generate_artifacts_includes_dockerfile_if_already_exists(tmp_path: Path) -> None:
    """If a Dockerfile was already created (e.g. resume path), it is included in the returned files."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.12-slim\n", encoding="utf-8")

    returned_files = generate_pipeline_artifacts(state, plan)

    assert dockerfile in returned_files


def test_state_test_image_ref_defaults_none(tmp_path: Path) -> None:
    from orchestrator.state import PipelineState
    state = PipelineState(goal="demo", repo_ref=str(tmp_path))
    assert state.test_image_ref is None


def test_generated_ci_skip_ci_uses_null_safe_expression(tmp_path: Path) -> None:
    """[skip ci] guards must use null-safe || fallback for PR compatibility."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    # Null-safe form: head_commit.message || pull_request.title || ''
    assert "github.event.pull_request.title" in ci_text
    # build-and-bump uses null-safe || '' fallback
    assert "(github.event.head_commit.message || '')" in ci_text


def test_generated_ci_docker_run_has_user_and_no_cache(tmp_path: Path) -> None:
    """In-container test step must run as host user to avoid permission failures."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    ci_text = (tmp_path / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--user" in ci_text
    assert "PYTHONDONTWRITEBYTECODE=1" in ci_text
    assert "no:cacheprovider" in ci_text


def test_generated_post_merge_app_name_from_argocd_manifest(tmp_path: Path) -> None:
    """APP_NAME must be read from the ArgoCD manifest, not from the repo name."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    workflow_text = (tmp_path / ".github" / "workflows" / "post-merge-activate.yml").read_text(encoding="utf-8")
    assert "basename" not in workflow_text
    assert "deploy/argocd/application.yaml" in workflow_text
    assert "metadata" in workflow_text or "yaml.safe_load" in workflow_text


def test_generated_helm_values_has_pull_secret_name(tmp_path: Path) -> None:
    """values.yaml must contain pullSecretName so the chart is configurable."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    values_text = (tmp_path / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8")
    assert "pullSecretName:" in values_text
    assert "ghcr-pull-secret" in values_text


def test_generated_helm_deployment_uses_values_pull_secret(tmp_path: Path) -> None:
    """Deployment template must reference .Values.pullSecretName, not hardcode the secret name."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    assert "{{ .Values.pullSecretName }}" in deployment_text
    assert "ghcr-pull-secret" not in deployment_text


def test_argocd_app_has_create_namespace_sync_option(tmp_path: Path) -> None:
    """ArgoCD application must have CreateNamespace=true in syncOptions."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    argocd_text = (tmp_path / "deploy" / "argocd" / "application.yaml").read_text(encoding="utf-8")
    assert "CreateNamespace=true" in argocd_text
    assert "syncOptions:" in argocd_text


def test_deployment_has_resource_requests_and_limits(tmp_path: Path) -> None:
    """Helm deployment template must reference resources from values; values.yaml must define defaults."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    assert "resources:" in deployment_text
    assert "requests:" in deployment_text
    assert "limits:" in deployment_text
    # No hardcoded defaults in template — values come from values.yaml
    assert ".Values.resources.requests.memory" in deployment_text
    assert ".Values.resources.limits.memory" in deployment_text

    values_text = (tmp_path / "deploy" / "helm" / "values.yaml").read_text(encoding="utf-8")
    assert "64Mi" in values_text
    assert "256Mi" in values_text
    assert "50m" in values_text
    assert "500m" in values_text


def test_deployment_imagepullpolicy_is_dynamic(tmp_path: Path) -> None:
    """imagePullPolicy must use a Helm conditional, on its own line (not collapsed with image:)."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    deployment_text = (tmp_path / "deploy" / "helm" / "templates" / "deployment.yaml").read_text(encoding="utf-8")
    # Each key must be on its own line — collapsed lines cause helm template parse errors
    assert "\n          imagePullPolicy:" in deployment_text
    assert "\n          image:" in deployment_text
    assert "\n          ports:" in deployment_text
    # Must contain the dynamic conditional logic
    assert "if eq .Values.image.tag" in deployment_text
    assert "Always" in deployment_text
    assert "IfNotPresent" in deployment_text


def test_self_heal_job_is_gated_off(tmp_path: Path) -> None:
    """ci-self-heal.yml must gate the job with if: false (stage-3 not yet implemented)."""
    state = _make_state(tmp_path)
    plan = BuildPlan(language="python", test_command="pytest -q")
    generate_pipeline_artifacts(state, plan)

    self_heal_text = (tmp_path / ".github" / "workflows" / "ci-self-heal.yml").read_text(encoding="utf-8")
    assert "if: ${{ false }}" in self_heal_text
    # Must not look like a working step that does nothing
    assert "Invoke stage-3" not in self_heal_text
