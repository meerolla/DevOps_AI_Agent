# Design Addendum — `--target` Abstraction, EKS Target, and Config File

> Layer this on top of the existing orchestrator (graph/state/agents/tools/artifacts/gitops/approve-resume).
> The agents and graph DO NOT change. Only tool selection + a few new tool implementations + flags.
> Goal: make the flow target-pluggable and add a real EKS target (with Terraform for AWS infra).

## A. Target abstraction
- Add a CLI flag `--target {k3s|eks|gke}` (default `k3s`).
- Introduce a `targets/` package. Each target provides the cluster/cloud-specific pieces behind one
  interface; the generic shell-outs stay in `tools/`. The graph/agents call the interface, not a target.

```
orchestrator/
  targets/
    base.py        # Target interface (abstract)
    k3s.py         # current on-prem behavior (move existing logic here)
    eks.py         # NEW — AWS
    gke.py         # stub (raises "not implemented yet") — shows the seam
  registry.py      # factory: get_target(name) -> Target
```

```python
# targets/base.py  (interface every target implements)
class Target:
    def provision_infra(self, plan, approved: bool) -> ChangeSet: ...   # gate shows this
    def registry_login(self) -> None: ...                              # auth for push
    def image_ref(self, app, tag) -> str: ...                          # full registry path
    def deploy(self, manifests, approved: bool) -> DeployResult: ...   # helm/argocd
    def healthcheck(self, ns, app) -> HealthResult: ...
```
- `tools/infra.py`, `tools/build.py`, `tools/deploy.py` become thin wrappers that call
  `get_target(args.target).<method>(...)`. Existing k3s logic moves into `targets/k3s.py` unchanged.
- Guardrails stay identical: no `provision`/`deploy` runs unless `state.approvals.<x>` is true.

## B. EKS target (`targets/eks.py`)
Prerequisite (NOT provisioned by this tool): an existing EKS cluster + `aws` CLI with credentials
(standard AWS chain: env vars / profile / IAM role). The EKS cluster itself stays a platform prereq,
exactly like k3s.

- **Cluster access:** accept `--cluster <eks-name>` + `--region <region>`; run
  `aws eks update-kubeconfig --name <eks-name> --region <region>` to set the kube-context, then use
  kubectl/Helm/ArgoCD against it (ArgoCD runs on EKS identically to k3s).
- **Registry = ECR:**
  - `registry_login()`: `aws ecr get-login-password --region <region> | docker login --username AWS
    --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com`
  - `image_ref()`: `<acct>.dkr.ecr.<region>.amazonaws.com/<repo>:<tag>`
- **Infra via Terraform (the AWS-path provisioning we were missing):**
  - `provision_infra()` runs a small Terraform module that creates **app-scoped** AWS resources — for
    the POC, at minimum the **ECR repository** (optionally an IAM policy + a Secrets Manager secret).
    It does NOT create the VPC or the EKS cluster (those are prereqs / roadmap).
  - Flow tied to the existing gate: `terraform init` -> `terraform plan -out=tfplan` -> **show the plan
    at `approve_infra`** -> after approval `terraform apply tfplan`. (On k3s, `provision_infra` stays
    namespace + secrets, no Terraform — so the gate is target-aware.)
  - Module location: `targets/eks/terraform/` parameterized by `app_name`, `region`. Keep it minimal.
- **Deploy:** unchanged — Helm + ArgoCD (or direct `helm upgrade --install`) against the EKS context.
- **LLM:** provider stays configurable; Bedrock is an option on AWS but not required.
- **Safety:** AWS creds only from the standard chain; never hardcoded or logged. `terraform apply` and
  `deploy` remain behind the approval gates.

## C. Optional config file — `pipeline-setup.yaml` (at the app repo root)
If present, it OVERRIDES the Planner's inference (reliability lever). If absent, the Planner infers
(current behavior). Never required.

```yaml
target: eks                     # k3s | eks | gke   (CLI --target overrides this)
app:
  language: python              # python | java | node | go ...
  entrypoint: app/main.py
  port: 8080
  health_path: /health
  test_command: pytest
eks:                            # only read when target=eks
  region: ap-south-1
  cluster: my-eks
  ecr_repo: jd-scorer
```
- Precedence: CLI flag > `pipeline-setup.yaml` > Planner inference.
- The Planner reads this file first; for any field present it uses it verbatim and skips inferring it.

## D. New/changed CLI flags
```
--target {k3s|eks|gke}     default k3s
--region <aws-region>      required when target=eks (or from config)
--cluster <name|context>   k3s: kube-context (e.g. default); eks: EKS cluster name
--registry <ref>           optional; for eks, derived from ECR if omitted
```

## E. Tasks to add (for the build agent)
- [ ] TA. Add `targets/base.py` interface; move current k3s logic into `targets/k3s.py`; add
      `get_target()` factory; make `tools/{infra,build,deploy}.py` dispatch via the selected target.
      Add `--target` (default k3s). Existing k3s runs must behave identically. Add a test.
- [ ] TB. Implement `targets/eks.py`: ECR login + image_ref, EKS kubeconfig, Helm/ArgoCD deploy, and
      `provision_infra` via a minimal Terraform module in `targets/eks/terraform/` (ECR repo), wired to
      the `approve_infra` gate (`terraform plan` shown, `apply` only after approval). Add `--region`.
- [ ] TC. Add `gke.py` as a clear "not implemented yet" stub (shows the extension seam).
- [ ] TD. Add optional `pipeline-setup.yaml` loading with precedence CLI > config > inference; the
      Planner consumes it. Add a test for the precedence.

## Scope note (POC vs roadmap)
- **In this POC:** the `--target` seam + EKS target with ECR-via-Terraform + EKS deploy. k3s stays the
  primary demo; EKS is real enough to show it's not hardcoded.
- **Roadmap:** provisioning the VPC/EKS cluster itself, GKE/AKS targets, richer IAM, multi-component apps.
