# ArgoCD Application Reference

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: <app-name>
  namespace: argocd
spec:
  project: default
  source:
    repoURL: <git-remote-url>
    targetRevision: main
    path: deploy/helm
  destination:
    server: https://kubernetes.default.svc
    namespace: <app-namespace>
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## Rules
- `repoURL` must be a real Git URL from origin remote.
- `targetRevision` should be branch name, never HEAD or latest.
- Application metadata namespace is `argocd`.
- Destination namespace is app namespace.
