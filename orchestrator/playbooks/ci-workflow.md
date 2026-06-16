# CI Workflow Reference

## Structure
- pull_request: run tests only.
- push to main: run tests, build and push image to GHCR, bump deploy/helm/values.yaml image tag, commit with [skip ci].

## Tag bump
- Only modify `image.tag` in deploy/helm/values.yaml.
- Tag value should be commit SHA from triggering run.
- Commit message includes `[skip ci]`.

## Permissions
```yaml
permissions:
  contents: write
  packages: write
```
