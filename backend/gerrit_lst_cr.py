"""Create LST handover/deprecation CRs via Gerrit REST Change Edit (no git clone).

Flux is fast because it reuses a warm workspace. This path matches that speed
by reading one file, creating a change, and publishing an edit over HTTP.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import random
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

logger = logging.getLogger(__name__)

Transport = Callable[..., Any]


class GerritRestError(Exception):
    def __init__(self, message: str, status_code: int = 502, payload: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code)
        self.payload = payload or {}


def git_fallback_enabled() -> bool:
    """Git clone path is opt-in so a REST failure does not hang on a full clone."""
    return (os.getenv("HANDOVER_CR_GIT_FALLBACK") or "").strip() in ("1", "true", "yes")


def force_git_clone() -> bool:
    return (os.getenv("HANDOVER_CR_USE_GIT") or "").strip() in ("1", "true", "yes")


def generate_change_id() -> str:
    raw = "%s-%s-%s" % (time.time(), os.getpid(), random.random())
    return "I" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def extract_change_id_footer(created: Dict[str, Any]) -> str:
    """Pull the I… Change-Id Gerrit assigned when the change was created."""
    import re
    cid = (created.get("change_id") or "").strip()
    if re.match(r"^I[0-9a-fA-F]{40}$", cid):
        return cid
    change_ref = (created.get("id") or "").strip()
    if "~" in change_ref:
        tail = change_ref.rsplit("~", 1)[-1].strip()
        if re.match(r"^I[0-9a-fA-F]{40}$", tail):
            return tail
    return ""


def ensure_change_id(commit_msg: str, change_id: Optional[str] = None) -> str:
    """Ensure message ends with Change-Id. Prefer Gerrit's assigned id to avoid HTTP 409."""
    import re
    msg = (commit_msg or "").rstrip()
    existing = None
    found = re.search(r"(?m)^\s*Change-Id:\s*(I[0-9a-fA-F]{40})\s*$", msg)
    if found:
        existing = found.group(1)
    msg = re.sub(r"(?m)^\s*Change-Id:\s*\S+\s*$", "", msg).rstrip()
    cid = (change_id or "").strip()
    if cid and "~" in cid:
        cid = cid.rsplit("~", 1)[-1].strip()
    if not re.match(r"^I[0-9a-fA-F]{40}$", cid or ""):
        cid = existing or generate_change_id()
    return msg + "\n\nChange-Id: %s\n" % cid


def infer_lst_component(test_names: Sequence[str]) -> str:
    """Majority package heuristic for Component: in Owner header."""
    counts = {}
    for name in test_names or []:
        n = (name or "").strip()
        if n.startswith("robo."):
            key = "Robo"
        elif n.startswith("cdp.stargate."):
            key = "Stargate"
        elif n.startswith("cdp.hades."):
            key = "Hades"
        elif n.startswith("cdp."):
            key = "CDP"
        else:
            key = "CDP"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "CDP"
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


_META_PREFIXES = ("# Owner:", "# Tracking ticket:", "# Supervisor type:", "#Owner:")
_STRUCTURAL_PREFIXES = ("summary:", "testcases:", "assignee:")


def _is_meta_line(stripped: str) -> bool:
    s = (stripped or "").strip()
    if s.startswith("#Owner:") or s.startswith("# Owner:"):
        return True
    return any(s.startswith(p) for p in _META_PREFIXES)


def _is_structural_line(stripped: str) -> bool:
    low = (stripped or "").strip().lower()
    if low == "]":
        return True
    return any(low.startswith(p) for p in _STRUCTURAL_PREFIXES)


def canonical_test_name(line: str) -> str:
    """Exact test name from an LST line: strip whitespace, quotes, and a trailing comma."""
    s = (line or "").strip()
    if not s or s.startswith("#") or _is_structural_line(s):
        return ""
    if s.endswith(","):
        s = s[:-1].rstrip()
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1].strip()
    if s.endswith(","):
        s = s[:-1].rstrip()
    return s


def resolve_test_name_in_lst(query: str, existing: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """Map a user/query test name onto an LST line name.

    Returns ``(resolved_full_name, [])`` on a unique match, ``(None, [])`` when
    nothing matches, or ``(None, candidates)`` when multiple lines match (ambiguous).

    Matching order: exact → unique safe prefix/substring (Sourcegraph-style).
    Near-names like ``test_foo`` vs ``test_foo_bar`` are *not* treated as matches.
    Truncated unique names like ``test_mantle_ke`` → ``test_mantle_key_rotation`` are.
    """
    q = (query or "").strip().rstrip(",").strip()
    if (q.startswith('"') and q.endswith('"')) or (q.startswith("'") and q.endswith("'")):
        q = q[1:-1].strip()
    if not q:
        return None, []
    names = [n for n in existing if n]
    if q in names:
        return q, []

    def _is_near_name(query_s: str, hit: str) -> bool:
        """True when hit is a longer sibling name (test_foo vs test_foo_bar), not a truncation."""
        if hit == query_s or not hit.startswith(query_s):
            return False
        rest = hit[len(query_s):]
        if not rest.startswith("_"):
            return False
        q_last = query_s.rsplit(".", 1)[-1]
        h_last = hit.rsplit(".", 1)[-1]
        return h_last.startswith(q_last + "_")

    def _safe_hits(cands: List[str]) -> List[str]:
        return [h for h in cands if not _is_near_name(q, h)]

    prefix_hits = _safe_hits([
        n for n in names
        if n.startswith(q) and (len(n) == len(q) or n[len(q)] in "._")
    ])
    if len(prefix_hits) == 1:
        return prefix_hits[0], []
    if len(prefix_hits) > 1:
        return None, prefix_hits

    substr_hits = _safe_hits([n for n in names if q in n])
    if len(substr_hits) == 1:
        return substr_hits[0], []
    if len(substr_hits) > 1:
        return None, substr_hits
    return None, []


def lst_test_names(lst_content: str) -> List[str]:
    """Ordered unique canonical test names from LST file content."""
    out = []
    seen = set()
    for ln in (lst_content or "").splitlines():
        name = canonical_test_name(ln)
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def match_tests_in_lst(
    lst_content: str, test_names: Sequence[str]
) -> Tuple[List[str], List[str], Dict[str, str], Dict[str, List[str]]]:
    """Return (present_resolved, not_present, resolved_from, ambiguous).

    ``present_resolved`` uses full LST line names. ``resolved_from`` maps
    full LST name → original query when they differ. ``ambiguous`` maps
    query → candidate LST names.
    """
    existing = lst_test_names(lst_content)
    present = []
    not_present = []
    resolved_from: Dict[str, str] = {}
    ambiguous: Dict[str, List[str]] = {}
    seen_present = set()
    for t in test_names or []:
        raw = (t or "").strip()
        if not raw:
            continue
        resolved, candidates = resolve_test_name_in_lst(raw, existing)
        if resolved:
            if resolved not in seen_present:
                seen_present.add(resolved)
                present.append(resolved)
            q = raw.rstrip(",").strip()
            if (q.startswith('"') and q.endswith('"')) or (q.startswith("'") and q.endswith("'")):
                q = q[1:-1].strip()
            if q != resolved:
                resolved_from[resolved] = q
        elif candidates:
            not_present.append(raw.rstrip(",").strip() or raw)
            ambiguous[raw.rstrip(",").strip() or raw] = candidates
        else:
            not_present.append(raw.rstrip(",").strip() or raw)
    return present, not_present, resolved_from, ambiguous


def _endswith_comma(line: str) -> bool:
    return (line or "").rstrip().endswith(",")


def _with_trailing_comma(line: str) -> str:
    """Ensure a test line has a trailing comma; preserve original newline if present."""
    if line.endswith("\n"):
        core, nl = line[:-1], "\n"
    else:
        core, nl = line, ""
    if core.rstrip().endswith(","):
        return line
    return core.rstrip() + "," + nl


def _without_trailing_comma(line: str) -> str:
    if line.endswith("\n"):
        core, nl = line[:-1], "\n"
    else:
        core, nl = line, ""
    stripped = core.rstrip()
    if stripped.endswith(","):
        return stripped[:-1] + nl
    return line


def _find_testcases_closing_bracket(lines: List[str]) -> Optional[int]:
    """Index of the ``]`` that closes ``testcases: [``, even if assignee/etc. follows."""
    start = None
    for i, line in enumerate(lines):
        if "testcases:" in (line or "").lower():
            start = i
            break
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        if (lines[i] or "").strip() == "]":
            return i
    return None


def _ensure_no_comma_on_last_test_before_bracket(lines: List[str]) -> List[str]:
    """Last test entry immediately before ] must not have a trailing comma."""
    bracket = _find_testcases_closing_bracket(lines)
    if bracket is None:
        # Fallback: last bare ] in the file (ignore trailing blank lines only)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "]":
                bracket = i
                break
            if lines[i].strip():
                break
    if bracket is None:
        return lines
    for j in range(bracket - 1, -1, -1):
        s = lines[j].strip()
        if not s:
            continue
        if _is_meta_line(s) or _is_structural_line(s):
            break
        if canonical_test_name(s):
            lines[j] = _without_trailing_comma(lines[j])
        break
    return lines


def build_handover_lst_block(
    test_names: Sequence[str],
    *,
    owner: str = "",
    branch: str = "",
    tickets: Optional[Sequence[str]] = None,
    component: Optional[str] = None,
    commas_before_bracket: bool = False,
) -> str:
    """Flux-style Owner/Tracking header + exact test name lines.

    When commas_before_bracket is True, every new test gets a trailing comma.
    Callers that insert before ``]`` must then strip the comma from the final
    test via ``_ensure_no_comma_on_last_test_before_bracket``.
    """
    names = [(n or "").strip().rstrip(",") for n in (test_names or []) if (n or "").strip()]
    names = [n for n in names if n]
    if not names:
        return ""
    owner_s = (owner or "").strip()
    branch_s = (branch or "").strip()
    comp = (component or "").strip() or infer_lst_component(names)
    ticket_parts = []
    for t in tickets or []:
        tt = (t or "").strip()
        if tt and tt not in ticket_parts:
            ticket_parts.append(tt)
    ticket_s = ", ".join(ticket_parts)
    owner_bits = []
    if owner_s:
        owner_bits.append("Owner: %s" % owner_s)
    if branch_s:
        owner_bits.append("Branch: %s" % branch_s)
    if comp:
        owner_bits.append("Component: %s" % comp)
    lines = []
    if owner_bits:
        lines.append("# " + ", ".join(owner_bits))
    if ticket_s:
        lines.append("# Tracking ticket: %s" % ticket_s)
    for name in names:
        # Always comma-separate list entries; last-before-] is fixed after insert.
        lines.append((name + ",") if commas_before_bracket else name)
    return "\n".join(lines) + "\n"


def append_missing_tests(
    lst_content: str,
    test_names: Sequence[str],
    *,
    owner: str = "",
    branch: str = "",
    tickets: Optional[Sequence[str]] = None,
    component: Optional[str] = None,
    lst_path: Optional[str] = None,
) -> Tuple[str, List[str], List[str]]:
    """Return (new_content, already_present, to_add). Exact full-line match only.

    Matching ignores a single trailing comma/quotes on existing LST lines so
    ``foo`` matches ``foo,``. Partial/substring resolve is intentionally *not*
    used here — handover must add every selected name that is not already an
    exact LST line (near-names like ``test_foo`` vs ``test_foo_bar`` are distinct).
    Official ``testcases: [ ... ]`` files get comma-separated entries; the last
    test immediately before ``]`` has no trailing comma.
    """
    content = lst_content or ""
    already = []
    to_add = []
    existing = set(lst_test_names(content))
    for name in test_names:
        name = (name or "").strip().rstrip(",")
        if (name.startswith('"') and name.endswith('"')) or (name.startswith("'") and name.endswith("'")):
            name = name[1:-1].strip()
        if not name:
            continue
        if name in existing:
            already.append(name)
        else:
            to_add.append(name)
            existing.add(name)
    if not to_add:
        return content, list(dict.fromkeys(already)), []

    already = list(dict.fromkeys(already))

    # Official milestone LSTs use `testcases: [ ... ]` — insert before the closing bracket
    if "testcases:" in content.lower():
        kept = content.splitlines(keepends=True)
        insert_at = _find_testcases_closing_bracket(kept)
        if insert_at is not None:
            # Previous last test before ] must gain a comma if we append more tests after it
            for j in range(insert_at - 1, -1, -1):
                s = kept[j].strip()
                if not s:
                    continue
                if _is_meta_line(s) or _is_structural_line(s):
                    break
                if canonical_test_name(s) and not _endswith_comma(kept[j]):
                    kept[j] = _with_trailing_comma(kept[j])
                break
            add_block = build_handover_lst_block(
                to_add,
                owner=owner,
                branch=branch,
                tickets=tickets,
                component=component,
                commas_before_bracket=True,
            )
            merged = kept[:insert_at] + add_block.splitlines(keepends=True)
            # Keep original ] and anything after (assignee, etc.)
            merged.extend(kept[insert_at:])
            merged = _ensure_no_comma_on_last_test_before_bracket(merged)
            return "".join(merged), already, to_add

    add_block = build_handover_lst_block(
        to_add,
        owner=owner,
        branch=branch,
        tickets=tickets,
        component=component,
        commas_before_bracket=False,
    )
    suffix = content
    if suffix and not suffix.endswith("\n"):
        suffix += "\n"
    return suffix + add_block, already, to_add


def remove_tests(lst_content: str, test_names: Sequence[str]) -> Tuple[str, List[str], List[str]]:
    """Return (new_content, removed, not_present). Exact stripped-line match only.

    A trailing comma on the LST line is ignored for matching (``foo`` matches ``foo,``).
    Partial queries that uniquely resolve to an LST line remove that full line.
    Also drops the Owner/Tracking/Supervisor block above a group when every test
    under that block is removed. Ensures the last remaining test before ] has no comma.
    """
    existing_list = lst_test_names(lst_content)
    remove_set = set()
    for t in test_names or []:
        raw = (t or "").strip().rstrip(",")
        if not raw:
            continue
        resolved, _candidates = resolve_test_name_in_lst(raw, existing_list)
        if resolved:
            remove_set.add(resolved)

    raw_lines = (lst_content or "").splitlines(keepends=True)
    removed = []
    out = []
    i = 0
    n = len(raw_lines)

    while i < n:
        stripped = raw_lines[i].strip()
        if not _is_meta_line(stripped):
            canon = canonical_test_name(stripped)
            if canon and canon in remove_set:
                removed.append(canon)
            else:
                out.append(raw_lines[i])
            i += 1
            continue

        meta = []
        while i < n and _is_meta_line(raw_lines[i].strip()):
            meta.append(raw_lines[i])
            i += 1
        while i < n and raw_lines[i].strip() == "":
            meta.append(raw_lines[i])
            i += 1

        body = []
        while i < n:
            s = raw_lines[i].strip()
            if _is_meta_line(s) or _is_structural_line(s):
                break
            body.append(raw_lines[i])
            i += 1

        owned = []
        for ln in body:
            c = canonical_test_name(ln)
            if c:
                owned.append(c)
        kept_body = []
        for line in body:
            c = canonical_test_name(line)
            if c and c in remove_set:
                removed.append(c)
            else:
                kept_body.append(line)
        remaining = [canonical_test_name(ln) for ln in kept_body if canonical_test_name(ln)]
        drop_meta = bool(owned) and not remaining
        if not drop_meta:
            out.extend(meta)
        out.extend(kept_body)

    removed = list(dict.fromkeys(removed))
    not_present = []
    for t in test_names or []:
        raw = (t or "").strip().rstrip(",")
        if not raw:
            continue
        resolved, _candidates = resolve_test_name_in_lst(raw, existing_list)
        if resolved:
            if resolved not in removed:
                not_present.append(raw)
        else:
            not_present.append(raw)

    # If we removed the former last entries before ], drop the comma on the new last.
    out = _ensure_no_comma_on_last_test_before_bracket(out)
    text = "".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    return text, removed, list(dict.fromkeys(not_present))


def gerrit_encode_id(value: str) -> str:
    return urllib.parse.quote((value or "").strip(), safe="")


def strip_gerrit_prefix(text: str) -> str:
    raw = text or ""
    if raw.startswith(")]}'"):
        parts = raw.split("\n", 1)
        return parts[1] if len(parts) > 1 else ""
    return raw


def parse_gerrit_json(text: str) -> Any:
    body = strip_gerrit_prefix(text).strip()
    if not body:
        return {}
    return json.loads(body)


def decode_file_content(payload: Any) -> str:
    """Decode Gerrit file content (base64 text/plain, or JSON string of plaintext)."""
    if isinstance(payload, dict):
        payload = payload.get("content") or payload.get("data") or ""
    raw = payload if isinstance(payload, str) else ("" if payload is None else str(payload))
    raw = strip_gerrit_prefix(raw).strip()
    if not raw:
        return ""

    # application/json content endpoint: body is a JSON string of the file text
    if raw.startswith('"') and raw.endswith('"'):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                return parsed
        except Exception:
            pass

    # text/plain content endpoint: body is base64
    if _looks_like_base64(raw):
        try:
            return base64.b64decode(raw, validate=False).decode("utf-8", errors="replace")
        except Exception:
            pass
    return raw


def _looks_like_base64(text: str) -> bool:
    import re
    sample = "".join((text or "").split())
    if len(sample) < 4 or len(sample) % 4 != 0:
        return False
    return re.fullmatch(r"[A-Za-z0-9+/]+=*", sample) is not None


def change_web_url(gerrit_url: str, project: str, change_number: Any) -> str:
    base = (gerrit_url or "").rstrip("/")
    proj = (project or "").strip("/")
    num = str(change_number or "").strip()
    if not num:
        return "%s/q/status:open+project:%s" % (base, urllib.parse.quote(proj, safe=""))
    return "%s/c/%s/+/%s" % (base, proj, num)


class GerritLstClient:
    def __init__(self, base_url: str, username: str, password: str, project: str, transport: Optional[Transport] = None):
        self.base_url = (base_url or "").rstrip("/")
        self.username = username
        self.password = password
        self.project = (project or "nutest-py3-tests").strip("/")
        self.transport = transport
        self._session = None if transport else requests.Session()

    def _request(self, method: str, path: str, json_body=None, data=None, content_type=None, timeout=30, accept=None):
        url = self.base_url + path
        headers = {"Accept": accept or "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        elif json_body is not None:
            headers["Content-Type"] = "application/json"
        try:
            if self.transport:
                resp = self.transport(
                    method=method,
                    url=url,
                    json=json_body,
                    data=data,
                    headers=headers,
                    auth=(self.username, self.password),
                    timeout=timeout,
                )
            else:
                resp = self._session.request(
                    method,
                    url,
                    json=json_body,
                    data=data,
                    headers=headers,
                    auth=(self.username, self.password),
                    timeout=timeout,
                    verify=False,
                )
        except requests.exceptions.Timeout as exc:
            raise GerritRestError("Gerrit request timed out: %s %s" % (method, path), 504) from exc
        except requests.exceptions.ConnectionError as exc:
            raise GerritRestError("Cannot reach Gerrit at %s" % self.base_url, 503) from exc

        status = int(getattr(resp, "status_code", 0) or 0)
        text = getattr(resp, "text", "") or ""
        if status >= 400:
            detail = text[:400]
            try:
                parsed = parse_gerrit_json(text)
                if isinstance(parsed, dict):
                    detail = parsed.get("message") or parsed.get("error") or detail
            except Exception:
                pass
            raise GerritRestError(
                "Gerrit %s %s failed (HTTP %s): %s" % (method, path, status, detail),
                502 if status >= 500 else status,
                {"gerrit_status": status},
            )
        return text

    def get_file(self, branch: str, file_path: str) -> str:
        path = "/a/projects/%s/branches/%s/files/%s/content" % (
            gerrit_encode_id(self.project),
            gerrit_encode_id(branch),
            gerrit_encode_id(file_path),
        )
        # Prefer text/plain (base64). application/json returns a JSON string of
        # plaintext; mishandling that rewrites the whole LST in the CR diff.
        text = self._request("GET", path, timeout=30, accept="text/plain")
        try:
            parsed = parse_gerrit_json(text)
        except Exception:
            parsed = None
        if isinstance(parsed, (dict, str)):
            return decode_file_content(parsed)
        return decode_file_content(text)

    def create_change(self, branch: str, subject: str) -> Dict[str, Any]:
        body = {
            "project": self.project,
            "branch": branch,
            "subject": (subject or "LST update").split("\n", 1)[0][:200],
            "status": "NEW",
        }
        text = self._request("POST", "/a/changes/", json_body=body, timeout=30)
        parsed = parse_gerrit_json(text)
        if not isinstance(parsed, dict) or not parsed.get("_number"):
            raise GerritRestError("Gerrit did not return a change number", 502, {"body": parsed})
        return parsed

    def put_edit(self, change_id: str, file_path: str, content: str) -> None:
        path = "/a/changes/%s/edit/%s" % (gerrit_encode_id(str(change_id)), gerrit_encode_id(file_path))
        self._request(
            "PUT",
            path,
            data=(content or "").encode("utf-8"),
            content_type="text/plain; charset=UTF-8",
            timeout=60,
            accept="application/json",
        )

    def set_message(self, change_id: str, message: str, change_id_footer: Optional[str] = None) -> None:
        path = "/a/changes/%s/edit:message" % gerrit_encode_id(str(change_id))
        body = {"message": ensure_change_id(message, change_id=change_id_footer)}
        self._request("PUT", path, json_body=body, timeout=30)

    def publish(self, change_id: str) -> None:
        path = "/a/changes/%s/edit:publish" % gerrit_encode_id(str(change_id))
        self._request("POST", path, json_body={}, timeout=60)

    def add_reviewers(self, change_id: str, reviewers: Sequence[str]) -> None:
        path = "/a/changes/%s/reviewers" % gerrit_encode_id(str(change_id))
        for reviewer in reviewers or []:
            rid = (reviewer or "").strip()
            if not rid:
                continue
            try:
                self._request("POST", path, json_body={"reviewer": rid}, timeout=20)
            except GerritRestError as exc:
                logger.warning("Could not add reviewer %s: %s", rid, exc.message)

    def publish_lst_edits(
        self,
        branch: str,
        commit_message: str,
        file_contents: Dict[str, str],
        reviewers: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Create one change, write each LST file, publish, add reviewers."""
        if not file_contents:
            raise GerritRestError("No LST file changes to publish", 400)
        created = self.create_change(branch, commit_message)
        number = created.get("_number")
        change_id = created.get("id") or str(number)
        footer = extract_change_id_footer(created)
        for file_path, content in file_contents.items():
            self.put_edit(change_id, file_path, content)
        try:
            self.set_message(change_id, commit_message, change_id_footer=footer or None)
        except GerritRestError as exc:
            # 409 wrong Change-Id: keep Gerrit default subject and still publish file edits
            if "Change-Id" in (exc.message or "") or exc.status_code == 409:
                logger.warning("edit:message skipped (%s); publishing file edits with original subject", exc.message)
            else:
                raise
        self.publish(change_id)
        self.add_reviewers(change_id, reviewers or [])
        url = change_web_url(self.base_url, self.project, number)
        return {
            "success": True,
            "gerrit_change_id": str(number),
            "gerrit_url": url,
            "cr_url": url,
            "change_id": footer or created.get("change_id") or "",
        }
