---
name: gerrit-comment-resolver
description: >-
  Fetch and resolve unresolved Gerrit review comments on a change using
  Gerrit REST APIs. Fixes code, posts AI-prefixed reply comments, marks
  threads resolved, and pushes new patchsets. Use when the user asks to
  resolve comments, fix review feedback, address Gerrit CR comments, or
  mentions a Gerrit change ID / commit hash for comment resolution.
---

# Gerrit Comment Resolver

Resolve unresolved review comments on a Gerrit change by fetching them
via the REST API, checking out the correct patchset locally, analysing
each comment, fixing valid ones or drafting counter-responses, posting
replies back to Gerrit, and pushing a new patchset.

## Prerequisites

**Credentials** are resolved automatically in this order:

1. **`~/.git-credentials`** (most developers already have this).
   The script reads the file, extracts the Gerrit host from
   `git remote -v`, and matches it to a credentials line:
   ```
   https://your.username:http-password@nugerrit.ntnxdpro.com
   ```
   No extra setup needed if this file exists.

2. **`~/.gerrit-credentials`** (fallback, shell-export format):
   ```
   export GERRIT_HOST="https://nugerrit.ntnxdpro.com"
   export GERRIT_USER="<username>"
   export GERRIT_HTTP_PASSWORD="<http-password>"
   ```

Helper script: `~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py`

## Workflow

Copy this checklist and track progress:

```
Task Progress:
- [ ] Step 1: Identify the change
- [ ] Step 2: Fetch unresolved comments
- [ ] Step 3: Ensure correct patchset is checked out locally
- [ ] Step 4: Analyse and resolve each comment
- [ ] Step 5: Summarise actions taken
```

### Step 0: Verify Environment

Before starting, confirm basic prerequisites:

```bash
git rev-parse --is-inside-work-tree
```

If this fails, the user is **not inside a git repository**. Inform
them and abort — the skill cannot operate without a git repo.

Also verify a remote exists:

```bash
git remote get-url origin
```

If this fails, there is no `origin` remote. Warn and abort.

### Step 1: Identify the Change

Accept any of these from the user:
- **Gerrit change number**: e.g. `410821`
- **Gerrit URL**: e.g. `https://nugerrit.ntnxdpro.com/c/nutest-py3-tests/+/410821`
- **Change-Id string**: e.g. `I1a2b3c4d...`
- **Commit hash**: e.g. `abc123def`

If given a URL, extract the numeric change number from the path segment
after `+/`. If given a commit hash or Change-Id string, search Gerrit:

```bash
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  search "commit:<hash>"
# or for a Change-Id:
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  search "<Change-Id>"
```

Extract the numeric change number from the search result.

- **If `[]` (empty)** — no matching change found. Inform the user
  and ask them to verify the input.
- **If multiple results** — present the list (change number, subject,
  project, status) and ask the user to pick the correct one. Do not
  guess.

### Step 1b: Validate the Change

After identifying the change, fetch its detail and validate:

```bash
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  detail <change_id>
```

**Check status:** If `status` is `ABANDONED` or `MERGED`, stop and
inform the user — there is no point fixing comments on a closed change.

**Check project matches current repo:** Compare the `project` field
from the detail (e.g. `nutest-py3-tests`) against the current repo:

```bash
basename "$(git remote get-url origin)" .git
```

If they don't match, warn the user they may be in the wrong repository
and abort unless they explicitly confirm.

### Step 2: Fetch Unresolved Comments

Run the helper to get only unresolved comments:

```bash
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  unresolved <change_id>
```

Output is JSON: `{ "<file_path>": [ { comment objects } ] }`.

**If the output is `{}`** (empty) — there are no unresolved comments.
Inform the user and stop. No need to proceed to Step 3.

**Thread resolution model:** In Gerrit, each comment carries its own
`unresolved` flag, but a thread's overall status is determined by the
**last** comment in the reply chain. A reply with `unresolved: false`
(e.g. the author replying "Done") resolves the entire thread, even
though earlier comments still retain `unresolved: true`. The helper
script accounts for this — it groups comments into threads and only
returns comments from threads where the last reply is still unresolved.

Each comment object contains:
- `id` — comment ID
- `path` — file path the comment is on
- `line` — line number (may be absent for file-level comments)
- `message` — the reviewer's comment text
- `author` — who wrote the comment
- `patch_set` — patchset number the comment was posted on
- `in_reply_to` — parent comment ID (for threaded replies)
- `unresolved` — individual comment flag (thread status is
  determined by the last comment in the chain)

**Sanity check:** Compare the number of unique threads returned
(group by root comment, i.e. comments without `in_reply_to`) against
`unresolved_comment_count` from the detail fetched in Step 1b. If
these numbers diverge significantly, something may be wrong — stop
and warn the user rather than acting on potentially stale data.

Note the current patchset number from the detail fetched in Step 1b.

### Step 3: Ensure Correct Patchset Is Checked Out

#### 3a. Record current branch

Save the user's current branch so we can return to it in Step 5:

```bash
git rev-parse --abbrev-ref HEAD
```

Store this value (e.g. `original_branch`). If the result is `HEAD`
(detached), record the commit hash instead via `git rev-parse HEAD`.

#### 3b. Check if user is already on the correct patchset

Use the `current_revision` commit hash from the detail already
fetched in Step 1b (no additional API call needed).

Compare with the local HEAD:

```bash
git rev-parse HEAD
```

**Case 1 — HEAD matches `current_revision` exactly:**
The user is on the correct patchset. **Stay on the current branch.**

**Case 2 — HEAD does not match, but patchset is an ancestor:**

```bash
git merge-base --is-ancestor <current_revision> HEAD
```

If exit code is 0, the patchset commit is an ancestor of HEAD —
the user has the correct patchset **plus extra local commits on
top** (e.g. uncommitted fixes from a previous run, or stacked
changes). **Stay on the current branch.** Do not switch away — that
would lose their local work.

**Case 3 — HEAD does not match and patchset is not an ancestor:**
The correct patchset is not checked out. Continue to 3c.

**In Cases 1 and 2**, before proceeding to Step 4, check if the
working tree is dirty:

```bash
git status --porcelain
```

If dirty, warn the user:
> Your working tree has uncommitted changes. These will appear in
> the diff output alongside any fixes made by this skill. Consider
> committing or stashing first for a clean diff.

Proceed anyway (the user is on the right branch, so no switch
needed), but note this in the Step 5 summary.

#### 3c. Guard against dirty working tree

Before any branch switch, check for uncommitted changes:

```bash
git status --porcelain
```

- **If output is empty** — clean, safe to proceed to 3d.
- **If output is non-empty** — the user has uncommitted work.
  **Do NOT stash and switch branches** — stashed changes from one
  branch should not be popped on a different branch.
  Ask the user to choose:
  1. Commit or stash their changes manually first, then re-run.
  2. Abort.

  **Do NOT silently proceed when the tree is dirty and a branch
  switch is needed.**

#### 3d. Fetch the latest patchset

```bash
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  fetch-command <change_id>
```

This prints a `git fetch ... && git checkout FETCH_HEAD` command.
Run the printed command to get the latest patchset locally.

#### 3e. Create or reuse a working branch

Check if a fix branch already exists:

```bash
git branch --list "fix/gerrit-<change_id>-*"
```

- **If no existing branch** — create one:
  ```bash
  git checkout -b fix/gerrit-<change_id>-comments FETCH_HEAD
  ```

- **If a branch already exists** — it may contain unpushed work
  from a previous skill run. **Do NOT auto-reset it.** Instead,
  warn the user:
  > Branch `fix/gerrit-<change_id>-comments` already exists and
  > may contain uncommitted work from a previous run. Options:
  > 1. Switch to it and keep existing commits (`git checkout <branch>`)
  > 2. Delete it and start fresh (`git branch -D <branch>`)
  > 3. Create a patchset-specific branch instead
  >    (`fix/gerrit-<change_id>-ps<N>-comments`)

  Let the user decide — never silently discard their commits.

**Re-run detection:** If the user is already on a
`fix/gerrit-<change_id>-*` branch with uncommitted changes from a
previous skill run, warn them:
> It looks like this skill was run before and left uncommitted edits.
> Continuing may cause duplicate or conflicting fixes. Consider
> committing or discarding the previous edits first.

### Step 4: Analyse and Resolve Each Comment

For every unresolved comment:

1. **Check for patchset drift.** Compare the comment's `patch_set`
   field against the current patchset number from Step 2.

   - **Same patchset** — comment applies directly; proceed normally.
   - **Older patchset** — the code may have changed since the comment
     was posted. Before acting:
     1. Read the file at the indicated line in the *current* patchset.
     2. Determine if the comment is **still relevant** (the code it
        refers to may have been rewritten, moved, or already fixed).
     3. If already addressed, classify as **Outdated** below.
     4. If the line has shifted, note the drift in the summary table
        (e.g. "Comment on PS3 line 42 → now line 48 in PS5").

2. **Handle special file paths before reading:**

   - **`/COMMIT_MSG`**: This is a Gerrit virtual file representing
     the commit message. Do not try to read it as a local file.
     Instead, read the commit message via `git log -1 --pretty=%B`
     and apply the comment to it.
   - **Deleted files**: If the file does not exist locally (it was
     removed in a later patchset), classify the comment as **Stale**
     and note "File deleted in current patchset" in the summary.
   - **File-level comments** (no `line` field): Read the entire file
     (or its first ~50 lines for context) rather than targeting a
     specific line.

3. **Read the file and surrounding context** at the line mentioned
   in the comment. Use the Read tool on the local file at the
   indicated line.

4. **For threaded comments** (`in_reply_to` is set): Read the parent
   comment(s) in the thread to understand the full conversation
   context before classifying. A reply may only make sense in light
   of the preceding discussion.

5. **Classify the comment:**

   | Category | Action |
   |----------|--------|
   | **Valid bug/issue** | Fix the code. |
   | **Valid style/convention** | Fix if it aligns with project rules. |
   | **Valid suggestion (improvement)** | Apply the improvement. |
   | **Incorrect / Disagree** | Draft a counter-response. |
   | **Question / Clarification** | Draft an answer. |
   | **Outdated (already fixed)** | Note it is already addressed. |
   | **Stale (patchset drift)** | Code changed since comment; note in summary. |

6. **If fixing:** Edit the file, following the project coding standards
   (2-space indent, 79-char limit, docstrings, etc.).

7. **If countering or answering:** Draft a polite, technical reply.
   - **Always prefix with `AI:`** so reviewers know the response was
     generated by Cursor, not written by the author directly.
   - Acknowledge the reviewer's point
   - Explain why the current approach is preferred, with evidence
   - Offer a compromise if applicable

   Example format:
   ```
   AI: Thanks for the suggestion. The current approach uses X because
   [reason]. However, we could also consider [compromise] if preferred.
   ```

### Step 4b: Post Replies to Gerrit

After processing all comments in Step 4, post AI-prefixed replies
back to Gerrit for every resolved thread. This uses the `reply`
command added to the helper script.

For each comment that was **Fixed**, **Countered**, **Answered**,
**Outdated**, or **Stale**, build a reply payload and post it.

**Build the payload:** Collect all replies into a single
`ReviewInput` JSON object grouped by file path:

```json
{
  "comments": {
    "path/to/file.py": [
      {
        "line": 33,
        "message": "AI: Done. Bumped DEFAULT_MAX_DUMPS to 48.",
        "in_reply_to": "<last_comment_id_in_thread>",
        "unresolved": false
      }
    ],
    "path/to/other.py": [
      {
        "line": 17,
        "message": "AI: The current approach is correct because ...",
        "in_reply_to": "<last_comment_id_in_thread>",
        "unresolved": false
      }
    ]
  }
}
```

Key rules for the payload:
- **`in_reply_to`** must be the `id` of the **last** comment in the
  unresolved thread (the one that triggered the action).
- **`unresolved: false`** marks the thread as resolved.
- **`message`** must start with `AI:` so reviewers know the response
  was generated by Cursor.
- **`line`** should match the line from the original comment.

**Post the review:**

```bash
python ~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py \
  reply <change_id> '<json_payload>'
```

The JSON payload must be passed as a single shell argument. Use
single quotes around it and ensure internal strings use double
quotes (standard JSON).

**Message templates by category:**

| Category | Message template |
|----------|-----------------|
| **Fixed** | `AI: Done. <brief description of fix>.` |
| **Valid suggestion applied** | `AI: Good call. Applied — <what changed>.` |
| **Counter / Disagree** | `AI: <acknowledgement>. <reasoning>. <optional compromise>.` |
| **Question answered** | `AI: <answer to the question>.` |
| **Outdated** | `AI: Already addressed in PS<N>.` |
| **Stale** | `AI: Code has changed since this comment; no longer applicable.` |

**Error handling:** If the POST fails (e.g. 403 Forbidden), warn the
user that the reply could not be posted and include the drafted
message in the Step 5 summary so they can post it manually.

### Step 5: Summarise Actions Taken

After processing all comments, present a summary table:

```
| # | File | Line | PS | Current PS | Reviewer | Action | Details |
|---|------|------|----|------------|----------|--------|---------|
| 1 | path/to/file.py | 42 | 3 | 5 | reviewer | Fixed | Changed X to Y |
| 2 | path/to/other.py | 17 | 5 | 5 | reviewer | AI: Counter | Approach is correct because... |
| 3 | path/to/foo.py | 10 | 2 | 5 | reviewer | Stale | Already fixed in PS4 |
```

- **PS** = patchset the comment was posted on
- **Current PS** = latest patchset number
- When PS < Current PS, the comment may reference shifted/changed code

Then:
- List all files modified
- Show a `git diff --stat` of the changes

#### 5a. Update commit message if needed

If any code was changed (i.e. at least one comment was **Fixed**):

1. Read the current commit message:
   ```bash
   git log -1 --pretty=%B
   ```
2. Analyse whether the existing subject and body still accurately
   describe the change after the fixes. Common reasons to update:
   - A fix renamed a function/class mentioned in the subject
   - A fix changed the approach described in the body
   - The body lists items that were added/removed by a fix
3. If an update is needed, draft the new message. **Preserve the
   existing `Change-Id`** (see Important Rules). Show the user a
   clear before/after comparison:
   ```
   Current subject: <old subject>
   Proposed subject: <new subject>

   Changes to body:
   - <what was updated and why>
   ```
4. If no update is needed, explicitly state:
   > Commit message reviewed — no update needed.

**Do NOT silently rewrite the commit message.** Always inform the
user of any proposed changes and get confirmation before amending.

#### 5b. Commit and push the new patchset

If any code was changed (at least one comment was **Fixed**):

1. **Stage and amend** the commit with the (possibly updated)
   message from Step 5a:

   ```bash
   git add -A
   git commit --amend -m "<full_message_with_change_id>"
   ```

   **Critical:** The amended message MUST include the original
   `Change-Id` line — see Important Rules.

2. **Push to Gerrit** for review:

   ```bash
   git push origin HEAD:refs/for/<target_branch>
   ```

   Where `<target_branch>` is the `branch` field from the change
   detail fetched in Step 1b (usually `master`).

3. **Verify the push succeeded.** If Gerrit returns
   `remote rejected` or `no new changes`:
   - Check that the tree differs from the previous patchset.
   - Verify the Change-Id matches.
   - Report the error to the user with the Gerrit message.

4. On success, report the new patchset number (visible in the
   Gerrit push output, e.g. `remote: New Changes: ...`).

#### 5c. Return to original branch

- If the skill switched branches in Step 3, offer to return to
  the original branch recorded in Step 3a:
  ```
  Switch back to your original branch (<original_branch>)? [y/n]
  ```
  If yes: `git checkout <original_branch>`

## Helper Script Reference

All commands use `~/.cursor/skills/gerrit-comment-resolver/scripts/gerrit_api.py`:

| Command | Description |
|---------|-------------|
| `detail <change_id>` | Full change detail (subject, status, patchset, reviewers) |
| `comments <change_id>` | All published comments grouped by file |
| `unresolved <change_id>` | Only unresolved comments grouped by file |
| `files <change_id>` | List of files changed in current revision |
| `diff <change_id> <file_path>` | Diff content for a specific file |
| `fetch-command <change_id>` | Print git fetch + checkout command for latest patchset |
| `search <query>` | Search Gerrit for changes matching a query |
| `reply <change_id> <json>` | Post a review with comments (ReviewInput JSON payload) |

## Important Rules

- **Gerrit write operations are limited to**: posting review comments
  via `reply` (Step 4b) and pushing new patchsets via `git push`
  (Step 5b). Never delete changes, abandon changes, or submit/merge
  through this skill.
- **Never log or display the HTTP password** from the credentials file.
- **Always check patchset freshness** before making code changes.
- **Follow all project coding standards** when editing files (see
  workspace rules for Python style, 2-space indent, 79-char limit,
  etc.).
- **Always amend onto the fetched Gerrit commit** rather than creating
  separate fix commits, so the push produces a clean new patchset.
- **Preserve the Change-Id when amending commits.** Gerrit identifies
  changes by a `Change-Id: I...` line in the commit message. When
  amending a commit (e.g. to upload a new patchset):
  1. **Read the existing message first**: `git log -1 --pretty=%B`
  2. **Extract the Change-Id** from it.
  3. **Always include the original Change-Id** at the bottom of the
     amended message. If you write the full message via `git commit
     --amend -m "..."`, you MUST embed the Change-Id in that text.
  4. **Verify before pushing**: run `git log -1 --pretty=%B | grep
     Change-Id` and confirm it matches the original change.
  If the Change-Id is missing or different, Gerrit will create a
  **new code review** instead of updating the existing one. This is
  a common and disruptive mistake — always guard against it.
