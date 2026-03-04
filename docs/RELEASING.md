# Releasing

## `aro-installer` (npm)

This repo includes an npm package at `integrations/npm/aro-installer`.

### One-time setup (npm)

Enable npm Trusted Publishing (GitHub Actions OIDC) for the `aro-installer` package so GitHub Actions can publish
without storing long-lived tokens.

On npmjs.com:
1) Open `aro-installer` → **Settings** → **Trusted Publishers** (GitHub Actions).
2) Add this repo (`loganrooks/agentic-research-orchestrator`) and set the workflow filename to
   `npm-publish-aro-installer.yml` (filename only, not the path).

This workflow already requests `permissions: id-token: write` and publishes with `--provenance`.
It also uses Node 24 (npm 11+) because npm Trusted Publishing requires a recent npm CLI (see npm docs).

### Release steps

1) Bump the version in:
   - `integrations/npm/aro-installer/package.json`

2) Commit and push to `main`.

3) Tag and push a tag of the form:

```bash
git tag aro-installer-vX.Y.Z
git push origin aro-installer-vX.Y.Z
```

GitHub Actions will:
- run tests
- verify the tag version matches `package.json`
- publish to npm
- create a GitHub Release (with auto-generated notes) and attach the `npm pack` tarball
