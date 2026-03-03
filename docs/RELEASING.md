# Releasing

## `aro-installer` (npm)

This repo includes an npm package at `integrations/npm/aro-installer`.

### One-time setup (GitHub)

Add a repo secret named `NPM_TOKEN` with an npm automation token that can publish `aro-installer`.

Recommended:
- Enable npm 2FA for publishes.
- Use a dedicated automation token (not your personal session token).

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
