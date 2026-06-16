# One-Time Setup — On-Prem Platform (k3s OR k3d) + ArgoCD + GHCR

> Run ONCE on your Ubuntu machine to create the platform the orchestrator deploys onto.
> Pick **one** cluster option below (Step 1), then do the common steps (2 onward).
> Commands are illustrative — adjust versions/names. Anything in `<...>` is yours to fill in.

## 0. Machine prep
```bash
sudo apt-get update && sudo apt-get install -y curl
```
Recommended minimum: 4 CPU / 8 GB RAM / 30 GB free disk.

---
## Step 1 — Choose ONE cluster option

### Option A — k3s  (single-node · lightest · no Docker needed)
Best if you just want a working cluster with the least overhead. k3s installs as a system service and
uses its own containerd (no Docker required).
```bash
# install k3s (runs as a service)
curl -sfL https://get.k3s.io | sh -

# make kubectl usable as your user
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER:$USER ~/.kube/config
export KUBECONFIG=~/.kube/config            # add this line to ~/.bashrc to persist

kubectl get nodes                           # one node, Ready
```
- Kube-context name: **`default`** → use `--cluster default` at run time.
- k3s bundles kubectl as `k3s kubectl`; copying the kubeconfig above lets standalone
  `kubectl`/`helm`/`argocd` work too.
- Teardown later: `sudo /usr/local/bin/k3s-uninstall.sh`

### Option B — k3d  (multi-node on one box · needs Docker)
Best if you want to demo multi-node behavior. k3d runs k3s nodes as Docker containers.
```bash
# Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER               # then log out/in (or: newgrp docker)

# kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# k3d
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash

# multi-node cluster: 1 server + 2 agents
k3d cluster create mycluster --servers 1 --agents 2 --port "8080:80@loadbalancer"
kubectl get nodes                           # 3 nodes
```
- Kube-context name: **`k3d-mycluster`** → use `--cluster k3d-mycluster` at run time.
- Not real HA (one physical host), but behaves like multi-node for scheduling/rollouts/demos.
- Teardown later: `k3d cluster delete mycluster`

> Not sure which you have? `command -v k3s` or `command -v k3d`. If neither, Option A (k3s) is the
> simplest to install. Single-node k3s is fine for the whole POC.

---
## Step 2 — Install Helm  (both options)
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version
```
(Option A users: kubectl came with the k3s kubeconfig above; no separate install needed.)

## Step 3 — Install ArgoCD  (both options)
```bash
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server

# initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo

# reach the UI (separate terminal)
kubectl -n argocd port-forward svc/argocd-server 8081:443
# open https://localhost:8081  (user: admin)
```

## Step 4 — GHCR access (registry)  (both options)
Create a GitHub Personal Access Token (classic) with `write:packages`, `read:packages`, `repo`.
```bash
# log in so build/push works (Option B needs Docker for this; Option A can use any container tool)
echo "<GITHUB_PAT>" | docker login ghcr.io -u "<github-username>" --password-stdin

# app namespace + image pull secret so the cluster can pull private images
kubectl create namespace <app-namespace>
kubectl -n <app-namespace> create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io \
  --docker-username="<github-username>" \
  --docker-password="<GITHUB_PAT>"
```
> Public GHCR images need no pull secret. Private ones sit in your GitHub plan's Packages quota
> (effectively free at POC scale).
> (k3s without Docker: build/push images from any machine that has Docker/Podman, or run the build
> step where Docker is available — the cluster only needs to *pull*, which the secret above covers.)

## Step 5 — LLM key (for the judgment agents)  (both options)
```bash
export OPENAI_API_KEY="<key>"        # or:
export ANTHROPIC_API_KEY="<key>"
# or skip for offline runs/tests: export LLM_MODE=mock
```
Put the same key into the target repo's **Actions secrets** later, so the Stage-3 CI Self-Heal
workflow can call the model.

## Step 6 — Verify the platform
```bash
kubectl get nodes              # Ready (1 for k3s, 3 for k3d)
kubectl -n argocd get pods     # argocd pods Running
helm version                   # Helm present
```

## Step 7 — Configure post-merge activation automation
The generated app workflow `.github/workflows/post-merge-activate.yml` runs after merge to `main`.
It expects a **self-hosted GitHub Actions runner** with cluster access and these tools installed:
- `kubectl`
- `helm`
- optional `argocd` CLI (workflow falls back to ArgoCD automated sync if missing)

### 7.1 Prepare runner host
Use a Linux host that can reach your Kubernetes API server and GitHub.
```bash
sudo apt-get update
sudo apt-get install -y curl tar git jq

# install kubectl if missing
command -v kubectl >/dev/null || {
  curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
  sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
}

# install helm if missing
command -v helm >/dev/null || curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### 7.2 Register self-hosted runner in GitHub
In the target app repository:
- `Settings` -> `Actions` -> `Runners` -> `New self-hosted runner`
- choose `Linux` + `x64`
- copy the generated download/config commands and run them on the runner host

Typical command sequence:
```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
# download URL/version/token are provided by GitHub UI
curl -o actions-runner-linux-x64.tar.gz -L <download-url-from-github>
tar xzf actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/<owner>/<repo> --token <registration-token> --labels self-hosted,linux,k8s
sudo ./svc.sh install
sudo ./svc.sh start
```

### 7.3 Configure Kubernetes access for runner user
The runner service user must have a kubeconfig with the context you pass to orchestrator `run --cluster ...`.
```bash
mkdir -p ~/.kube
# copy or create kubeconfig for the runner user
kubectl config get-contexts
kubectl get nodes
helm version
```

### 7.4 Verify runner is online
- In GitHub repo `Settings` -> `Actions` -> `Runners`, status should be `Idle`.
- Trigger a simple workflow dispatch to confirm the job lands on the self-hosted runner.

This enables fully automated Phase B activation with no manual deploy CLI wait.

## You're done — what exists now
- A Kubernetes cluster (context `default` for k3s, or `k3d-mycluster` for k3d).
- ArgoCD installed and reachable.
- GHCR login + a pull secret in your app namespace.
- An LLM key (or mock mode).
- Self-hosted Actions runner ready for post-merge activation workflow.

Next, follow **RUNBOOK.md Part 3**, passing the matching `--cluster` context.

## Teardown
- k3s: `sudo /usr/local/bin/k3s-uninstall.sh`
- k3d: `k3d cluster delete mycluster`

(No cloud resources either way — nothing keeps billing, unlike the AWS path.)
