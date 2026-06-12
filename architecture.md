# Architecture — Pipeline Setup Orchestrator (Demo 3)

> A thin orchestrator coordinates a few judgment agents on top of deterministic tools, with humans
> approving the destructive steps. Goal: given an app repo, set up CI/CD and deploy it — safely.

## The one principle that drives everything
**Agents do judgment. Tools do execution. Humans gate destructive steps.**
- LLM agents are used ONLY where there's genuine ambiguity (what does this app need? how do we
  containerize it? why did this step fail?).
- Everything well-defined (provision, build, test, scan, deploy) runs through deterministic tools
  (Terraform, Docker/BuildKit, the test runner, Trivy, Helm, ArgoCD) — not the LLM.
- Anything destructive or expensive (infra apply, deploy/promote) pauses for human approval.

## Components
**Orchestrator (thin supervisor)** — decomposes the goal, sequences steps, routes work, holds shared
state, and enforces the approval gates. It plans and routes; it does not do the work itself.

**Judgment agents (LLM + tools):**
1. **Planner** — inspects the repo and produces a structured `BuildPlan` (language, framework, ports,
   dependencies, stateful?, DB?, test command).
2. **Dockerizer** — generates a working multi-stage Dockerfile for the app; iterates until it builds.
3. **Diagnose-Fix** — when a deterministic step fails (build/test/scan/deploy), investigates and
   proposes a fix. (Same idea as Demo 2, applied across every step.)

**Deterministic tools (the agents/orchestrator call these — no LLM in the loop):**
`provision_infra` (Terraform plan/apply) · `build_image` (Docker) · `run_tests` · `scan_image`
(Trivy) · `deploy` (Helm + ArgoCD) · `healthcheck`.

**Shared state** — a typed `PipelineState` object carries artifacts between steps (plan, Dockerfile,
image ref, scan report, manifests, approvals, step status). No freeform chat hand-offs.

## End-to-end flow
```
[orchestrator] receive goal + repo
   -> [agent: Planner]      inspect repo            -> BuildPlan
   -> [agent: Dockerizer]   write Dockerfile        -> Dockerfile
   -> [tool: build_image]   docker build            -> image ref     (fail -> Diagnose-Fix -> retry)
   -> [tool: run_tests]     run test command        -> results       (fail -> Diagnose-Fix -> retry)
   -> [tool: scan_image]    Trivy scan              -> report        (high CVE -> Diagnose-Fix / GATE)
   -> [GATE] human approves the infra change set (on-prem: namespace+secrets; AWS: terraform plan)
   -> [tool: provision_infra] apply the change set    -> infra
   -> [GATE] human approves deploy
   -> [tool: deploy]        Helm + ArgoCD sync      -> live
   -> [tool: healthcheck]   probe service           (unhealthy -> Diagnose-Fix -> recommend rollback)
```

## Diagram
```
                         +---------------------------+
                         |       ORCHESTRATOR        |   plans, routes, holds state,
                         |   (thin supervisor)       |   enforces approval gates
                         +-------------+-------------+
            judgment           |       |       |            execution
        +------------------+---+   +---+---+   +--+------------------------+
        |                  |       |       |      |                        |
   [Planner]        [Dockerizer]  [Diagnose-Fix]  |   deterministic tools  |
    inspect repo     write image    fix failures  |  provision/build/test/ |
                                                   |  scan/deploy/health    |
                                                   +-----------+------------+
                                                               |
                                                  [GATE] human approves
                                                  destructive steps
```

## Failure handling (don't let a 7-step chain rot to 70% reliability)
- A **validation check after every step**; on failure, route to Diagnose-Fix, propose a fix, and
  retry the single step — don't restart the whole pipeline.
- Bounded retries; if still failing, stop and escalate to a human with the diagnosis.
- Steps are **idempotent** and **checkpointed** so a re-run resumes, not repeats.

## Safety / blast radius
- Agents hold **no standing cloud-admin creds**. Destructive operations run only through gated tool
  calls executed by the orchestrator after approval.
- The change set is always shown to the human *before* it is applied (a `terraform plan` on the AWS path).
- Deploys go through ArgoCD; nothing is hand-applied. Full audit log of every step and approval.

## Demo / sandbox mode
For a live demo, point tools at a local **k3d/kind** cluster and stub `provision_infra`. The point on
stage is the orchestration, the judgment agents, and the gates — not real cloud spend. A mock LLM mode
keeps it reproducible offline.
