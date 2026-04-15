# AGENTS.md — RegX-AI

This file gives AI coding agents quick orientation for the **RegX-AI** (Regression Dashboard) repository.

## What this project is

- **React (CRA)** frontend in `src/`
- **Flask** backend in `backend/test_flask.py` (API prefix `/mcp/regression/`)
- Local dev: frontend port **3000**, backend **5001** (see `package.json` proxy)

## Read first

- **[PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md](PROJECT_DOCUMENTATION_AND_ARCHITECTURE.md)** — architecture, env vars, data layout, API overview
- **[README.md](README.md)** — install and run commands

## Cursor-specific

- Project skill: `.cursor/skills/regx-ai/SKILL.md`
- Project rules: `.cursor/rules/regx-ai.mdc`

## Conventions

- Do not commit secrets; use environment variables (see architecture doc).
- For Gerrit/code review, push to `refs/for/<branch>` rather than directly to the target branch when opening or updating a change.
