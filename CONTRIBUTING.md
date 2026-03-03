# Contributing

Thanks for helping improve Agentic Research Orchestrator (ARO).

## Development

Prereqs:
- Python 3.11+
- Node 18+ (needed for the `aro-installer` tests)

Run tests:

```bash
pytest -q
```

## Changes

Please keep changes focused and easy to review:
- Prefer small PRs with a clear purpose.
- Add/adjust tests when behavior changes.
- Update docs when CLI or run-bundle behavior changes.

## Packaging notes

- The core orchestrator is a Python package (`agentic-research-orchestrator`).
- The installer is an npm package in `integrations/npm/aro-installer`.

For `aro-installer` releases, see `docs/RELEASING.md`.

