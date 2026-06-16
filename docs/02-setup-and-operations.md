# Setup and Operations

This document consolidates one-time platform setup and per-app runtime operations.

Scope: current phase. Stage 1 (build the app) is separate; Stage 4 (runtime triage) is next phase.
Target: on-prem k3s/k3d cluster plus GHCR registry.

Golden rule: agents do judgment, tools do execution, humans approve destructive steps.

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
- LLM key exported (OPENAI_API_KEY or ANTHROPIC_API_KEY) or mock mode enabled.

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

### Step 5: LLM key

```bash
export OPENAI_API_KEY="<key>"
# or
export ANTHROPIC_API_KEY="<key>"
# or
export LLM_MODE=mock
```

### Step 6: Verify platform

```bash
kubectl get nodes
kubectl -n argocd get pods
helm version
```

## Part 4: Run on an App (Per App)

### Primary run command

```bash
pipeline-setup run --repo ./my-app --cluster k3d-mycluster --registry ghcr.io/<org>/my-app --namespace my-app
```

Equivalent module invocation:

```bash
python -m orchestrator.main run --repo ../resume-scorer --cluster default --registry ghcr.io/meerolla/resume-scorer --namespace my-app --goal "given an app repo, set up CI/CD and deploy it"
```

### Gate approvals

```bash
pipeline-setup approve --repo ./my-app --step infra
pipeline-setup resume --repo ./my-app
pipeline-setup approve --repo ./my-app --step deploy
pipeline-setup resume --repo ./my-app
```

### Retry from failed step after manual fix

```bash
pipeline-setup retry --repo ./my-app --from-step test
```

### Draft PR behavior

Generated assets are committed and draft PR is opened by default.
- requires GITHUB_TOKEN with repo scope
- disable with `--no-draft-pr`

### Operational sequence

1. Plan agent produces BuildPlan.
2. Dockerizer produces Dockerfile; build tool pushes image to GHCR.
3. Test and scan run; failures route to Diagnose-Fix and retry or escalate.
4. Infra approval gate then provision.
5. Deploy approval gate then Helm and ArgoCD deploy.
6. Healthcheck verifies rollout.
7. Generated pipeline artifacts are committed and draft PR is opened by default.

### Expected generated artifacts

- Dockerfile
- .github/workflows/ci.yml
- .github/workflows/ci-self-heal.yml
- helm/Chart.yaml
- helm/values.yaml
- helm/templates/deployment.yaml
- argocd/application.yaml

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
