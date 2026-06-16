# Demo and Roadmap

## Demo 3 Plan: Pipeline Setup Orchestrator

Show a multi-agent system that adapts to real app repos, sets up CI/CD, deploys to Kubernetes, and stays safe with approval gates.

## Headline

The core story is adaptive judgment versus deterministic execution:
- agents read and reason over repo evidence
- deterministic tools execute build/test/scan/deploy
- humans own destructive approvals

Not "more agents." The demo point is trusted adaptation with safety.

## What the Audience Sees

1. Provide fresh app repo and goal.
2. Planner agent inspects repo files and outputs app-specific structured plan.
3. Dockerizer agent writes framework-specific Dockerfile; build tool builds image.
4. Tests and scan run. Introduce failure. Diagnose-Fix proposes remediation and retries step.
5. Infra approval gate pause and approval; in sandbox this can show plan/apply behavior.
6. Deploy approval gate pause and approval, then Helm and ArgoCD deploy and healthcheck.

## Demo Beats

- Start with architecture diagram.
- Highlight deterministic vs judgment boundaries.
- Pause visibly at each gate to demonstrate safety ownership.

## Bulletproofing

- Use local kind or k3d cluster and sandbox-compatible setup.
- Keep mock LLM mode available.
- Use prepared repo with seeded failure.
- Pre-pull images to reduce live demo latency.
- If needed, use local/null provider style infra planning rather than cloud infra for stage reliability.

## Prereqs for Demo

- Local cluster and ArgoCD installed.
- Docker and Trivy available.
- LLM credentials or mock mode.
- Sample app repo prepared.

## Honesty Notes

- Deliberately small number of judgment agents.
- Deterministic tools do heavy lifting.
- Agent value is adaptation, routing, and recovery on real repo differences.
- Eight autonomous agents re-deriving deterministic work would be slower, costlier, and more fragile.

### Non-template acceptance criteria

- Planner must produce different plans for different app fixtures (for example FastAPI versus Node/Express).
- Dockerizer must produce different Dockerfiles for different frameworks.
- FastAPI Dockerfiles must not use generic `python -m http.server` runtime.

## Relation to Demo 1 and Demo 2

- Demo 1: agent builds an app.
- Demo 2: agent maintains a running app.
- Demo 3: agent stands up full CI/CD and deployment path, reusing self-heal concepts.

## Product Positioning

DevOps AI Agent moves from app repo to live deployment with spec-driven orchestration and safety gates.

## Delivery Surfaces

1. CLI tool: primary operator interface.
2. GitHub Action: always-on CI self-heal path.
3. Repo config and agent instructions: implementation steering layer.

## Example Commands

```bash
python3 -m orchestrator.main run --repo ../resume-scorer --cluster default --registry ghcr.io/meerolla/resume-scorer --namespace my-app --goal "given an app repo, set up CI/CD and deploy it"
python -m orchestrator.main run --repo ../resume-scorer --cluster k3d-mycluster --registry ghcr.io/<org>/resume-scorer --namespace my-app
```

Disable draft PR creation:

```bash
python -m orchestrator.main run ... --no-draft-pr
```

## Roadmap

1. Real LLM Agent Core: convert Planner, Dockerizer, and Diagnose-Fix to tool-using, repo-specific agent behavior with diversity tests.
2. Runtime correctness guardrails: FastAPI/web runtime command checks, probe defaults, and anti-directory-listing checks.
3. Config and targets: pipeline-setup.yaml plus EKS/GKE/AKS target paths.
4. Multi-component: multi-service apps with database dependencies.
5. Multi-language depth: Java, Node, Go with stronger framework playbooks.
6. Full lifecycle: always-on CI self-heal, runtime triage, observability, and rollback strategy.
