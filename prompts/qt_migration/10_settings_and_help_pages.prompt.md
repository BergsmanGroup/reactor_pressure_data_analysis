---
description: "Qt migration step 10 — Settings and Help pages (existing config/docs only)"
---

# 10 — Settings and Help pages

Prerequisite: 07. Owner decision: implement only what existing config/docs support; no placeholders.

## Tasks

1. Settings page: surface the preferences already in `config_default.json` / `config_local.json` (processing defaults, per-reactor valve names, reactor types) using the existing load/save functions. Add "Reset to defaults" only if it maps to copying `config_default.json` values.
2. Help page: links/open actions for `WHITEPAPER.md`, `PROCESSING_WORKFLOW_REVIEW.md`, and the docs folder; app version/Python/PySide6 versions. Correct the stale iSE statement in `WHITEPAPER.md`.
3. If something is not backed by existing config/docs, leave it out.
4. Tests: settings round-trip through `config_local.json` in a temp dir.
