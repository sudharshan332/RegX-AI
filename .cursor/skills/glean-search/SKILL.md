---
name: glean-search
description: Query internal company documentation using the local Glean chat wrapper. Use when the user asks to read or summarize Google Docs, asks company-knowledge questions, or asks product-specific questions that require internal docs/runbooks/RFCs.
---

# Glean Search

## Purpose

Use this skill to answer questions from internal company knowledge via:

`python3 .cursor/skills/glean-search/scripts/glean_chat.py`

Use this when internal context is required and public web search is not
enough.

## When To Use

Trigger this skill when the user asks for:
- Content or summaries from Google Docs links
- Company-specific docs, runbooks, policies, RFCs, or internal processes
- Product-specific internal behavior, troubleshooting, architecture, or
  operational details

Do not use this skill for direct source-code analysis.

## Prerequisites

- Python dependency is available: `requests`
- Valid auth cookie is available through one of:
  - `--okta-session-store TOKEN`
  - `OKTA_SAML_HOSTED_LOGIN_SESSION_STORE` environment variable
  - `.env` file key `OKTA_SAML_HOSTED_LOGIN_SESSION_STORE`
  - custom env file via `--env-file PATH`

Never print raw cookie values in responses.

## Default Command Pattern

Prefer non-streaming JSON for machine-readable output:

```bash
python3 .cursor/skills/glean-search/scripts/glean_chat.py \
  --no-stream --json \
  "USER_QUESTION"
```

## Mode Selection

Use `--mode` deliberately:
- `thinking`: default for most internal knowledge questions
- `fast`: simple fact lookup
- `auto`: let Glean choose
- `deep_research`: long-form report, can take longer
- `gpt_no_web`: ground answers in company knowledge only

Examples:

```bash
python3 .cursor/skills/glean-search/scripts/glean_chat.py \
  --mode thinking --no-stream --json \
  "Summarize this Google Doc: <url>"

python3 .cursor/skills/glean-search/scripts/glean_chat.py \
  --mode fast --no-stream --json \
  "What does internal docs say about CFS?"

python3 .cursor/skills/glean-search/scripts/glean_chat.py \
  --mode gpt_no_web --no-stream --json \
  "How does our product handle <feature>?"
```

## Conversation Continuity

For follow-ups on the same topic:

1. List chats:
```bash
python3 .cursor/skills/glean-search/scripts/glean_chat.py --list-chats --json
```

2. Continue a chat:
```bash
python3 .cursor/skills/glean-search/scripts/glean_chat.py \
  --chat-id CHAT_ID --no-stream --json \
  "FOLLOW_UP_QUESTION"
```

## Agent Workflow

1. Detect if the request is Google Doc content or internal company/product
   knowledge.
2. Choose mode (`thinking` unless speed/constraints suggest another mode).
3. Run `glean_chat.py` with `--no-stream --json`.
4. Extract assistant answer text and cited sources when available.
5. If incomplete, run one focused follow-up in the same chat context.
6. Return a concise synthesis and clearly call out uncertainty.

## Failure Handling

- Missing cookie error: ask user to refresh login and set one of supported
  auth inputs.
- `401`/`403`: cookie expired or invalid; ask user to refresh session and retry.
- Other request failures: report error briefly and retry once.
- Weak answer quality: retry with `--mode thinking`, then
  `--mode deep_research` for complex topics.

## Output Guidance

- Provide a short direct answer first.
- Include key supporting points.
- If sources are returned, list them succinctly.
- Do not expose secrets/tokens from commands or environment.
