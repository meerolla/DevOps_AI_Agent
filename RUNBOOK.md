# Runbook — Pipeline Orchestrator (Stage 2 + 3, on-prem + GHCR)

> Scope: current phase. Stage 1 (build the app) is separate; Stage 4 (runtime triage) is next phase.
> Target: **on-prem k3s/k3d cluster + GHCR registry** (cheap, simple, no cloud bill).
> Detailed install steps for the platform live in **ONE_TIME_SETUP.md**.
> Golden rule: agents do judgment, tools do execution, humans approve destructive steps.

---
## Part 1 — Build the tools  (ONE TIME · you + Copilot)
- [ ] Rename `dotgithub/` → `.github/`; open the orchestrator repo in VS Code.
- [ ] Create a virtualenv so all installs are isolated:
      `python3.12 -m venv .venv && source .venv/bin/activate` (the agent also does this per its instructions).
- [ ] Select Copilot's `@agent-builder` and point it at `specs/tasks.md`.
- [ ] It builds three things: the **CLI**, the **shared diagnosis library**, and the **Stage-3 CI
      Self-Heal GitHub Action**.
- [ ] Verify offline: `SANDBOX=1 LLM_MODE=mock pytest -q` passes.
- [ ] Package: pip wheel for the CLI + the reusable Action template.

**Done when:** the CLI installs and a sandbox run completes end-to-end with the gates working.

---
## Part 2 — Platform prerequisites  (ONE TIME · see ONE_TIME_SETUP.md for commands)
On-prem, on your single Ubuntu machine:
- [ ] Docker installed.
- [ ] **k3d** installed and a multi-node cluster created (1 server + 2 agents).
- [ ] **ArgoCD** installed on the cluster and reachable.
- [ ] **GHCR** access: a GitHub token (PAT) with `write:packages`/`read:packages`; image pull secret
      created in the cluster namespace.
- [ ] **LLM key**: `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` exported (or use `LLM_MODE=mock`).

> No AWS, no EKS, no ECR, no Terraform on this path. The cluster is a prerequisite — the tool does NOT
> create it.

---
## Part 3 — Run the tool on an app  (PER APP · end-to-end)
- [ ] Push the target app repo to GitHub.
- [ ] `pip install` the CLI.
- [ ] Run it (note: GHCR registry, k3d kube-context):
      `pipeline-setup run --repo ./my-app --cluster k3d-mycluster --registry ghcr.io/<org>/my-app --namespace my-app`

The orchestrator then:
1. **Plan** (agent) → BuildPlan.
2. **Dockerize** (agent) → Dockerfile; **Build** (tool) → image pushed to **GHCR**.
3. **Test** + **Scan** (tools). Failure → **Diagnose-Fix** (agent) proposes a fix → retry that step.
4. **[GATE]** approve provision → creates namespace + secrets (no Terraform on-prem).
5. **[GATE]** approve deploy → **Helm + ArgoCD** sync to the k3d cluster → **Healthcheck**.
6. Commits into the repo: Dockerfile, CI workflow, Helm chart, ArgoCD Application, **and the Stage-3
   CI Self-Heal workflow** (+ the GHCR/LLM secrets references).

**Done when:** the app is live and healthy in the k3d cluster and the repo carries its pipeline + the
CI Self-Heal workflow.

---
## After setup — Stage 3 is live (no extra install)
Future CI failures auto-trigger the CI Self-Heal Action → it diagnoses → opens a **fix PR** for a human
to merge. Never merges/deploys/weakens a test. Same diagnosis library as Stage 2.

---
## If you ever switch to AWS (later phase)
Only three things change — the agents don't: cluster k3d → EKS, registry GHCR → ECR (AWS creds), and
`provision_infra` gains a real `terraform plan/apply`. Remember AWS bills **per hour** — run a couple of
days and `terraform destroy` everything (incl. NAT gateways, load balancers, EBS, Elastic IPs) to keep
it to ~$10–15 rather than a monthly bill.

## Fill-in checklist
- GitHub org/user: `[TODO]` · GHCR repo path: `ghcr.io/[TODO]/<app>` · kube context: `k3d-[TODO]`
- namespace: `[TODO]` · LLM provider + key var: `[TODO]`
- GitHub PAT scopes: `write:packages, read:packages, repo` · repo secrets for the CI Self-Heal Action: `[TODO]`
