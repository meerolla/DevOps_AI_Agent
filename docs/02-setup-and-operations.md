# Setup and Operations

This document consolidates one-time platform setup and per-app runtime operations.

Scope: current phase. Stage 1 (build the app) is separate; Stage 4 (runtime triage) is next phase.
Target: on-prem k3s/k3d cluster plus GHCR registry.

Golden rule: agents do judgment, tools do execution, and orchestration enforces safety policy.

Immediate execution priority: Real LLM Agent Core. Planner, Dockerizer, and Diagnose-Fix must behave as repo-aware agents, not static templates.

## Part 1: Build the Orchestrator Tools (One Time)

1. Rename dotgithub/ to .github/ if needed.
2. Open orchestrator repo in VS Code.
3. Create virtual environment.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

4. If using the agent-builder flow, point it at specs/tasks.md.
5. Verify offline.

```bash
SANDBOX=1 LLM_MODE=mock pytest -q
```

6. Package pip wheel for CLI and reusable action template.

Done when CLI installs and sandbox run completes end-to-end with gates.

## Part 2: Platform Prerequisites Checklist (One Time)

On-prem, single Ubuntu machine:
- Docker installed.
- k3d installed and multi-node cluster created (1 server + 2 agents), or k3s single-node.
- ArgoCD installed and reachable.
- GHCR access with PAT scopes write:packages, read:packages, repo.
- LLM provider environment exported in the same shell used to run the orchestrator.
- Self-hosted GitHub Actions runner with access to Kubernetes API.

No AWS, no EKS, no ECR, no Terraform required on this path.

## Part 3: One-Time Platform Setup (Detailed)

Run once on Ubuntu machine.

### 0. Machine prep

```bash
sudo apt-get update && sudo apt-get install -y curl
```

Recommended minimum: 4 CPU / 8 GB RAM / 30 GB disk.

### Step 1: Choose one cluster option

#### Option A: k3s

```bash
curl -sfL https://get.k3s.io | sh -
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
export KUBECONFIG=~/.kube/config
kubectl get nodes
```

- kube context: default
- teardown: `sudo /usr/local/bin/k3s-uninstall.sh`

#### Option B: k3d

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
k3d cluster create mycluster --servers 1 --agents 2 --port "8080:80@loadbalancer"
kubectl get nodes
```

- kube context: k3d-mycluster
- teardown: `k3d cluster delete mycluster`

If unsure which is installed:

```bash
command -v k3s
command -v k3d
```

If neither is available, k3s is the simplest starting option.

### Step 2: Install Helm

```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```

If using k3s with copied kubeconfig above, standalone kubectl, helm, and argocd can all use the same context.

### Step 3: Install ArgoCD

```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server

kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
kubectl -n argocd port-forward svc/argocd-server 8081:443
```

### Step 4: GHCR access

Create PAT with scopes: write:packages, read:packages, repo.

```bash
echo "<GITHUB_PAT>" | docker login ghcr.io -u "<github-username>" --password-stdin

kubectl create namespace <app-namespace>
kubectl -n <app-namespace> create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username="<github-username>" \
  --docker-password="<GITHUB_PAT>"
```

### Step 5: LLM mode and provider setup

Use these settings in the same shell/session that invokes `pipeline-setup` or `python -m orchestrator.main`.

```bash
export LLM_MODE=provider
export OPENAI_API_KEY="<key>"
export OPENAI_MODEL="gpt-4o-mini"   # optional
# or
export ANTHROPIC_API_KEY="<key>"
# or
export LLM_MODE=mock
```

Important:
- `OPENAI_API_KEY` is the recognized variable name.
- `OPENAI_KEY` alone is not sufficient for provider mode.
- If env vars are set in a different terminal session, the orchestrator process will not see them.

### Step 6: Verify platform

```bash
kubectl get nodes
kubectl -n argocd get pods
helm version
```

### Step 7: Configure self-hosted runner for post-merge activation

The generated workflow `.github/workflows/post-merge-activate.yml` runs on `self-hosted` runner labels.

#### 7.1 Prepare runner host

```bash
sudo apt-get update
sudo apt-get install -y curl tar git jq

command -v kubectl >/dev/null || {
  curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
}

command -v helm >/dev/null || curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

Optional but recommended:
- install `argocd` CLI for explicit sync visibility

#### 7.2 Register runner in target app repository

In GitHub: `Settings` -> `Actions` -> `Runners` -> `New self-hosted runner`.

Run provided commands on runner host, for example:

```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L <download-url-from-github>
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/<owner>/<repo> --token <registration-token> --labels self-hosted,linux,k8s
sudo ./svc.sh install
sudo ./svc.sh start
```

#### 7.3 Configure Kubernetes access for runner user

```bash
kubectl config get-contexts
kubectl get nodes
helm version
```

The runner must have the same kube context referenced in orchestrator run command `--cluster` argument.

## Part 4: Run on an App (Per App)

### Primary run command

```bash
pipeline-setup run --repo ./my-app --cluster k3d-mycluster --registry ghcr.io/<org>/my-app --namespace my-app
```

Equivalent module invocation:

```bash
python -m orchestrator.main run --repo ../resume-scorer --cluster default --registry ghcr.io/meerolla/resume-scorer --namespace my-app --goal "given an app repo, set up CI/CD and deploy it"
```

Bootstrap run executes pre-merge phase only (plan/build/test/scan/provision/finalize).
Post-merge deployment activates automatically through generated GitHub workflow.

### Validate provider mode is active

Before a run, verify your shell has provider vars:

```bash
echo "$LLM_MODE"
echo "$OPENAI_API_KEY" | wc -c
```

Expected:
- `LLM_MODE` prints `provider` for real-provider runs.
- `OPENAI_API_KEY` length check is non-zero.

### Gate approvals (bootstrap)

```bash
pipeline-setup approve --repo ./my-app --step infra
pipeline-setup resume --repo ./my-app
```

Deploy approval is currently automated in post-merge activation workflow.

### Retry from failed step after manual fix

```bash
pipeline-setup retry --repo ./my-app --from-step test
```

If post-merge activation needs manual recovery, run:

```bash
python -m orchestrator.main activate --repo ./my-app --cluster <context> --registry ghcr.io/<org>/my-app --namespace <namespace> --auto-approve-deploy
```

### Draft PR behavior

Generated assets are committed and draft PR is opened by default.
- requires GITHUB_TOKEN with repo scope
- disable with `--no-draft-pr`

### Operational sequence

1. Planner inspects repo evidence and produces BuildPlan.
2. Dockerizer generates an app-specific Dockerfile; build tool validates and pushes image to GHCR.
3. Test and scan run; failures route to Diagnose-Fix and retry or escalate.
4. Infra approval gate then provision.
5. Finalize validates artifacts, commits generated assets, and opens draft PR by default.
6. After merge to `main`, post-merge workflow runs activation (deploy + healthcheck).

### Quick realism checks (avoid template regressions)

After a run, validate generated outputs are app-specific:
- Dockerfile runtime command matches framework (for FastAPI use uvicorn command, not generic http.server).
- BuildPlan fields differ across different app fixtures (for example Python/FastAPI versus Node/Express).
- Diagnose-Fix suggestions remain inside generated artifact boundaries.

### Expected generated artifacts

- Dockerfile
- .github/workflows/ci.yml
- .github/workflows/ci-self-heal.yml
- .github/workflows/post-merge-activate.yml
- deploy/helm/Chart.yaml
- deploy/helm/values.yaml
- deploy/helm/templates/deployment.yaml
- deploy/argocd/application.yaml

Done when the app is live and healthy in cluster and the repo contains generated pipeline assets.

## After Setup: Stage 3 Behavior

Future CI failures can trigger the Stage-3 CI self-heal workflow.
The expected pattern is diagnose and open fix PR for human review; never auto-merge, never weaken tests/scans.

## If You Switch to AWS Later

Only three dimensions change:
- cluster: k3d to EKS
- registry: GHCR to ECR
- provision_infra: can include real terraform plan/apply

Cost note: AWS bills by the hour. Destroy resources (including NAT gateways, load balancers, EBS, and Elastic IPs) after short-lived experiments.

## Fill-In Checklist

- GitHub org/user: [TODO]
- GHCR repo path: ghcr.io/[TODO]/<app>
- kube context: k3d-[TODO] or default (k3s)
- namespace: [TODO]
- LLM provider and key var: [TODO]
- GitHub PAT scopes: write:packages, read:packages, repo
- Repo secrets for CI self-heal workflow: [TODO]

## Teardown

- k3s: `sudo /usr/local/bin/k3s-uninstall.sh`
- k3d: `k3d cluster delete mycluster`

No cloud resources are created on this on-prem path, so there is no cloud billing loop to clean up.
