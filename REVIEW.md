# Review guidance

This project is MiloAgent, a Python agent that posts as real accounts on Reddit, Telegram
and Twitter, generates content with LLM providers and serves a web dashboard (port 8420).
It is deployed from `deploy/` (Helm chart) on OpenShift. The agent acts under real
identities, so a bug becomes a ban, spam or a leaked session.

## Always P0 or P1

- A credential or session is committed: Reddit `password` or `token_v2`, cookies, Telegram
  `.session` files, LLM API keys, `.env`, `config/*.local.yaml`, `projects/*.yaml`, or
  `data/*.db`. Real values belong in the Helm secrets, never in git.
- The dashboard auth is weakened: default `MILO_WEB_PASS=changeme` accepted, an
  unauthenticated route, a new endpoint that can act or read config, or the dashboard bound
  or exposed (`deploy/templates/route.yaml`) without credentials.
- A change in `safety/` (rate limiter, ban detector, dedup, account manager) or in
  `core/content_validator.py` that lets the agent post more often, skip the dedup, ignore
  a ban or removal signal, or post unvalidated LLM output.
- Posting to a platform bypasses `safety/rate_limiter.py`, or a new action path does not
  go through the orchestrator checks.
- Content from Reddit or other users reaches an LLM prompt and then an action (post,
  reply, command, file or shell access) without validation (prompt injection).
- A secret is logged, written to `logs/`, or sent to an LLM provider as prompt content.
- Chart or image changes that widen privileges: SCC `anyuid` binding, a root container,
  a secret rendered into a ConfigMap, or an unpinned third-party action with `packages: write`.

## Also check

- New configuration has a template in `config/` or `deploy/files/` with placeholder values.
- SQLite schema changes in `core/database.py` migrate existing data.
- Dependencies in `requirements.txt` are pinned.
- Tests in `tests/` cover a changed safety rule.

## Out of scope

- Prompt wording, persona text, README marketing copy, screenshots, formatting.
