# Demo 3 Plan — Pipeline Setup Orchestrator

> Show a multi-agent system that sets up CI/CD and deploys an app — with a thin orchestrator,
> a few judgment agents, deterministic tools underneath, and humans approving the risky steps.

## The headline
Not "more agents." The story is **judgment vs. execution**: agents only where there's ambiguity,
deterministic tools everywhere else, humans gating anything destructive. That restraint is the
expertise — and it's what keeps the demo from collapsing live.

## What the audience sees
1. Hand the orchestrator a fresh app repo and the goal "set up CI/CD and deploy this."
2. **Planner agent** inspects the repo and prints a structured plan (language, ports, test cmd, etc.).
3. **Dockerizer agent** writes a Dockerfile; the deterministic `build_image` tool builds it.
4. Deterministic `run_tests` and `scan_image` run. Break one on purpose -> **Diagnose-Fix agent**
   proposes a fix -> retry just that step. (Great moment to show the agents earning their keep.)
5. **[GATE]** the orchestrator pauses and shows a `terraform plan`; you approve -> it applies (sandbox).
6. **[GATE]** you approve the deploy -> Helm + ArgoCD sync -> service goes live -> healthcheck passes.

## Demo beats to call out
- Point at the architecture diagram first: "agents here, tools here, gates here." 60 seconds.
- When a step fails, show the agent diagnosing — contrast with the deterministic steps that just run.
- Pause visibly at each gate. The pause IS the point: a human owns the destructive decisions.

## Bulletproofing
- Local **kind** cluster; Terraform against a local/null provider (or stub it). No real cloud.
- Mock LLM mode + a prepared repo with a known, seeded test failure for the Diagnose-Fix moment.
- Pre-pull images so `build`/`deploy` are fast on stage.

## Prereqs (manual, one-time)
- kind cluster + ArgoCD installed; Docker available; Trivy installed.
- LLM creds (or mock mode). A sample app repo to feed in.
- Fill the `[TODO]`s in the spec files.

## Honesty notes for the audience
- This deliberately uses only 3 judgment agents. Eight autonomous agents re-deriving deterministic
  work would be slower, costlier, and more fragile — and unsafe with cloud creds.
- The deterministic tools (Terraform/Helm/ArgoCD) are doing the heavy lifting; the agents add the
  adaptation and recovery on top.

## How it relates to Demos 1 & 2
- Demo 1: an agent *builds* an app. Demo 2: an agent *maintains* a running app.
- Demo 3: agents *stand up the whole pipeline* for an app — and the Diagnose-Fix agent reuses the
  Demo 2 self-heal idea across every step.
