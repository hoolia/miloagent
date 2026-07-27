---
name: miloagent
description: Use when editing or inspecting MiloAgent dashboard projects, prompt templates, or personas via its HTTPS API at milo.grn.cloud - listing/creating/updating a project, editing a prompt or persona per project, or reverting an override. Not for cluster/pod operations (use oc) or Reddit account/token work.
---

# MiloAgent - Dashboard project, prompt, and persona management

Self-contained: one stdlib-only CLI (`scripts/milo-tool.py`) that authenticates to the
MiloAgent dashboard REST API and edits projects, prompt templates, and personas. No pip
install. Copy this directory to reuse.

## Scripts

```bash
TOOL=.claude/skills/miloagent/scripts/milo-tool.py

# Connectivity (no auth)
$TOOL health

# Projects (persist to the projects/*.yaml on the PVC)
$TOOL projects                                  # list
$TOOL project-schema                            # the editable field tree
$TOOL project get grncloud
$TOOL project set grncloud --json '{"project":{"tagline":"New tagline"}}'
$TOOL project set grncloud --file patch.json    # same, patch from a file
$TOOL project create --name X --url https://x --description "..." [--type SaaS --weight 1.0 --tagline "..."]
$TOOL project delete X

# Prompt templates (per-project DB overrides, applied live)
$TOOL prompts --project grncloud                # list; has_override marks edited ones
$TOOL prompt get reddit_comment --project grncloud   # body -> stdout, name/state/placeholders -> stderr
$TOOL prompt set reddit_comment --project grncloud --file new.txt   # or --content '...'
$TOOL prompt revert reddit_comment --project grncloud              # back to built-in default

# Personas (per-project DB overrides, YAML)
$TOOL personas --project grncloud
$TOOL persona get dev_tech --project grncloud
$TOOL persona set dev_tech --project grncloud --file persona.yaml   # or --content '...'
$TOOL persona revert dev_tech --project grncloud
```

Edit-then-verify: after `set`, run the matching `get`/list to confirm `has_override` /
effective text. All output is JSON except `prompt get`/`persona get`, which print the
effective content to stdout (pipe-friendly) and a state header to stderr.

## Credentials

The CLI reads `MILO_WEB_USER` (default `admin`) and `MILO_WEB_PASS` from the environment,
and `MILO_BASE` (default `https://milo.grn.cloud`). Source `MILO_WEB_PASS` fresh from
Vaultwarden (`vault.grn.cloud`) each run - never hardcode it or rely on a shell profile.
Vault item: `MiloAgent dashboard - milo.grn.cloud (openshift-config)`.

The login token is cached under the system temp dir (0600, keyed by host+user) and reused
for its 24h life; a `401` triggers one transparent re-login and retry.

## Gotchas

- **Per-project.** Prompt/persona edits are scoped to `--project` (e.g. `grncloud`); other
  projects keep defaults. Project edits target `projects/<name>.yaml`.
- **Project `set` is a deep-merge:** dicts merge key-wise, but **lists and scalars REPLACE**.
  To append to a list (keywords, features, ...), send the full new list, not just the addition.
- **Prompt placeholders are enforced.** An edited template may only use `{placeholders}` that
  the built-in default already has; an unknown one returns `400 Unknown placeholders: ...`
  (surfaced verbatim). `prompt get` prints the allowed set. A bad override can never crash
  generation - the server falls back to the file default.
- **Live, no restart.** Prompt/persona overrides are read from the PVC DB per generation, so a
  saved edit applies to the next comment/post immediately. Projects hot-reload via the file
  watcher.
- **Revert = built-in default.** `prompt revert` / `persona revert` delete the override row;
  the bot falls back to the image-baked default. Personas revert to the `expert_personas.yaml`
  default.
- **Sessions are in-memory** on the dashboard; a pod restart invalidates tokens - the CLI
  re-logins automatically on the next call.
