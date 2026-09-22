"""Formal Intelligent Triage analysis JSON schema (Phase 2).

Confidences are independent:
  - intermittent_analysis.intermittent_confidence
  - triage_analysis.triage_confidence
There is NO overall_confidence that averages the two.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mcp_service(service: str, available: Optional[bool] = None, ok: Optional[bool] = None, error: Any = None) -> Dict[str, Any]:
    return {
        "service": service,
        "available": bool(available) if available is not None else False,
        "ok": bool(ok) if ok is not None else False,
        "error": error,
        "claimed_success": bool(ok) if ok is not None else False,
    }


def build_empty_analysis(
    testcase_id: str = "",
    testcase_name: str = "",
    status: str = "",
) -> Dict[str, Any]:
    """Return a blank schema_version=1 analysis object."""
    return {
        "schema_version": SCHEMA_VERSION,
        "testcase_id": testcase_id or "",
        "testcase_name": testcase_name or "",
        "status": status or "",
        "jita": {
            "agave_task_id": "",
            "test_log_url": "",
            "failure_stage": "",
            "exception_summary": "",
        },
        "intermittent_analysis": {
            "is_intermittent": False,
            "pattern_id": None,
            "pattern_description": None,
            "intermittent_confidence": None,
            "approved_pattern": False,
            "ai_log_validation": None,
            "action": None,
        },
        "triage_analysis": {
            "issue_type": None,
            "summary": None,
            "recommended_action": None,
            "best_matching_ticket": None,
            "triage_confidence": None,
            "ran_at": None,
            "model": None,
        },
        "triage_genie": {
            "original": {
                "ticket": "",
                "fetched_at": None,
                "raw": None,
                "note": "First evidence only — not RegX final recommendation",
            },
            "ai_validation": None,
        },
        "glean_candidates": {
            "search": {
                "queries": [],
                "candidates": [],
                "snippets": [],
                "search_source": "none",
                "mcp_health": _mcp_service("glean"),
            },
            # Human-triggered only; never auto-filled for every candidate.
            "ai_validation": None,
        },
        "decision": {
            "outcome": None,
            "reasons": [],
            "decided_at": None,
            "thresholds_version": None,
            "deep_ai_recommended": False,
            "deep_ai_started": False,
            "auto_triage_write": None,
            "auto_triage_write_detail": None,
        },
        "mcp_health": {
            "glean": _mcp_service("glean"),
            "sourcegraph": _mcp_service("sourcegraph"),
            "jira": _mcp_service("jira"),
            "triage_genie": _mcp_service("triage_genie"),
        },
        "deep_ai": {
            "status": "not_run",
            "skill_used": None,
            "session_id": None,
            "root_cause": None,
            "classification": None,
            "confidence": None,
            "mcp_health": {
                "sourcegraph": _mcp_service("sourcegraph"),
                "glean": _mcp_service("glean"),
            },
            "follow_ups": [],
        },
        "auto_triage": {
            "applied": False,
            "jira_tickets": [],
            "comment": "",
            "applied_at": None,
            "applied_by": None,
            "mode": None,
        },
        "flux": {
            "status": "not_requested",
            "note": "Flux UI deferred to a later phase",
            "requested_at": None,
            "confirmed_by": None,
            "action_id": None,
            "error": None,
        },
        "audit": {
            "first_level_runs": [],
            "deep_ai_runs": [],
            "glean_ai_validations": [],
            "last_error": None,
        },
    }


def _candidate_match_score(ticket: Dict[str, Any], failure_text: str = "") -> float:
    """Heuristic 0–1 match score from overlap_score / shared terms / open status."""
    if ticket.get("match_score") is not None:
        try:
            return max(0.0, min(1.0, float(ticket["match_score"])))
        except (TypeError, ValueError):
            pass
    overlap = ticket.get("overlap_score")
    score = 0.35
    if isinstance(overlap, (int, float)):
        # overlap_score is a raw shared-term count from TG validation heuristics.
        score = min(1.0, 0.2 + (float(overlap) / 8.0) * 0.7)
    title = "%s %s %s" % (
        ticket.get("jira_summary") or "",
        ticket.get("glean_title") or "",
        ticket.get("glean_snippet") or "",
    )
    fail_words = set(w.lower() for w in (failure_text or "").split() if len(w) > 3)
    title_words = set(w.lower() for w in title.split() if len(w) > 3)
    if fail_words and title_words:
        common = fail_words & title_words
        score = max(score, min(1.0, len(common) / max(4, min(len(fail_words), 12)) + 0.2))
    if ticket.get("is_open") is False:
        score = max(0.0, score - 0.15)
    elif ticket.get("is_open") is True:
        score = min(1.0, score + 0.05)
    return round(score, 3)


def normalize_glean_candidates(
    enriched_tickets: Optional[List[Dict[str, Any]]],
    failure_text: str = "",
) -> List[Dict[str, Any]]:
    """Map enriched tickets → glean_candidates.search.candidates with match_score."""
    out: List[Dict[str, Any]] = []
    for t in enriched_tickets or []:
        ticket_id = t.get("ticket") or ""
        if not ticket_id:
            continue
        entry = {
            "ticket": ticket_id,
            "match_score": _candidate_match_score(t, failure_text),
            "title": t.get("jira_summary") or t.get("glean_title") or "",
            "snippet": (t.get("glean_snippet") or "")[:500],
            "url": t.get("url") or ("https://jira.nutanix.com/browse/%s" % ticket_id),
            "jira_status": t.get("jira_status") or "Unknown",
            "jira_resolution": t.get("jira_resolution") or "",
            "jira_type": t.get("jira_type") or "",
            "is_open": t.get("is_open"),
            "source": t.get("source") or "glean",
            # Per-candidate AI validation is human-triggered and stored separately.
            "ai_validation": t.get("ai_validation"),
        }
        out.append(entry)
    out.sort(key=lambda e: (-(e.get("match_score") or 0), 0 if e.get("is_open") else 1))
    return out


def build_analysis_from_first_level(
    test_result: Dict[str, Any],
    first_level: Dict[str, Any],
    intermittent: Optional[Dict[str, Any]] = None,
    decision: Optional[Dict[str, Any]] = None,
    triage_confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """Compose schema analysis from First-Level + intermittent outputs.

    Does NOT invent an overall_confidence. triage_confidence and
    intermittent_confidence remain independent fields.
    """
    testcase_id = str(test_result.get("testcase_id") or "")
    testcase_name = str(test_result.get("testcase_name") or "")
    status = str(test_result.get("status") or "")
    analysis = build_empty_analysis(testcase_id, testcase_name, status)

    exception_summary = test_result.get("exception_summary") or ""
    analysis["jita"] = {
        "agave_task_id": test_result.get("agave_task_id") or "",
        "test_log_url": first_level.get("test_log_url") or test_result.get("test_log_url") or "",
        "failure_stage": first_level.get("failure_stage") or test_result.get("failure_stage") or "",
        "exception_summary": (exception_summary or "")[:2000],
    }

    tg = first_level.get("tg_ticket_validation") or {}
    original_ticket = (
        (tg.get("ticket") if isinstance(tg, dict) else None)
        or test_result.get("triage_genie_ticket_id")
        or test_result.get("triage_genie_ticket")
        or ""
    )
    analysis["triage_genie"]["original"] = {
        "ticket": original_ticket,
        "fetched_at": _utc_now(),
        "raw": {
            "source": "triage-genie",
            "fields_kept": ["ticket"],
            "jira_status": tg.get("jira_status") if isinstance(tg, dict) else None,
            "jira_summary": tg.get("jira_summary") if isinstance(tg, dict) else None,
        },
        "note": "First evidence only — not RegX final recommendation",
    }
    if isinstance(tg, dict) and (tg.get("verdict") or tg.get("ticket")):
        analysis["triage_genie"]["ai_validation"] = {
            "verdict": tg.get("verdict"),
            "reason": tg.get("reason"),
            "overlap_score": tg.get("overlap_score"),
            "found_in_glean": tg.get("found_in_glean"),
            "is_open": tg.get("is_open"),
            "jira_status": tg.get("jira_status"),
            "jira_summary": tg.get("jira_summary"),
            "ran_at": _utc_now(),
        }

    failure_text = "%s %s" % (exception_summary, test_result.get("exception") or "")
    candidates = normalize_glean_candidates(
        first_level.get("enriched_tickets") or first_level.get("existing_issues"),
        failure_text=failure_text,
    )
    glean_available = first_level.get("glean_available")
    glean_ok = first_level.get("glean_ok")
    search_source = first_level.get("search_source") or "none"
    glean_health = _mcp_service(
        "glean",
        available=glean_available,
        ok=glean_ok,
        error=None if glean_ok else ("unavailable" if glean_available is False else "empty_or_failed"),
    )
    # Never claim success when ok is false.
    if not glean_ok:
        glean_health["claimed_success"] = False

    analysis["glean_candidates"]["search"] = {
        "queries": first_level.get("search_queries") or [],
        "candidates": candidates,
        "snippets": first_level.get("glean_snippets") or [],
        "search_source": search_source,
        "mcp_health": glean_health,
    }
    # ai_validation stays None until a human triggers [AI Validate].

    if intermittent:
        analysis["intermittent_analysis"] = {
            "is_intermittent": bool(intermittent.get("is_intermittent")),
            "pattern_id": intermittent.get("pattern_id"),
            "pattern_description": intermittent.get("pattern_description"),
            "intermittent_confidence": intermittent.get("intermittent_confidence"),
            "approved_pattern": bool(intermittent.get("approved_pattern")),
            "ai_log_validation": intermittent.get("ai_log_validation"),
            "action": intermittent.get("action"),
        }

    # Independent triage confidence — never average with intermittent_confidence.
    if triage_confidence is None:
        triage_confidence = first_level.get("triage_confidence")
    analysis["triage_analysis"] = {
        "issue_type": first_level.get("issue_type"),
        "summary": first_level.get("analysis"),
        "recommended_action": first_level.get("recommended_action"),
        "best_matching_ticket": first_level.get("best_matching_ticket"),
        "triage_confidence": triage_confidence,
        "ran_at": _utc_now(),
        "model": first_level.get("model") or "first_level_ai",
    }

    analysis["mcp_health"]["glean"] = glean_health
    analysis["mcp_health"]["sourcegraph"] = _mcp_service(
        "sourcegraph",
        available=None,
        ok=None,
        error="not_checked_at_first_level",
    )
    # Jira enrichment happened if we have candidates with jira_status != Unknown for some.
    jira_ok = any(
        (c.get("jira_status") and c.get("jira_status") != "Unknown") for c in candidates
    )
    analysis["mcp_health"]["jira"] = _mcp_service("jira", available=True, ok=jira_ok or not candidates)
    analysis["mcp_health"]["triage_genie"] = _mcp_service(
        "triage_genie",
        available=True,
        ok=bool(original_ticket) or True,
        error=None,
    )

    if decision:
        analysis["decision"] = {
            "outcome": decision.get("outcome"),
            "reasons": list(decision.get("reasons") or []),
            "decided_at": decision.get("decided_at") or _utc_now(),
            "thresholds_version": decision.get("thresholds_version"),
            "deep_ai_recommended": bool(decision.get("deep_ai_recommended")),
            "deep_ai_started": False,  # First-Level never auto-starts Deep AI
            "auto_triage_write": decision.get("auto_triage_write"),
            "auto_triage_write_detail": decision.get("auto_triage_write_detail"),
        }

    analysis["audit"]["first_level_runs"].append({
        "ran_at": _utc_now(),
        "outcome": (decision or {}).get("outcome"),
        "triage_confidence": triage_confidence,
        "intermittent_confidence": (intermittent or {}).get("intermittent_confidence"),
    })
    return analysis


def merge_glean_ai_validation(
    analysis: Dict[str, Any],
    validation: Dict[str, Any],
    ticket: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach human-triggered Glean AI validation; keep search candidates intact."""
    out = deepcopy(analysis) if analysis else build_empty_analysis()
    payload = dict(validation or {})
    payload.setdefault("ran_at", _utc_now())
    payload.setdefault("trigger", "human")
    out.setdefault("glean_candidates", {})
    out["glean_candidates"]["ai_validation"] = payload

    # Optionally stamp the specific candidate.
    if ticket:
        search = out["glean_candidates"].setdefault("search", {})
        for cand in search.get("candidates") or []:
            if (cand.get("ticket") or "").upper() == ticket.upper():
                cand["ai_validation"] = payload
                break

    out.setdefault("audit", {}).setdefault("glean_ai_validations", []).append({
        "ticket": ticket,
        "ran_at": payload["ran_at"],
        "verdict": payload.get("verdict") or payload.get("match_verdict"),
    })
    return out


def set_deep_ai_started(
    analysis: Dict[str, Any],
    session_id: str = "",
    skill_used: str = "",
    mcp_health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mark Deep AI as user-started (never call from First-Level auto path)."""
    out = deepcopy(analysis) if analysis else build_empty_analysis()
    out.setdefault("decision", {})
    out["decision"]["deep_ai_started"] = True
    out.setdefault("deep_ai", {})
    out["deep_ai"]["status"] = "running" if not out["deep_ai"].get("root_cause") else "complete"
    if session_id:
        out["deep_ai"]["session_id"] = session_id
    if skill_used:
        out["deep_ai"]["skill_used"] = skill_used
    if mcp_health:
        out["deep_ai"]["mcp_health"] = mcp_health
        out.setdefault("mcp_health", {}).update({
            k: v for k, v in mcp_health.items() if k in ("glean", "sourcegraph")
        })
    out.setdefault("audit", {}).setdefault("deep_ai_runs", []).append({
        "ran_at": _utc_now(),
        "session_id": session_id,
        "skill_used": skill_used,
    })
    return out
