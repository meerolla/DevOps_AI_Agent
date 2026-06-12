# Requirements — Pipeline Setup Orchestrator

> Spec 1 of 3. WHAT it does. EARS-style acceptance criteria.

## Product summary
A multi-agent system that, given an app repo, plans and sets up CI/CD and deploys the app: a thin
orchestrator coordinates judgment agents (Planner, Dockerizer, Diagnose-Fix) on top of deterministic
tools (Terraform, Docker, test runner, Trivy, Helm, ArgoCD), pausing for human approval on destructive
steps.

## US1 — Plan from a repo
- WHEN given a repo, THE PLANNER SHALL produce a `BuildPlan`; unknown fields SHALL be flagged, not guessed.

## US2 — Containerize
- THE DOCKERIZER SHALL produce a Dockerfile that builds successfully (non-root, pinned base, no secrets),
  retrying within a bound; on persistent failure it SHALL escalate with the build error.

## US3 — Deterministic execution
- Build, test, scan, provision, and deploy SHALL run through deterministic tools, NOT the LLM.
- THE SYSTEM SHALL validate each step's result before proceeding.

## US4 — Self-heal per step
- WHEN a step fails, THE ORCHESTRATOR SHALL route to Diagnose-Fix, which proposes a fix for THAT step;
  THE SYSTEM SHALL retry only that step. Diagnose-Fix SHALL never weaken a test/scan to force a pass.

## US5 — Approval gates
- BEFORE provisioning infrastructure, THE SYSTEM SHALL show the change set and require human approval
  (on-prem: the namespace + secrets to be created; AWS path: the `terraform plan`).
- BEFORE deploying, THE SYSTEM SHALL require human approval. No destructive tool runs before approval.

## US6 — Safety & audit
- Agents SHALL hold no standing cloud-admin creds. THE SYSTEM SHALL write an audit entry for every step
  and approval, and SHALL NOT log secrets.

## US7 — Demo/sandbox mode
- THE SYSTEM SHALL run against a local k3d/kind cluster with infra stubbed, and SHALL support a
  mock LLM mode, so it runs reproducibly offline.

## Out of scope
- Multi-cloud, multi-app fleets, real production cloud provisioning in the demo, autonomous (un-gated)
  apply/deploy.

## Acceptance (definition of done)
- On a seeded sample repo: Planner -> Dockerizer -> build -> test -> scan all succeed (with a seeded
  test failure recovered by Diagnose-Fix), both gates pause for approval, and the app deploys to the
  kind cluster and passes healthcheck. Full audit log; no secrets logged.
