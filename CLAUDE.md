# CLAUDE.md

Collector for U.S. Congress STOCK Act trading disclosures. Public repo, holds paid
secrets (R2, Supabase, Telegram) as GitHub Actions secrets. See README's "public by
design" note for why it's public and what that trades off.

## Before merging or approving any PR here

This repo's one real attack surface is a fork's pull request modifying a
`.github/workflows/*.yml` file to try to exfiltrate a secret. Before merging anything,
or clicking "Approve and run" on a fork's workflow run:

1. Run (or confirm CI ran) `congress_collector.ops.check_workflow_secrets` — it fails
   red if a `pull_request`-triggered workflow references a secret, or if
   `pull_request_target` appears at all. Never merge past a red run of this check
   without understanding exactly why it's red.
2. If the PR touches `.github/workflows/**`, read the diff yourself line by line even
   if CI is green — the check above catches the specific pattern of secrets +
   `pull_request`, not every way a workflow file could be made to do something
   unwanted.
3. Confirm Settings → Actions → General → "Fork pull request workflows from outside
   collaborators" is still set to require approval for **all** outside collaborators,
   not just first-time ones. If you find it's been changed to something looser, treat
   that itself as suspicious and ask the owner before approving anything.

## Commands

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run python -m congress_collector.ops.check_workflow_secrets
```

See `README.md` for architecture, data model, and everything else.
