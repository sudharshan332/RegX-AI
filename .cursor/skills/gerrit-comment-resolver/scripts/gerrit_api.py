#!/usr/bin/env python3
"""Gerrit REST API client for comment resolution workflows.

Credentials are resolved in order:
  1. ~/.git-credentials — match the Gerrit host derived from
     `git remote -v` (most developers already have this).
  2. ~/.gerrit-credentials — shell-export format fallback.

Supports both read (GET) and write (POST) operations.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GERRIT_JSON_PREFIX = ")]}'\n"
GIT_CREDENTIALS_PATH = os.path.expanduser("~/.git-credentials")
GERRIT_CREDENTIALS_PATH = os.path.expanduser("~/.gerrit-credentials")


def _get_remote_host() -> Optional[str]:
  """Extract the Gerrit hostname from git remote origin URL.

  Returns:
    Hostname string (e.g. "nugerrit.ntnxdpro.com") or None if
    git remote cannot be determined.
  """
  try:
    result = subprocess.run(["git", "remote", "get-url", "origin"],
                            capture_output=True, text=True, timeout=5,)
    if result.returncode == 0:
      parsed = urlparse(result.stdout.strip())
      if parsed.hostname:
        return parsed.hostname
  except (subprocess.TimeoutExpired, FileNotFoundError):
    pass
  return None


def _load_from_git_credentials(
    target_host: Optional[str] = None,
) -> Optional[Dict[str, str]]:
  """Try loading credentials from ~/.git-credentials.

  The file contains lines in the format:
    https://user:password@hostname

  If target_host is provided, only the line matching that host is
  used. Otherwise the first https:// line is used.

  Args:
    target_host: Hostname to match (e.g. "nugerrit.ntnxdpro.com").

  Returns:
    Dict with keys host, user, password — or None if not found.
  """
  if not os.path.isfile(GIT_CREDENTIALS_PATH):
    return None

  with open(GIT_CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
    for line in fh:
      line = line.strip()
      if not line or not line.startswith("https://"):
        continue
      parsed = urlparse(line)
      hostname = parsed.hostname
      if not hostname or not parsed.username or not parsed.password:
        continue
      if target_host and hostname != target_host:
        continue
      return {
        "host": f"https://{hostname}",
        "user": unquote(parsed.username),
        "password": unquote(parsed.password),
      }
  return None


def _load_from_gerrit_credentials() -> Optional[Dict[str, str]]:
  """Try loading credentials from ~/.gerrit-credentials.

  The file contains shell export lines:
    export GERRIT_HOST="https://..."
    export GERRIT_USER="..."
    export GERRIT_HTTP_PASSWORD="..."

  Returns:
    Dict with keys host, user, password — or None if file is
    missing or incomplete.
  """
  if not os.path.isfile(GERRIT_CREDENTIALS_PATH):
    return None

  creds = {}
  export_pattern = re.compile(r'^export\s+(\w+)=["\']?([^"\']*)["\']?\s*$')
  with open(GERRIT_CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
    for line in fh:
      match = export_pattern.match(line.strip())
      if match:
        creds[match.group(1)] = match.group(2)

  required = {"GERRIT_HOST", "GERRIT_USER", "GERRIT_HTTP_PASSWORD",}
  if not required.issubset(creds):
    return None

  return {
    "host": creds["GERRIT_HOST"].rstrip("/"),
    "user": creds["GERRIT_USER"],
    "password": creds["GERRIT_HTTP_PASSWORD"],
  }


def load_credentials() -> Dict[str, str]:
  """Load Gerrit credentials using a fallback chain.

  Resolution order:
    1. ~/.git-credentials (matched to git remote origin host)
    2. ~/.gerrit-credentials (shell-export format)

  Returns:
    Dict with keys: host, user, password.

  Raises:
    RuntimeError: If no credentials source is available.
  """
  remote_host = _get_remote_host()

  git_creds = _load_from_git_credentials(remote_host)
  if git_creds:
    return git_creds

  gerrit_creds = _load_from_gerrit_credentials()
  if gerrit_creds:
    return gerrit_creds

  sources_tried = f"{GIT_CREDENTIALS_PATH}, {GERRIT_CREDENTIALS_PATH}"
  raise RuntimeError(
    f"No Gerrit credentials found. Tried: {sources_tried}. "
    "Set up ~/.git-credentials (https://user:pass@host) or "
    "~/.gerrit-credentials (export GERRIT_HOST/USER/HTTP_PASSWORD).")


def strip_prefix(text: str) -> str:
  """Remove Gerrit JSON security prefix from response.

  Args:
    text: Raw response body.

  Returns:
    JSON string with prefix removed.
  """
  if text.startswith(GERRIT_JSON_PREFIX):
    return text[len(GERRIT_JSON_PREFIX):]
  return text


class GerritClient:
  """Gerrit REST API client with read and write support."""

  def __init__(self) -> None:
    """Initialise with auto-discovered credentials."""
    creds = load_credentials()
    self.base_url = creds["host"]
    self.session = requests.Session()
    self.session.auth = (creds["user"], creds["password"])
    self.session.verify = False
    self.username = creds["user"]

  def _get(self, endpoint: str) -> Any:
    """Perform authenticated GET and parse JSON response.

    Args:
      endpoint: API path relative to /a/ (e.g. "changes/12345/detail").

    Returns:
      Parsed JSON response.

    Raises:
      requests.HTTPError: On non-2xx response.
    """
    url = f"{self.base_url}/a/{endpoint}"
    response = self.session.get(url, timeout=30)
    response.raise_for_status()
    return json.loads(strip_prefix(response.text))

  def _post(self, endpoint: str, payload: Dict[str, Any]) -> Any:
    """Perform authenticated POST with JSON payload.

    Args:
      endpoint: API path relative to /a/.
      payload: Dict to send as JSON body.

    Returns:
      Parsed JSON response, or None for 204 No Content.

    Raises:
      requests.HTTPError: On non-2xx response.
    """
    url = f"{self.base_url}/a/{endpoint}"
    response = self.session.post(url, json=payload, timeout=30)
    response.raise_for_status()
    if response.status_code == 204 or not response.text.strip():
      return None
    return json.loads(strip_prefix(response.text))

  def post_review(
      self,
      change_id: str,
      revision: str,
      payload: Dict[str, Any],
  ) -> Any:
    """Post a review (comments and/or labels) on a change revision.

    Uses the Gerrit Set Review endpoint:
      POST /changes/{id}/revisions/{revision}/review

    The payload follows Gerrit's ReviewInput schema. Example:
      {
        "comments": {
          "path/to/file.py": [
            {
              "line": 33,
              "message": "AI: Done. Bumped to 48.",
              "in_reply_to": "<parent_comment_id>",
              "unresolved": false
            }
          ]
        }
      }

    Args:
      change_id: Gerrit change number.
      revision: Revision identifier ("current" or patchset number).
      payload: ReviewInput dict per Gerrit API spec.

    Returns:
      Parsed ReviewResult from Gerrit, or None.
    """
    endpoint = (f"changes/{change_id}/revisions/{revision}/review")
    return self._post(endpoint, payload)

  def get_detail(
      self,
      change_id: str,
      include_revisions: bool = False,
  ) -> Dict[str, Any]:
    """Fetch full change detail.

    Args:
      change_id: Gerrit change number (e.g. "410821").
      include_revisions: If True, include current revision info
        (needed for patchset number and fetch refs).

    Returns:
      Change detail dict with subject, status, current_revision, etc.
    """
    endpoint = f"changes/{change_id}/detail"
    if include_revisions:
      endpoint += "?o=CURRENT_REVISION"
    return self._get(endpoint)

  def get_comments(
      self, change_id: str,
  ) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch all published comments on a change.

    Args:
      change_id: Gerrit change number.

    Returns:
      Dict mapping file path to list of comment objects.
    """
    return self._get(f"changes/{change_id}/comments")

  def get_unresolved_comments(
      self, change_id: str,
  ) -> Dict[str, List[Dict[str, Any]]]:
    """Fetch only comments belonging to unresolved threads.

    In Gerrit's threading model each comment carries its own
    ``unresolved`` flag, but a thread's overall status is determined
    by the **last** comment in the reply chain.  A reply posted with
    ``unresolved: false`` resolves the whole thread even though
    earlier comments still have ``unresolved: true``.

    This method groups comments into threads, checks the last comment
    in each thread, and returns only those from truly unresolved
    threads.

    Args:
      change_id: Gerrit change number.

    Returns:
      Dict mapping file path to list of comment objects from
      unresolved threads only.
    """
    all_comments = self.get_comments(change_id)
    result: Dict[str, List[Dict[str, Any]]] = {}

    for filepath, comments in all_comments.items():
      comments_by_id = {c["id"]: c for c in comments}

      thread_roots: Dict[str, List[Dict[str, Any]]] = {}
      for comment in comments:
        root_id = self._find_thread_root(
          comment, comments_by_id)
        thread_roots.setdefault(root_id, []).append(comment)

      unresolved_comments = []
      for thread in thread_roots.values():
        thread.sort(key=lambda c: c.get("updated", ""))
        last_comment = thread[-1]
        if last_comment.get("unresolved", False):
          unresolved_comments.extend(thread)

      if unresolved_comments:
        result[filepath] = unresolved_comments

    return result

  @staticmethod
  def _find_thread_root(
      comment: Dict[str, Any],
      comments_by_id: Dict[str, Dict[str, Any]],
  ) -> str:
    """Walk the in_reply_to chain to find the thread root comment id.

    Args:
      comment: Comment dict with optional ``in_reply_to`` field.
      comments_by_id: Lookup dict of all comments keyed by id.

    Returns:
      The id of the root comment in the thread.
    """
    current = comment
    seen = set()
    while (current.get("in_reply_to")
           and current["in_reply_to"] in comments_by_id
           and current["id"] not in seen):
      seen.add(current["id"])
      current = comments_by_id[current["in_reply_to"]]
    return current["id"]

  def get_files(self, change_id: str) -> Dict[str, Any]:
    """List files changed in the current revision.

    Args:
      change_id: Gerrit change number.

    Returns:
      Dict mapping file path to file info (status, lines inserted/deleted).
    """
    return self._get(f"changes/{change_id}/revisions/current/files")

  def get_diff(self, change_id: str, file_path: str) -> Dict[str, Any]:
    """Fetch diff for a specific file in the current revision.

    Args:
      change_id: Gerrit change number.
      file_path: Path of the file within the repository.

    Returns:
      Diff info dict with content, meta_a, meta_b, etc.
    """
    encoded_path = quote(file_path, safe="")
    return self._get(
      f"changes/{change_id}/revisions/current/files/{encoded_path}/diff")

  def get_current_revision_number(self, change_id: str) -> int:
    """Get current (latest) patchset number for a change.

    Args:
      change_id: Gerrit change number.

    Returns:
      Integer patchset number.

    Raises:
      ValueError: If revision info is missing from detail.
    """
    detail = self.get_detail(change_id, include_revisions=True)
    current_rev = detail.get("current_revision")
    revisions = detail.get("revisions", {})
    if current_rev and current_rev in revisions:
      return revisions[current_rev].get("_number", 1)
    raise ValueError(
      f"Cannot determine current revision for change {change_id}")

  def get_fetch_command(self, change_id: str) -> str:
    """Build git fetch + checkout command for latest patchset.

    Args:
      change_id: Gerrit change number.

    Returns:
      Shell command string to fetch and checkout the change.

    Raises:
      ValueError: If revision info or project is missing.
    """
    detail = self.get_detail(change_id, include_revisions=True)
    project = detail.get("project")
    if not project:
      raise ValueError(f"No project found in change {change_id} detail")
    current_rev = detail.get("current_revision")
    revisions = detail.get("revisions", {})
    if not current_rev or current_rev not in revisions:
      raise ValueError(
        f"Cannot determine current revision for change {change_id}")
    revision_number = revisions[current_rev].get("_number", 1)
    change_suffix = str(change_id).zfill(2)[-2:]
    fetch_url = f"{self.base_url}/a/{project}"
    return (f"git fetch {fetch_url} refs/changes/{change_suffix}/{change_id}/"
            f"{revision_number} && git checkout FETCH_HEAD")

  def search_changes(self, query: str) -> List[Dict[str, Any]]:
    """Search Gerrit for changes matching a query string.

    Args:
      query: Gerrit search query (e.g. "commit:abc123").

    Returns:
      List of change info dicts matching the query.
    """
    encoded_query = quote(query, safe=":")
    return self._get(f"changes/?q={encoded_query}")


def format_output(data: Any) -> str:
  """Pretty-print data as indented JSON.

  Args:
    data: Any JSON-serializable object.

  Returns:
    Formatted JSON string.
  """
  return json.dumps(data, indent=2, default=str)


def _build_parser() -> argparse.ArgumentParser:
  """Build the CLI argument parser with subcommands.

  Returns:
    Configured ArgumentParser with subparsers for each command.
  """
  parser = argparse.ArgumentParser(prog="gerrit_api.py",
    description="Gerrit REST API client for comment resolution.")
  subparsers = parser.add_subparsers(dest="command", required=True,
                                     help="Available commands")

  for cmd in ("detail", "comments", "unresolved", "files", "fetch-command"):
    sub = subparsers.add_parser(cmd)
    sub.add_argument("change_id", help="Gerrit change number")

  sub_diff = subparsers.add_parser("diff")
  sub_diff.add_argument("change_id", help="Gerrit change number")
  sub_diff.add_argument("file_path", help="Path of file to diff")

  sub_search = subparsers.add_parser("search")
  sub_search.add_argument("query", help='Search query (e.g. "commit:abc123")')

  sub_reply = subparsers.add_parser("reply")
  sub_reply.add_argument("change_id", help="Gerrit change number")
  sub_reply.add_argument("json_payload",
                         help="ReviewInput JSON payload (as a string)")

  return parser


def _run_command(args: argparse.Namespace) -> None:
  """Execute the parsed subcommand.

  Args:
    args: Parsed CLI arguments from argparse.
  """
  try:
    client = GerritClient()
  except RuntimeError as error:
    print(f"Credential error: {error}", file=sys.stderr)
    sys.exit(1)

  command = args.command
  change_id = getattr(args, "change_id", None)

  if command == "detail":
    print(format_output(client.get_detail(change_id)))
  elif command == "comments":
    print(format_output(client.get_comments(change_id)))
  elif command == "unresolved":
    print(format_output(client.get_unresolved_comments(change_id)))
  elif command == "files":
    print(format_output(client.get_files(change_id)))
  elif command == "diff":
    print(format_output(client.get_diff(change_id, args.file_path)))
  elif command == "fetch-command":
    print(client.get_fetch_command(change_id))
  elif command == "search":
    print(format_output(client.search_changes(args.query)))
  elif command == "reply":
    payload = json.loads(args.json_payload)
    result = client.post_review(change_id, "current", payload)
    if result is not None:
      print(format_output(result))
    else:
      print("Review posted successfully.")


def main() -> None:
  """CLI entry point — parse args and dispatch."""
  parser = _build_parser()
  args = parser.parse_args()

  try:
    _run_command(args)
  except json.JSONDecodeError as error:
    print(f"Invalid JSON payload: {error}", file=sys.stderr)
    sys.exit(1)
  except requests.ConnectionError:
    print("Network error: cannot reach Gerrit. "
          "Check your network connection.", file=sys.stderr)
    sys.exit(1)
  except requests.HTTPError as error:
    status = (error.response.status_code
              if error.response is not None else "?")
    hint = ""
    if status == 401:
      hint = (" Check your credentials in "
              f"{GIT_CREDENTIALS_PATH} or {GERRIT_CREDENTIALS_PATH}.")
    print(f"Gerrit API error (HTTP {status}): {error}{hint}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()
