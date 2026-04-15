---
name: regx-ai
description: >-
  Works on the RegX-AI Regression Dashboard (React CRA + Flask). Covers
  regression home, run plans, triage genie, failed-test analysis, run reports,
  and Jita/Triage Genie/TCMS integrations. Use when editing this repo, adding
  dashboard pages, Flask routes under /mcp/regression/, or regression/triage
  workflows.
---

# RegX-AI (Regression Dashboard)

## Quick facts

- **Frontend:** `src/` — entry `src/App.jsx`, API base `src/config.js` (`REACT_APP_API_URL`).
- **Backend:** `backend/test_flask.py` — Flask + CORS; JSON routes under `/mcp/regression/`.
- **Run:** `python3 backend/test_flask.py` + `npm start` (backend 5001, dev server 3000 with proxy).

## When changing behavior

1. Read **[PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md](../../PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md)** for architecture and env vars.
2. Match existing patterns in the touched page under `src/pages/` or the Flask section for that feature.
3. Large JSON lives in `data/` or `*_config.json` — reference paths, do not paste full datasets into this skill.

## Code review (Gerrit)

Push updates for review to `refs/for/<target-branch>`, not directly to the integration branch.
