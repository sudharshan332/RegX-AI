#!/usr/bin/env python3
# Owner: sam.gaver@nutanix.com
# Copyright: Nutanix 2026
"""JIRA helper for triage-cdp-test-failure skill.

Provides compact, agent-optimized JIRA operations that reduce token
usage by filtering verbose JIRA JSON responses and batching
multi-step workflows into single invocations.

Auth: Reads JIRA_URL and JIRA_PERSONAL_TOKEN from environment
variables, or falls back to parsing ~/.cursor/mcp.json Docker args.

Usage:
  python3 jira_helper.py search --jql 'project=ENG AND ...' [--jql ...]
  python3 jira_helper.py get --issue ENG-12345
  python3 jira_helper.py get-dev-info --issue ENG-12345
  python3 jira_helper.py create --project ENG --summary '...' ...
  python3 jira_helper.py comment --issue ENG-12345 --body-file /tmp/report.txt
  python3 jira_helper.py update --issue ENG-12345 --fields '{...}'
  python3 jira_helper.py add-labels --issue ENG-12345 --labels backup_to_shrek
  python3 jira_helper.py link --type Duplicate --inward ENG-111 --outward ENG-222
  python3 jira_helper.py merge-duplicate --dup ENG-111 --orig ENG-222 ...
  python3 jira_helper.py update-existing --issue ENG-12345 ...
  python3 jira_helper.py field-options --field-id customfield_15160 ...
  python3 jira_helper.py verify
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


ISSUE_FIELDS_SEARCH = [
  "summary", "status", "issuetype", "priority", "resolution",
  "components", "labels", "assignee", "reporter", "created",
  "updated", "environment", "customfield_15160",
  "customfield_18060", "customfield_14262",
]

ISSUE_FIELDS_DETAIL = ISSUE_FIELDS_SEARCH + [
  "description", "comment",
]

CUSTOM_FIELD_NAMES = {
  "customfield_15160": "primary_component",
  "customfield_18060": "test_case_name",
  "customfield_14262": "feat_numbers",
  "customfield_13260": "regression",
}


def _load_auth() -> tuple:
  """Loads JIRA URL and PAT from env vars or ~/.cursor/mcp.json.

  Returns:
    tuple: Tuple of (jira_url, personal_token).

  Raises:
    SystemExit: If credentials cannot be found.
  """
  jira_url = os.environ.get("JIRA_URL")
  jira_token = os.environ.get("JIRA_PERSONAL_TOKEN")

  if jira_url and jira_token:
    return jira_url, jira_token

  mcp_path = Path.home() / ".cursor" / "mcp.json"
  if not mcp_path.exists():
    print("ERROR: No JIRA credentials found. Set JIRA_URL and "
          "JIRA_PERSONAL_TOKEN env vars, or configure "
          "~/.cursor/mcp.json.", file=sys.stderr)
    sys.exit(1)

  with open(mcp_path) as fh:
    mcp_config = json.load(fh)

  servers = mcp_config.get("mcpServers", {})
  atlassian = servers.get("atlassian", {})
  docker_args = atlassian.get("args", [])

  url_from_config = None
  token_from_config = None
  for idx, arg in enumerate(docker_args):
    if arg == "JIRA_URL" or (
      isinstance(arg, str) and arg.startswith("JIRA_URL=")):
      if "=" in arg:
        url_from_config = arg.split("=", 1)[1]
      elif idx + 1 < len(docker_args):
        url_from_config = docker_args[idx + 1]
    if arg == "JIRA_PERSONAL_TOKEN" or (
      isinstance(arg, str)
      and arg.startswith("JIRA_PERSONAL_TOKEN=")):
      if "=" in arg:
        token_from_config = arg.split("=", 1)[1]
      elif idx + 1 < len(docker_args):
        token_from_config = docker_args[idx + 1]

  if not url_from_config or not token_from_config:
    print("ERROR: Could not extract JIRA credentials from "
          "~/.cursor/mcp.json. Ensure the 'atlassian' MCP "
          "server is configured with JIRA_URL and "
          "JIRA_PERSONAL_TOKEN.", file=sys.stderr)
    sys.exit(1)

  return url_from_config, token_from_config


class JiraClient:
  """Thin JIRA REST API client with compact output formatting."""

  def __init__(self, base_url: str, token: str):
    """Initializes JIRA client.

    Args:
      base_url (str): JIRA server URL.
      token (str): Personal Access Token for authentication.
    """
    self.base_url = base_url.rstrip("/")
    self._headers = {
      "Authorization": f"Bearer {token}",
      "Content-Type": "application/json",
      "Accept": "application/json",
    }

  # --- Public operations ---

  def verify(self) -> dict:
    """Verifies JIRA connectivity with a lightweight search.

    Returns:
      dict: Status and server info.
    """
    try:
      result = self._get(
        "/rest/api/2/search",
        params={
          "jql": "project = ENG AND created >= -1d "
                 "ORDER BY created DESC",
          "maxResults": 1,
          "fields": "summary",
        },
      )
      return {
        "status": "ok",
        "total_recent_issues": result.get("total", 0),
        "server": self.base_url,
      }
    except SystemExit:
      return {"status": "error", "server": self.base_url}

  def search(self, jql_queries: list,
             limit: int = 10) -> dict:
    """Executes JQL queries and returns deduplicated results.

    Each query is executed independently. Results are merged
    and deduplicated by issue key.

    Args:
      jql_queries (list): List of JQL query strings.
      limit (int): Max results per query.

    Returns:
      dict: Per-query counts, merged issues list, and total.
    """
    all_issues = {}
    query_results = []

    fields_csv = ",".join(ISSUE_FIELDS_SEARCH)

    for jql in jql_queries:
      result = self._get(
        "/rest/api/2/search",
        params={
          "jql": jql,
          "maxResults": limit,
          "fields": fields_csv,
        },
      )
      raw_issues = result.get("issues", [])
      query_keys = []
      for raw_issue in raw_issues:
        key = raw_issue.get("key", "")
        query_keys.append(key)
        if key not in all_issues:
          all_issues[key] = self._compact_issue(raw_issue)

      query_results.append({
        "jql": jql,
        "total_matches": result.get("total", 0),
        "returned": len(raw_issues),
        "keys": query_keys,
      })

    sorted_issues = sorted(
      all_issues.values(),
      key=lambda iss: iss.get("created", ""),
      reverse=True,
    )

    return {
      "queries": query_results,
      "issues": sorted_issues,
      "unique_count": len(sorted_issues),
    }

  def get_issue(self, issue_key: str,
                comment_limit: int = 20) -> dict:
    """Fetches full issue details with compact output.

    Includes description, comments, environment, custom
    fields, and linked issues for duplicate analysis.

    Args:
      issue_key (str): JIRA issue key (e.g., ENG-12345).
      comment_limit (int): Max comments to include.

    Returns:
      dict: Compact issue with description and comments.
    """
    detail_fields = list(ISSUE_FIELDS_DETAIL)
    detail_fields.append("issuelinks")
    detail_fields.append("versions")
    fields_csv = ",".join(detail_fields)

    raw = self._get(
      f"/rest/api/2/issue/{issue_key}",
      params={"fields": fields_csv},
    )
    return self._compact_issue(
      raw,
      include_description=True,
      include_comments=True,
      comment_limit=comment_limit,
    )

  def get_dev_info(self, issue_key: str) -> dict:
    """Fetches development info (Gerrit changes, commits).

    Args:
      issue_key (str): JIRA issue key.

    Returns:
      dict: Compact dev info with changes list.
    """
    issue_data = self._get(
      f"/rest/api/2/issue/{issue_key}",
      params={"fields": "summary"},
    )
    issue_id = issue_data.get("id", "")

    try:
      dev_data = self._get(
        "/rest/dev-status/latest/issue/detail",
        params={
          "issueId": issue_id,
          "applicationType": "stash",
          "dataType": "pullrequest",
        },
      )
    except SystemExit:
      return {
        "issue_key": issue_key,
        "changes": [],
        "note": ("Dev info API unavailable or no "
                 "linked changes"),
      }

    changes = []
    for detail in dev_data.get("detail", []):
      for pr_data in detail.get("pullRequests", []):
        changes.append({
          "id": pr_data.get("id", ""),
          "name": pr_data.get("name", ""),
          "status": pr_data.get("status", ""),
          "url": pr_data.get("url", ""),
          "last_update": self._format_date(
            pr_data.get("lastUpdate")
          ),
        })

    return {"issue_key": issue_key, "changes": changes}

  def create_issue(
    self, project_key: str, summary: str,
    issue_type: str,
    description: Optional[str] = None,
    components: Optional[list] = None,
    additional_fields: Optional[dict] = None,
  ) -> dict:
    """Creates a new JIRA issue.

    Description is posted as-is (JIRA wiki markup).

    Args:
      project_key (str): JIRA project key (e.g., ENG).
      summary (str): Issue summary/title.
      issue_type (str): Issue type name (Bug, Test, etc.).
      description (Optional[str]): Description in wiki markup.
      components (Optional[list]): Component name strings.
      additional_fields (Optional[dict]): Extra fields to set.

    Returns:
      dict: Created issue key and URL.
    """
    fields = {
      "project": {"key": project_key},
      "summary": summary,
      "issuetype": {"name": issue_type},
    }

    if description:
      fields["description"] = description

    if components:
      fields["components"] = [
        {"name": comp} for comp in components
      ]

    if additional_fields:
      fields.update(additional_fields)

    result = self._post(
      "/rest/api/2/issue", json={"fields": fields},
    )

    key = result.get("key", "")
    return {
      "key": key,
      "id": result.get("id", ""),
      "url": f"{self.base_url}/browse/{key}",
    }

  def add_comment(self, issue_key: str,
                  body: str) -> dict:
    """Adds a comment to an issue.

    Body is posted as-is (JIRA wiki markup).

    Args:
      issue_key (str): JIRA issue key.
      body (str): Comment body in JIRA wiki markup.

    Returns:
      dict: Comment id and status.
    """
    result = self._post(
      f"/rest/api/2/issue/{issue_key}/comment",
      json={"body": body},
    )
    return {
      "status": "ok",
      "comment_id": result.get("id", ""),
      "issue_key": issue_key,
    }

  def update_issue(self, issue_key: str,
                   fields: Optional[dict] = None,
                   additional_fields: Optional[dict] = None
                   ) -> dict:
    """Updates issue fields.

    Args:
      issue_key (str): JIRA issue key.
      fields (Optional[dict]): Standard fields to update.
      additional_fields (Optional[dict]): Custom fields.

    Returns:
      dict: Update status.
    """
    update_fields = {}
    if fields:
      update_fields.update(fields)
    if additional_fields:
      update_fields.update(additional_fields)

    self._put(
      f"/rest/api/2/issue/{issue_key}",
      json={"fields": update_fields},
    )

    return {"status": "ok", "issue_key": issue_key}

  def add_labels(self, issue_key: str,
                 labels_to_add: list,
                 labels_to_remove: Optional[list] = None
                 ) -> dict:
    """Adds labels to an issue, preserving existing labels.

    Fetches current labels, applies additions and removals,
    then updates.

    Args:
      issue_key (str): JIRA issue key.
      labels_to_add (list): Labels to add.
      labels_to_remove (Optional[list]): Labels to remove.

    Returns:
      dict: Previous and new label lists.
    """
    raw = self._get(
      f"/rest/api/2/issue/{issue_key}",
      params={"fields": "labels"},
    )
    existing = raw.get("fields", {}).get("labels", [])

    new_labels = set(existing)
    if labels_to_remove:
      new_labels -= set(labels_to_remove)
    new_labels |= set(labels_to_add)
    new_labels_sorted = sorted(new_labels)

    self._put(
      f"/rest/api/2/issue/{issue_key}",
      json={"fields": {"labels": new_labels_sorted}},
    )

    return {
      "status": "ok",
      "issue_key": issue_key,
      "previous_labels": existing,
      "new_labels": new_labels_sorted,
    }

  def create_issue_link(self, link_type: str,
                        inward_key: str,
                        outward_key: str) -> dict:
    """Creates a link between two issues.

    Args:
      link_type (str): Link type name (Duplicate, etc.).
      inward_key (str): Inward issue key.
      outward_key (str): Outward issue key.

    Returns:
      dict: Link status.
    """
    self._post(
      "/rest/api/2/issueLink",
      json={
        "type": {"name": link_type},
        "inwardIssue": {"key": inward_key},
        "outwardIssue": {"key": outward_key},
      },
    )
    return {
      "status": "ok",
      "link_type": link_type,
      "inward": inward_key,
      "outward": outward_key,
    }

  def get_field_options(self, field_id: str,
                        project_key: str = "ENG",
                        issue_type: str = "Bug",
                        contains: Optional[str] = None
                        ) -> dict:
    """Gets allowed values for a custom field.

    Args:
      field_id (str): Custom field ID.
      project_key (str): Project key for context.
      issue_type (str): Issue type name for context.
      contains (Optional[str]): Substring filter on values.

    Returns:
      dict: Matching options.
    """
    result = self._get(
      "/rest/api/2/issue/createmeta",
      params={
        "projectKeys": project_key,
        "issuetypeNames": issue_type,
        "expand": "projects.issuetypes.fields",
      },
    )

    options = []
    for project in result.get("projects", []):
      for itype in project.get("issuetypes", []):
        field_info = (
          itype.get("fields", {}).get(field_id, {})
        )
        for opt in field_info.get("allowedValues", []):
          value = opt.get("value", "")
          children = [
            child.get("value", "")
            for child in opt.get("children", [])
          ]
          if contains:
            match = contains.lower()
            value_match = match in value.lower()
            child_match = any(
              match in cv.lower() for cv in children
            )
            if not value_match and not child_match:
              continue
          entry = {"value": value}
          if children:
            if contains:
              filtered = [
                cv for cv in children
                if contains.lower() in cv.lower()
              ]
              entry["children"] = filtered or children
            else:
              entry["children"] = children
          options.append(entry)

    return {"field_id": field_id, "options": options}

  def merge_duplicate(
    self, dup_key: str, orig_key: str,
    report_body: Optional[str] = None,
    dup_comment: Optional[str] = None,
    add_labels: Optional[list] = None,
    remove_labels: Optional[list] = None,
  ) -> dict:
    """Executes the full duplicate merge workflow.

    Steps: link as duplicate, comment on dup, post triage
    report on orig, merge labels/environment/FEAT numbers.

    Args:
      dup_key (str): Duplicate issue key.
      orig_key (str): Original issue key.
      report_body (Optional[str]): Triage report wiki markup.
      dup_comment (Optional[str]): Comment for dup ticket.
      add_labels (Optional[list]): Labels to add to orig.
      remove_labels (Optional[list]): Labels to remove.

    Returns:
      dict: Actions taken with before/after state.
    """
    merge_fields = (
      "labels,environment,customfield_18060,"
      "customfield_14262,reporter"
    )
    dup_raw = self._get(
      f"/rest/api/2/issue/{dup_key}",
      params={"fields": merge_fields},
    )
    orig_raw = self._get(
      f"/rest/api/2/issue/{orig_key}",
      params={"fields": merge_fields},
    )

    dup_fields = dup_raw.get("fields", {})
    orig_fields = orig_raw.get("fields", {})
    actions = []

    self._post(
      "/rest/api/2/issueLink",
      json={
        "type": {"name": "Duplicate"},
        "inwardIssue": {"key": orig_key},
        "outwardIssue": {"key": dup_key},
      },
    )
    actions.append(
      f"Linked {dup_key} as duplicate of {orig_key}"
    )

    if not dup_comment:
      dup_reporter = self._extract_user(
        dup_fields.get("reporter")
      )
      mention = (
        f"[~{dup_reporter}] " if dup_reporter else ""
      )
      dup_comment = (
        f"{mention}This ticket has been identified as a "
        f"duplicate of {orig_key}. Merging findings into "
        f"the original ticket."
      )
    self._post(
      f"/rest/api/2/issue/{dup_key}/comment",
      json={"body": dup_comment},
    )
    actions.append(f"Commented on {dup_key}")

    if report_body:
      self._post(
        f"/rest/api/2/issue/{orig_key}/comment",
        json={"body": report_body},
      )
      actions.append(
        f"Posted triage report on {orig_key}"
      )

    update_payload = {}

    orig_labels = set(orig_fields.get("labels", []))
    dup_labels = set(dup_fields.get("labels", []))
    merged_labels = orig_labels | dup_labels
    if add_labels:
      merged_labels |= set(add_labels)
    if remove_labels:
      merged_labels -= set(remove_labels)
    merged_labels_sorted = sorted(merged_labels)
    update_payload["labels"] = merged_labels_sorted
    actions.append(
      f"Labels: {sorted(orig_labels)} -> "
      f"{merged_labels_sorted}"
    )

    orig_env = orig_fields.get("environment") or ""
    dup_env = dup_fields.get("environment") or ""
    if dup_env:
      if orig_env:
        merged_env = f"{orig_env}\n{dup_env}"
      else:
        merged_env = dup_env
      update_payload["environment"] = merged_env
      actions.append(
        f"Environment: appended {dup_key} env "
        f"to {orig_key}"
      )

    orig_test_names = (
      orig_fields.get("customfield_18060") or []
    )
    dup_test_names = (
      dup_fields.get("customfield_18060") or []
    )
    if dup_test_names:
      merged_test_names = sorted(
        set(orig_test_names) | set(dup_test_names)
      )
      update_payload["customfield_18060"] = (
        merged_test_names
      )
      actions.append(
        f"Test case names: merged "
        f"{len(dup_test_names)} from {dup_key}"
      )

    orig_feats = (
      orig_fields.get("customfield_14262") or []
    )
    dup_feats = (
      dup_fields.get("customfield_14262") or []
    )
    if dup_feats:
      if isinstance(orig_feats, str):
        orig_feats = [orig_feats]
      if isinstance(dup_feats, str):
        dup_feats = [dup_feats]
      merged_feats = sorted(
        set(orig_feats) | set(dup_feats)
      )
      update_payload["customfield_14262"] = merged_feats
      actions.append(
        f"FEAT numbers: merged {len(dup_feats)} "
        f"from {dup_key}"
      )

    if update_payload:
      self._put(
        f"/rest/api/2/issue/{orig_key}",
        json={"fields": update_payload},
      )
      actions.append(f"Updated fields on {orig_key}")

    return {
      "status": "ok",
      "dup_key": dup_key,
      "orig_key": orig_key,
      "actions": actions,
      "note": (
        f"{dup_key} must be manually resolved as "
        f"Duplicate in the JIRA UI (API limitation)."
      ),
    }

  def update_existing(
    self, issue_key: str,
    report_body: Optional[str] = None,
    append_environment: Optional[str] = None,
    add_labels: Optional[list] = None,
    remove_labels: Optional[list] = None,
    add_test_case_names: Optional[list] = None,
  ) -> dict:
    """Updates an existing ticket with new triage evidence.

    Atomic workflow: fetches current state, applies changes,
    returns before/after so the agent can report to the user.

    Args:
      issue_key (str): JIRA issue key.
      report_body (Optional[str]): Triage report comment.
      append_environment (Optional[str]): Text to append.
      add_labels (Optional[list]): Labels to add.
      remove_labels (Optional[list]): Labels to remove.
      add_test_case_names (Optional[list]): Test case names
        to merge into customfield_18060 (preserves existing).

    Returns:
      dict: Before/after state and actions taken.
    """
    fetch_fields = "labels,environment,customfield_18060"
    raw = self._get(
      f"/rest/api/2/issue/{issue_key}",
      params={"fields": fetch_fields},
    )
    fields = raw.get("fields", {})
    actions = []

    if report_body:
      self._post(
        f"/rest/api/2/issue/{issue_key}/comment",
        json={"body": report_body},
      )
      actions.append("Posted triage report comment")

    update_payload = {}

    if append_environment:
      existing_env = fields.get("environment") or ""
      if existing_env:
        new_env = (
          f"{existing_env}\n{append_environment}"
        )
      else:
        new_env = append_environment
      update_payload["environment"] = new_env
      actions.append(
        "Environment: "
        f"{'appended' if existing_env else 'set'}"
      )

    if add_labels or remove_labels:
      existing_labels = set(fields.get("labels", []))
      new_labels = set(existing_labels)
      if remove_labels:
        new_labels -= set(remove_labels)
      if add_labels:
        new_labels |= set(add_labels)
      new_labels_sorted = sorted(new_labels)
      update_payload["labels"] = new_labels_sorted
      actions.append(
        f"Labels: {sorted(existing_labels)} -> "
        f"{new_labels_sorted}"
      )

    if add_test_case_names:
      existing_names = (
        fields.get("customfield_18060") or []
      )
      merged = sorted(
        set(existing_names) | set(add_test_case_names)
      )
      if merged != sorted(existing_names):
        update_payload["customfield_18060"] = merged
        added = sorted(
          set(add_test_case_names) - set(existing_names)
        )
        actions.append(
          f"Test Case Name: added {added}"
        )
      else:
        actions.append(
          "Test Case Name: already present"
        )

    if update_payload:
      self._put(
        f"/rest/api/2/issue/{issue_key}",
        json={"fields": update_payload},
      )

    return {
      "status": "ok",
      "issue_key": issue_key,
      "actions": actions,
      "previous_environment": fields.get("environment"),
      "previous_labels": fields.get("labels", []),
    }

  # --- Private methods ---

  def _api(self, method: str, path: str,
           **kwargs) -> dict:
    """Makes an API request and returns parsed JSON.

    Args:
      method (str): HTTP method (GET, POST, PUT).
      path (str): API path relative to base URL.
      **kwargs: Supports ``params`` (dict) and ``json``
        (dict serialized as request body).

    Returns:
      dict: Parsed JSON response.

    Raises:
      SystemExit: On HTTP errors.
    """
    url = urljoin(self.base_url, path)

    params = kwargs.pop("params", None)
    if params:
      url = f"{url}?{urlencode(params, doseq=True)}"

    body_data = kwargs.pop("json", None)
    data = (
      json.dumps(body_data).encode() if body_data else None
    )

    req = Request(url, data=data, headers=self._headers,
                  method=method)
    try:
      with urlopen(req, timeout=30) as resp:
        resp_body = resp.read().decode("utf-8")
        if not resp_body:
          return {}
        return json.loads(resp_body)
    except Exception as error:
      error_msg = str(error)
      read_fn = getattr(error, "read", None)
      if read_fn:
        error_msg = read_fn().decode(
          "utf-8", errors="replace"
        )
      print(
        f"ERROR: JIRA API {method} {path} failed: "
        f"{error_msg[:500]}", file=sys.stderr,
      )
      sys.exit(1)

  def _get(self, path: str, **kwargs) -> dict:
    """Sends an HTTP GET request.

    Args:
      path (str): API path relative to base URL.
      **kwargs: Additional arguments passed to _api.

    Returns:
      dict: Parsed JSON response.
    """
    return self._api("GET", path, **kwargs)

  def _post(self, path: str, **kwargs) -> dict:
    """Sends an HTTP POST request.

    Args:
      path (str): API path relative to base URL.
      **kwargs: Additional arguments passed to _api.

    Returns:
      dict: Parsed JSON response.
    """
    return self._api("POST", path, **kwargs)

  def _put(self, path: str, **kwargs) -> dict:
    """Sends an HTTP PUT request.

    Args:
      path (str): API path relative to base URL.
      **kwargs: Additional arguments passed to _api.

    Returns:
      dict: Parsed JSON response.
    """
    return self._api("PUT", path, **kwargs)

  def _extract_user(
    self, user_data: Optional[dict]
  ) -> Optional[str]:
    """Extracts display name from JIRA user object.

    Args:
      user_data (Optional[dict]): Raw JIRA user dict.

    Returns:
      Optional[str]: Display name or None.
    """
    if not user_data:
      return None
    return (user_data.get("displayName")
            or user_data.get("name"))

  def _extract_components(self,
                          components: list) -> list:
    """Extracts component names from JIRA components.

    Args:
      components (list): Raw JIRA components list.

    Returns:
      list: Component name strings.
    """
    if not components:
      return []
    return [
      comp.get("name", "") for comp in components
    ]

  def _extract_cascading_select(
    self, field_data: Optional[dict]
  ) -> Optional[str]:
    """Extracts cascading select as 'Parent > Child'.

    Args:
      field_data (Optional[dict]): Raw cascading select.

    Returns:
      Optional[str]: Formatted string or None.
    """
    if not field_data:
      return None
    parent = field_data.get("value", "")
    child_data = field_data.get("child")
    if child_data:
      child_val = child_data.get("value", "")
      return f"{parent} > {child_val}"
    return parent

  def _extract_versions(
    self, versions: Optional[list]
  ) -> list:
    """Extracts version names from JIRA versions.

    Args:
      versions (Optional[list]): Raw JIRA versions list.

    Returns:
      list: Version name strings.
    """
    if not versions:
      return []
    return [ver.get("name", "") for ver in versions]

  def _format_date(
    self, date_str: Optional[str]
  ) -> Optional[str]:
    """Formats JIRA date string to compact YYYY-MM-DD.

    Args:
      date_str (Optional[str]): Raw JIRA datetime string.

    Returns:
      Optional[str]: Compact date string or None.
    """
    if not date_str:
      return None
    try:
      parsed = datetime.fromisoformat(
        date_str.replace("+0000", "+00:00")
      )
      return parsed.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
      if len(date_str) >= 10:
        return date_str[:10]
      return date_str

  def _format_comments(
    self, comment_data: Optional[dict],
    limit: int = 20
  ) -> list:
    """Extracts and formats comments into compact dicts.

    Args:
      comment_data (Optional[dict]): Raw JIRA comment data.
      limit (int): Maximum number of comments to return.

    Returns:
      list: Compact comment dicts with author, date, body.
    """
    if not comment_data:
      return []
    raw_comments = comment_data.get("comments", [])
    formatted = []
    for comment in raw_comments[-limit:]:
      formatted.append({
        "author": self._extract_user(
          comment.get("author")
        ),
        "date": self._format_date(
          comment.get("created")
        ),
        "body": comment.get("body", ""),
      })
    return formatted

  def _compact_issue(
    self, raw: dict,
    include_description: bool = False,
    include_comments: bool = False,
    comment_limit: int = 20
  ) -> dict:
    """Converts raw JIRA issue JSON to compact form.

    Strips avatar URLs, schema links, self-links, expand
    metadata while preserving fields for triage analysis.

    Args:
      raw (dict): Raw JIRA issue JSON dict.
      include_description (bool): Include description.
      include_comments (bool): Include comments.
      comment_limit (int): Max comments when included.

    Returns:
      dict: Compact issue dict.
    """
    fields = raw.get("fields", {})
    status_obj = fields.get("status", {})
    resolution_obj = fields.get("resolution")
    issuetype_obj = fields.get("issuetype", {})
    priority_obj = fields.get("priority", {})

    compact = {
      "key": raw.get("key", ""),
      "summary": fields.get("summary", ""),
      "status": (
        status_obj.get("name", "")
        if status_obj else ""
      ),
      "issue_type": (
        issuetype_obj.get("name", "")
        if issuetype_obj else ""
      ),
      "priority": (
        priority_obj.get("name", "")
        if priority_obj else ""
      ),
      "resolution": (
        resolution_obj.get("name")
        if resolution_obj else None
      ),
      "assignee": self._extract_user(
        fields.get("assignee")
      ),
      "reporter": self._extract_user(
        fields.get("reporter")
      ),
      "components": self._extract_components(
        fields.get("components", [])
      ),
      "labels": fields.get("labels", []),
      "created": self._format_date(
        fields.get("created")
      ),
      "updated": self._format_date(
        fields.get("updated")
      ),
      "environment": fields.get("environment"),
      "primary_component": (
        self._extract_cascading_select(
          fields.get("customfield_15160")
        )
      ),
      "test_case_name": fields.get("customfield_18060"),
      "feat_numbers": fields.get("customfield_14262"),
      "versions": self._extract_versions(
        fields.get("versions", [])
      ),
    }

    if include_description:
      compact["description"] = fields.get(
        "description", ""
      )

    if include_comments:
      compact["comments"] = self._format_comments(
        fields.get("comment"), limit=comment_limit
      )

    linked_issues = fields.get("issuelinks", [])
    if linked_issues:
      compact["linked_issues"] = (
        self._format_issue_links(linked_issues)
      )

    return compact

  def _format_issue_links(self, links: list) -> list:
    """Extracts compact linked issue info.

    Args:
      links (list): Raw JIRA issuelinks array.

    Returns:
      list: Compact link dicts.
    """
    formatted = []
    for link in links:
      link_type = link.get("type", {})
      if "inwardIssue" in link:
        related = link["inwardIssue"]
        direction = link_type.get(
          "inward", "relates to"
        )
      elif "outwardIssue" in link:
        related = link["outwardIssue"]
        direction = link_type.get(
          "outward", "relates to"
        )
      else:
        continue
      related_fields = related.get("fields", {})
      related_status = related_fields.get("status", {})
      formatted.append({
        "direction": direction,
        "key": related.get("key", ""),
        "summary": related_fields.get("summary", ""),
        "status": (
          related_status.get("name", "")
          if related_status else ""
        ),
      })
    return formatted


def _build_parser() -> argparse.ArgumentParser:
  """Builds the CLI argument parser.

  Returns:
    argparse.ArgumentParser: Configured parser.
  """
  parser = argparse.ArgumentParser(
    description=(
      "JIRA helper for triage-cdp-test-failure skill"
    )
  )
  sub = parser.add_subparsers(
    dest="command", required=True
  )

  sub.add_parser("verify", help="Verify JIRA connectivity")

  search_p = sub.add_parser(
    "search", help="Search JIRA issues"
  )
  search_p.add_argument(
    "--jql", action="append", required=True,
    help="JQL query (repeatable)",
  )
  search_p.add_argument(
    "--limit", type=int, default=10,
    help="Max results per query",
  )

  get_p = sub.add_parser("get", help="Get issue details")
  get_p.add_argument(
    "--issue", required=True, help="Issue key"
  )
  get_p.add_argument(
    "--comment-limit", type=int, default=20,
    help="Max comments to include",
  )

  dev_p = sub.add_parser(
    "get-dev-info", help="Get development info"
  )
  dev_p.add_argument(
    "--issue", required=True, help="Issue key"
  )

  create_p = sub.add_parser(
    "create", help="Create new issue"
  )
  create_p.add_argument(
    "--project", required=True, help="Project key"
  )
  create_p.add_argument(
    "--summary", required=True, help="Issue summary"
  )
  create_p.add_argument(
    "--type", required=True,
    help="Issue type (Bug, Test, etc.)"
  )
  create_p.add_argument(
    "--description-file",
    help="Path to description file (wiki markup)",
  )
  create_p.add_argument(
    "--description",
    help="Inline description (wiki markup)",
  )
  create_p.add_argument(
    "--components",
    help="Comma-separated component names",
  )
  create_p.add_argument(
    "--fields",
    help="JSON string of additional fields",
  )

  comment_p = sub.add_parser(
    "comment", help="Add comment to issue"
  )
  comment_p.add_argument(
    "--issue", required=True, help="Issue key"
  )
  comment_p.add_argument(
    "--body-file",
    help="Path to file containing comment body",
  )
  comment_p.add_argument(
    "--body", help="Inline comment body (wiki markup)",
  )

  update_p = sub.add_parser(
    "update", help="Update issue fields"
  )
  update_p.add_argument(
    "--issue", required=True, help="Issue key"
  )
  update_p.add_argument(
    "--fields", required=True,
    help="JSON string of fields to update",
  )

  labels_p = sub.add_parser(
    "add-labels", help="Add labels (preserves existing)"
  )
  labels_p.add_argument(
    "--issue", required=True, help="Issue key"
  )
  labels_p.add_argument(
    "--labels", required=True, nargs="+",
    help="Labels to add",
  )
  labels_p.add_argument(
    "--remove", nargs="+", help="Labels to remove",
  )

  link_p = sub.add_parser(
    "link", help="Create issue link"
  )
  link_p.add_argument(
    "--type", required=True,
    help="Link type (Duplicate, etc.)"
  )
  link_p.add_argument(
    "--inward", required=True, help="Inward issue key"
  )
  link_p.add_argument(
    "--outward", required=True, help="Outward issue key"
  )

  merge_p = sub.add_parser(
    "merge-duplicate",
    help="Full duplicate merge workflow",
  )
  merge_p.add_argument(
    "--dup", required=True,
    help="Duplicate issue key",
  )
  merge_p.add_argument(
    "--orig", required=True,
    help="Original issue key",
  )
  merge_p.add_argument(
    "--report-file",
    help="Path to triage report (wiki markup)",
  )
  merge_p.add_argument(
    "--dup-comment",
    help="Custom comment for dup ticket",
  )
  merge_p.add_argument(
    "--add-labels", nargs="+",
    help="Labels to add to orig",
  )
  merge_p.add_argument(
    "--remove-labels", nargs="+",
    help="Labels to remove from orig",
  )

  upd_exist_p = sub.add_parser(
    "update-existing",
    help="Update existing ticket with new evidence",
  )
  upd_exist_p.add_argument(
    "--issue", required=True, help="Issue key"
  )
  upd_exist_p.add_argument(
    "--report-file",
    help="Path to triage report (wiki markup)",
  )
  upd_exist_p.add_argument(
    "--append-environment",
    help="Text to append to environment field",
  )
  upd_exist_p.add_argument(
    "--add-labels", nargs="+", help="Labels to add",
  )
  upd_exist_p.add_argument(
    "--remove-labels", nargs="+",
    help="Labels to remove",
  )
  upd_exist_p.add_argument(
    "--add-test-case-name", nargs="+",
    help="Test case names to merge into ticket",
  )

  opts_p = sub.add_parser(
    "field-options",
    help="Get allowed field option values",
  )
  opts_p.add_argument(
    "--field-id", required=True,
    help="Custom field ID",
  )
  opts_p.add_argument(
    "--project", default="ENG", help="Project key"
  )
  opts_p.add_argument(
    "--issue-type", default="Bug", help="Issue type"
  )
  opts_p.add_argument(
    "--contains", help="Substring filter on values"
  )

  return parser


def _read_file_arg(
  path: Optional[str]
) -> Optional[str]:
  """Reads file contents if path is provided.

  Args:
    path (Optional[str]): File path or None.

  Returns:
    Optional[str]: File contents or None.
  """
  if not path:
    return None
  with open(path) as fh:
    return fh.read()


def main():
  """CLI entry point."""
  parser = _build_parser()
  args = parser.parse_args()

  jira_url, jira_token = _load_auth()
  client = JiraClient(jira_url, jira_token)

  if args.command == "verify":
    result = client.verify()

  elif args.command == "search":
    result = client.search(
      args.jql, limit=args.limit
    )

  elif args.command == "get":
    result = client.get_issue(
      args.issue, comment_limit=args.comment_limit
    )

  elif args.command == "get-dev-info":
    result = client.get_dev_info(args.issue)

  elif args.command == "create":
    description = (
      _read_file_arg(args.description_file)
      or args.description
    )
    components = (
      [
        comp.strip()
        for comp in args.components.split(",")
      ]
      if args.components else None
    )
    additional = (
      json.loads(args.fields)
      if args.fields else None
    )
    result = client.create_issue(
      project_key=args.project,
      summary=args.summary,
      issue_type=args.type,
      description=description,
      components=components,
      additional_fields=additional,
    )

  elif args.command == "comment":
    body = _read_file_arg(args.body_file) or args.body
    if not body:
      print(
        "ERROR: --body or --body-file required",
        file=sys.stderr,
      )
      sys.exit(1)
    result = client.add_comment(args.issue, body)

  elif args.command == "update":
    fields = json.loads(args.fields)
    result = client.update_issue(
      args.issue, fields=fields
    )

  elif args.command == "add-labels":
    result = client.add_labels(
      args.issue, args.labels,
      labels_to_remove=args.remove,
    )

  elif args.command == "link":
    result = client.create_issue_link(
      args.type, args.inward, args.outward
    )

  elif args.command == "merge-duplicate":
    report_body = _read_file_arg(args.report_file)
    result = client.merge_duplicate(
      dup_key=args.dup,
      orig_key=args.orig,
      report_body=report_body,
      dup_comment=args.dup_comment,
      add_labels=getattr(args, "add_labels", None),
      remove_labels=getattr(
        args, "remove_labels", None
      ),
    )

  elif args.command == "update-existing":
    report_body = _read_file_arg(args.report_file)
    result = client.update_existing(
      issue_key=args.issue,
      report_body=report_body,
      append_environment=args.append_environment,
      add_labels=getattr(args, "add_labels", None),
      remove_labels=getattr(
        args, "remove_labels", None
      ),
      add_test_case_names=getattr(
        args, "add_test_case_name", None
      ),
    )

  elif args.command == "field-options":
    result = client.get_field_options(
      field_id=args.field_id,
      project_key=args.project,
      issue_type=args.issue_type,
      contains=args.contains,
    )

  else:
    parser.print_help()
    sys.exit(1)

  print(json.dumps(result, indent=2))


if __name__ == "__main__":
  main()
