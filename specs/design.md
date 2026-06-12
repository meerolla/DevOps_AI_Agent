# Design — Pipeline Setup Orchestrator

> Spec 2 of 3. HOW. Decisive so the build is hands-off.

## Stack (fixed)
- Python 3.12.
- Orchestration: **LangGraph** — its state graph + `interrupt()` for human-in-the-loop is purpose-built
  for the approval gates. Judgment agents are LangChain/LangGraph agents. (Swappable for Google ADK's
  hierarchical agents or Strands multi-agent — the state contract and node boundaries don't change.)
- Deterministic tools shell out to: Docker/BuildKit, the repo's test runner, Trivy, Helm, ArgoCD
  CLI/kubectl. (Terraform only if real cloud infra is needed — see Deployment target.)
- pytest for the system's own tests. Mock LLM mode required.

## Deployment target (POC default: on-prem)
- **Cluster:** a **k3s / k3d** cluster is a PREREQUISITE (stood up once — see ONE_TIME_SETUP.md), not
  something this tool provisions. The AWS/EKS path is an alternative for a later phase.
- **Registry:** **GHCR (ghcr.io)** by default; auth via a GitHub token (PAT or Actions token), not AWS
  creds. Swap to ECR + AWS creds only on the cloud path.
- **LLM provider:** OpenAI or Anthropic API key (or a local model) on-prem; Bedrock only on the AWS path.
- On the on-prem path, `provision_infra` reduces to namespace + secrets (no Terraform). The approval
  gate still applies; it just shows the namespace/secret changes instead of a `terraform plan`.

## Why LangGraph here
The pipeline is a graph with conditional edges (success -> next step; failure -> Diagnose-Fix -> retry)
and human pauses. LangGraph models exactly that: nodes = steps, edges = routing, `interrupt()` = gates,
a typed state object = the shared `PipelineState`. The orchestrator stays thin — it's the graph.

## Module layout
```
orchestrator/
  graph.py          # pipeline orchestration flow + pause/resume gates
  state.py          # PipelineState + artifact models
  artifacts.py      # deterministic repo artifact generation
  gitops.py         # auto-commit generated artifacts
  agents/
    planner.py      # Planner agent
    dockerizer.py   # Dockerizer agent
    diagnose_fix.py # Diagnose-Fix agent
  tools/
    infra.py        # provision_infra: terraform plan/apply (sandbox-aware)
    build.py        # build_image: docker build
    test.py         # run_tests
    scan.py         # scan_image: trivy
    deploy.py       # deploy: helm + argocd
    health.py       # healthcheck
  llm.py            # provider selection + mock mode
  audit.py          # structured, secret-safe audit log
  main.py           # CLI: run/approve/resume
tests/
  fixtures/sample-repo/   # seeded app with a known test failure
  test_agents_mock.py
  test_gates.py
```

## The orchestrator flow (graph.py)
Nodes: `plan -> dockerize -> build -> test -> scan -> approve_infra -> provision ->
approve_deploy -> deploy -> healthcheck`.
- Conditional edge after build/test/scan/healthcheck: on failure -> `diagnose_fix` -> back to the failed
  node (bounded retries; then escalate).
- `approve_infra` and `approve_deploy` are explicit CLI pause points backed by persisted state in
  `.orchestrator_state.json`; `provision`/`deploy` run only after approval is recorded.

## Tools (deterministic, target-aware)
Each tool is a typed function that shells out and returns a structured result. On the on-prem path,
`provision_infra` produces a change set for namespace + GHCR image pull secret and applies only after
approval. `build_image` builds and pushes to **GHCR** (GitHub-token auth), `deploy` uses Helm and
ArgoCD application sync, and `healthcheck` validates deployment readiness. In `SANDBOX=1`, commands
are deterministic stubs. No tool embeds an LLM call.

## Guardrails (enforced in code)
- No destructive tool (`apply`, `deploy`) runs unless `state.approvals.<x>` is true.
- Agents receive scoped, read-mostly tools; no standing cloud-admin creds.
- Diagnose-Fix changes are rejected if they delete/skip/weaken a test or scan.
- Bounded retries per step; then escalate. Every step + approval -> audit entry; never log secrets.

## Run & test
- Setup (once): `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run (venv active): `python -m orchestrator.main run --repo <path> --cluster <context> --registry <ghcr-ref> --namespace <ns> --goal "set up CI/CD and deploy"`
- Approve paused gate: `python -m orchestrator.main approve --repo <path> --step infra|deploy`
- Resume paused run: `python -m orchestrator.main resume --repo <path>`
- Test (venv active): `SANDBOX=1 LLM_MODE=mock pytest -q`

## Generated artifacts
For the target app repo, the orchestrator generates:
- `Dockerfile`
- `.github/workflows/ci.yml`
- `.github/workflows/ci-self-heal.yml`
- `helm/Chart.yaml`
- `helm/values.yaml`
- `helm/templates/deployment.yaml`
- `argocd/application.yaml`

On successful completion, artifacts are auto-committed.
