"""Local-first RAG for Cursor AI chat.

Retrieves from team/tag JSON (failed analysis, triage accuracy, handover,
deprecation, RDM patterns, QI context). Answers lookups and lists without an
LLM. Calls AI only for synthesis, and only with retrieved records as context.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from typing import Any, Callable, Dict, List, Tuple

logger = logging.getLogger(__name__)

# Intents the router understands. `existing_local` means Flask's component /
# QI-summary helpers should handle the question (this module returns None).
INTENT_EXISTING_LOCAL = "existing_local"
INTENT_LOOKUP_TICKET = "lookup_ticket"
INTENT_LOOKUP_TEST = "lookup_test"
INTENT_LOOKUP_OWNER = "lookup_owner"
INTENT_LOOKUP_HANDOVER = "lookup_handover"
INTENT_LOOKUP_DEPRECATION = "lookup_deprecation"
INTENT_LIST_FAILED = "list_failed"
INTENT_CREATE_TICKET = "create_ticket"
INTENT_ATTACH_TICKET = "attach_ticket"
INTENT_CONFIRM_ATTACH = "confirm_attach"
INTENT_RETRIEVE = "retrieve"
INTENT_SYNTHESIZE = "synthesize"
INTENT_NONE = "none"

SOURCE_LOCAL = "local"
SOURCE_RAG = "rag"
SOURCE_AI = "ai"

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)
_TICKET_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]+[-_]\d+)\b")
_TEST_NAME_RE = re.compile(
    r"\b(?:(?:cdp|robo|stargate|hades|curator|pithos|nutanix|ahv|cassandra|"
    r"zookeeper|medusa|mantle|xmount|chronos|polaris|insights|uhura|"
    r"acropolis|castor|lazan|anduril|ergon|katana|minerva|prism)"
    r"(?:\.[A-Za-z0-9_~]+){2,}|test_[A-Za-z0-9_]+)\b"
)
_OWNER_RE = re.compile(
    r"\b(?:owned by|owner(?:\s+is)?|belongs to|tests? (?:for|of))\s+"
    r"([A-Za-z][A-Za-z.\-]+)",
    re.I,
)
_WHO_OWNS_RE = re.compile(r"\bwho owns\s+(.+?)(?:\?|$)", re.I)

_STOPWORDS = frozenset({
    "the", "a", "an", "of", "for", "from", "in", "on", "to", "and", "or", "is",
    "was", "are", "were", "how", "many", "what", "which", "who", "me", "this",
    "that", "with", "about", "please", "show", "list", "give", "tell", "did",
    "does", "do", "it", "its", "be", "been", "can", "could", "would", "should",
    "current", "run", "data", "any", "all", "just", "get",
})

_KNOWN_COMPONENTS = (
    "blockstore", "stargate", "hades", "curator", "pithos", "zookeeper",
    "cassandra", "medusa", "mantle", "xmount", "robo", "chronos", "polaris",
    "insights", "manageability", "nutanix", "ahv", "uhura", "acropolis",
    "castor", "lazan", "anduril", "ergon", "katana", "minerva", "prism",
)

_COUNT_QUESTION_RE = re.compile(
    r"\b(pass|passed|succeed|succeeded|success|fail|failed|failure|"
    r"how many|count|list|which|show|status)\b",
    re.I,
)

_SYNTHESIZE_RE = re.compile(
    r"\b(why|root cause|root-cause|summarize|summary of failures|"
    r"compare|suggest|recommend|explain|analyse|analyze|analysis|"
    r"triage summary|what happened|what went wrong)\b",
    re.I,
)

_HANDOVER_RE = re.compile(r"\b(handover|handed over|hand over|onboard(?:ed|ing)?)\b", re.I)
_DEPRECATION_RE = re.compile(r"\b(deprecat(?:e|ed|ion|ing)|removed from lst)\b", re.I)
_OWNER_INTENT_RE = re.compile(
    r"\b(who owns|owner of|owned by|regression owner|owners?)\b", re.I
)
_LIST_FAILED_RE = re.compile(
    r"\b((?:list|show|which|what)\s+(?:the\s+)?(?:failed|failing)\s+"
    r"(?:tests?|testcases?|test cases?)|"
    r"failed\s+(?:tests?|testcases?)\s+(?:list|names?))\b",
    re.I,
)
_DATA_HINT_RE = re.compile(
    r"\b(fail|failed|failure|jira|ticket|owner|handover|deprecat|"
    r"triage|exception|rdm|pattern|regression|testcase|test case)\b",
    re.I,
)
_CREATE_TICKET_RE = re.compile(
    r"\b(create|file|raise|make|creaet)\b.{0,50}\b(ticket|tickets|jira|eng)\b"
    r"|\bnew\s+(an?\s+)?(eng\s+)?ticket\b"
    r"|\b(create|file)\s+eng\b",
    re.I,
)
_ATTACH_TICKET_RE = re.compile(
    r"\b(attach|link)\b.{0,40}\b([A-Za-z][A-Za-z0-9]+[-_]\d+)\b"
    r"|\b([A-Za-z][A-Za-z0-9]+[-_]\d+)\b.{0,20}\b(attach|link)\b",
    re.I,
)
_CONFIRM_ATTACH_RE = re.compile(
    r"^\s*(yes|y|ok|okay|confirm|do it|proceed)(\b|[.!,;:]|$)",
    re.I,
)
_JIRA_BROWSE_URL = "https://jira.nutanix.com/browse/"
_JIRA_CREATE_URL = "https://jira.nutanix.com/secure/CreateIssue!default.jspa"
_TICKET_SAMPLE = 8

_BM25_K1 = 1.4
_BM25_B = 0.75
_MIN_RETRIEVE_SCORE = 2.5
_RETRIEVE_K = 8
_LIST_LIMIT = 40
_EXCEPTION_TEXT_CAP = 1200
_AI_CHUNK_CAP = 900
_AI_CONTEXT_CAP = 7000

_CORPUS_CACHE: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

Loaders = Dict[str, Callable[..., Any]]
AiCaller = Callable[[str, str], str]


def clear_corpus_cache():
    """Drop the in-memory document cache (tests / tag switches)."""
    with _CACHE_LOCK:
        _CORPUS_CACHE.clear()


def _normalize_question_text(text):
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _extract_component(text):
    t = _normalize_question_text(text)
    if not t:
        return None
    for comp in _KNOWN_COMPONENTS:
        if re.search(rf"(?<![a-z0-9_]){re.escape(comp)}(?![a-z0-9_])", t):
            return comp
    return None


def _is_component_count_question(text):
    t = _normalize_question_text(text)
    if not t or not _extract_component(t):
        return False
    return bool(_COUNT_QUESTION_RE.search(t))


def _is_overall_summary_question(text):
    t = _normalize_question_text(text)
    if not t or _extract_component(t):
        return False
    needles = (
        "summary",
        "overview",
        "success count",
        "succeeded",
        "pass rate",
        "pass count",
        "failed count",
        "failure count",
        "how many passed",
        "how many failed",
        "how many succeeded",
        "regression run",
        "test summary",
        "qi summary",
        "status summary",
        "give me summary",
        "give summary",
        "what is the qi",
        "what's the qi",
        "what is qi",
    )
    if any(n in t for n in needles):
        return True
    return bool(re.search(r"^(what('?s| is)?\s+)?(the\s+)?qi\b", t))


def tokenize(text):
    if not text:
        return []
    return [
        tok
        for tok in _TOKEN_RE.findall(str(text).lower())
        if tok not in _STOPWORDS and len(tok) > 1
    ]


def normalize_ticket(value):
    raw = (value or "").strip().upper().replace("_", "-")
    if not raw:
        return ""
    m = re.match(r"([A-Z][A-Z0-9]+)-?(\d+)$", raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return raw


def extract_tickets(text):
    found = []
    seen = set()
    for match in _TICKET_RE.finditer(text or ""):
        ticket = normalize_ticket(match.group(1))
        if ticket and ticket not in seen:
            seen.add(ticket)
            found.append(ticket)
    return found


def extract_test_names(text):
    found = []
    seen = set()
    for match in _TEST_NAME_RE.finditer(text or ""):
        name = match.group(0).strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            found.append(name)
    return found


def extract_owner(text):
    who = _WHO_OWNS_RE.search(text or "")
    if who:
        rest = who.group(1).strip().rstrip("?.").strip()
        tickets = extract_tickets(rest)
        tests = extract_test_names(rest)
        if tickets or tests:
            return None
        token = rest.split()[0] if rest else ""
        if token and token.lower() not in _STOPWORDS:
            return token
    m = _OWNER_RE.search(text or "")
    if m:
        return m.group(1).strip().rstrip(".,")
    return None


def is_create_ticket_intent(question):
    """True for create/file/raise ticket phrases (not 'open ticket ENG-123')."""
    t = _normalize_question_text(question)
    if not t:
        return False
    if re.match(r"open\s+ticket\b", t):
        return False
    if re.search(r"\b(list|show|related)\b.{0,30}\btickets?\b", t) and not re.search(
        r"\b(create|file|raise|make|creaet)\b", t
    ):
        return False
    return bool(_CREATE_TICKET_RE.search(t))


def parse_attach_request(question):
    """Return (ticket_key, is_confirm) for attach/yes follow-ups."""
    t = question or ""
    m = _ATTACH_TICKET_RE.search(t)
    if m:
        raw = m.group(2) or m.group(3) or ""
        key = normalize_ticket(raw)
        if key:
            return key, False
    keys = extract_tickets(t)
    if keys and re.search(r"\b(attach|link|yes|confirm)\b", _normalize_question_text(t)):
        return keys[0], bool(_CONFIRM_ATTACH_RE.search(t))
    if _CONFIRM_ATTACH_RE.search(t):
        return (keys[0] if keys else ""), True
    return "", False


def classify_intent(question):
    """Heuristic intent. Never calls an LLM."""
    t = _normalize_question_text(question)
    if not t:
        return INTENT_NONE
    attach_key, is_confirm = parse_attach_request(question)
    if attach_key and not is_create_ticket_intent(question):
        return INTENT_ATTACH_TICKET
    if is_confirm and not is_create_ticket_intent(question):
        return INTENT_CONFIRM_ATTACH
    if is_create_ticket_intent(question):
        return INTENT_CREATE_TICKET
    tests = extract_test_names(question)
    tickets = extract_tickets(question)
    # Ticket / test-name lookups win over component-count heuristics because
    # dotted names like cdp.stargate.* contain component tokens.
    if _HANDOVER_RE.search(t):
        return INTENT_LOOKUP_HANDOVER
    if _DEPRECATION_RE.search(t):
        return INTENT_LOOKUP_DEPRECATION
    if tickets:
        return INTENT_LOOKUP_TICKET
    if tests:
        if _SYNTHESIZE_RE.search(t):
            return INTENT_SYNTHESIZE
        return INTENT_LOOKUP_TEST
    if _is_component_count_question(question) or _is_overall_summary_question(question):
        return INTENT_EXISTING_LOCAL
    if _OWNER_INTENT_RE.search(t):
        return INTENT_LOOKUP_OWNER
    if _LIST_FAILED_RE.search(t):
        return INTENT_LIST_FAILED
    if _SYNTHESIZE_RE.search(t):
        return INTENT_SYNTHESIZE
    if _DATA_HINT_RE.search(t) or _extract_component(t):
        return INTENT_RETRIEVE
    return INTENT_NONE


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                key = item.get("key") or item.get("id") or item.get("ticket") or ""
                if key:
                    out.append(str(key))
            elif item is not None and str(item).strip():
                out.append(str(item).strip())
        return out
    text = str(value).strip()
    return [text] if text else []


def _tickets_from_record(record):
    tickets = []
    seen = set()
    for key in (
        "jira_tickets",
        "jira_ticket",
        "tickets",
        "bug_tickets",
        "handover_tickets",
        "triage_genie_ticket",
        "triage_genie_ticket_id",
        "jira",
    ):
        for raw in _as_list(record.get(key) if isinstance(record, dict) else None):
            ticket = normalize_ticket(raw)
            if ticket and ticket not in seen:
                seen.add(ticket)
                tickets.append(ticket)
    return tickets


def _test_name_from_record(record):
    if not isinstance(record, dict):
        return ""
    return (
        record.get("testcase_name")
        or record.get("test_name")
        or record.get("name")
        or ""
    ).strip()


def _truncate(text, cap):
    text = (text or "").strip()
    if len(text) <= cap:
        return text
    return text[: cap - 1].rstrip() + "…"


def _safe_call(loader, *args):
    if not callable(loader):
        return None
    try:
        return loader(*args)
    except TypeError:
        try:
            return loader()
        except Exception as exc:
            logger.warning("[cursor-ai-rag] loader failed: %s", exc)
            return None
    except Exception as exc:
        logger.warning("[cursor-ai-rag] loader failed: %s", exc)
        return None


def _doc(
    doc_id,
    source,
    title,
    text,
    fields=None,
    tokens=None,
):
    body = text or ""
    tok = tokens if tokens is not None else tokenize(f"{title} {body}")
    return {
        "id": doc_id,
        "source": source,
        "title": title or "",
        "text": body,
        "fields": fields or {},
        "tokens": tok,
        "length": max(len(tok), 1),
    }


def _docs_from_failed_analysis(payload, tag):
    docs = []
    if not isinstance(payload, dict):
        return docs
    results = payload.get("results") or []
    if not isinstance(results, list):
        return docs
    for idx, rec in enumerate(results):
        if not isinstance(rec, dict):
            continue
        name = _test_name_from_record(rec)
        tickets = _tickets_from_record(rec)
        owner = (rec.get("regression_owner") or "").strip()
        summary = (rec.get("exception_summary") or "")[:_EXCEPTION_TEXT_CAP]
        exception = (rec.get("exception") or "")[:400]
        comments = (rec.get("comments") or "")[:300]
        text_parts = [
            name,
            " ".join(tickets),
            owner,
            rec.get("status") or "",
            rec.get("failure_stage") or "",
            summary,
            exception,
            comments,
        ]
        docs.append(_doc(
            f"failed:{tag}:{idx}:{name}",
            "failed_analysis",
            name or f"failed-{idx}",
            " ".join(p for p in text_parts if p),
            fields={
                "testcase_name": name,
                "testcase_id": (rec.get("testcase_id") or rec.get("agave_test_result_id") or "").strip(),
                "tickets": tickets,
                "owner": owner,
                "status": rec.get("status") or "",
                "failure_stage": rec.get("failure_stage") or "",
                "exception_summary": summary,
                "comments": comments,
                "triage_genie_ticket_id": rec.get("triage_genie_ticket_id") or "",
            },
        ))
    return docs


def _docs_from_triage(payload, tag):
    docs = []
    if not isinstance(payload, dict):
        return docs
    rows = payload.get("testcases") or []
    if not isinstance(rows, list):
        return docs
    for idx, rec in enumerate(rows):
        if not isinstance(rec, dict):
            continue
        name = _test_name_from_record(rec)
        tickets = _tickets_from_record(rec)
        owner = (rec.get("regression_owner") or rec.get("owner") or "").strip()
        text_parts = [
            name,
            " ".join(tickets),
            owner,
            rec.get("status") or "",
            rec.get("match_status") or "",
        ]
        docs.append(_doc(
            f"triage:{tag}:{idx}:{name}",
            "triage",
            name or f"triage-{idx}",
            " ".join(p for p in text_parts if p),
            fields={
                "testcase_name": name,
                "testcase_id": (rec.get("testcase_id") or "").strip() if isinstance(rec.get("testcase_id"), str) else str(rec.get("testcase_id") or "").strip(),
                "tickets": tickets,
                "owner": owner,
                "status": rec.get("status") or "",
                "match_status": rec.get("match_status") or "",
            },
        ))
    return docs


def _docs_from_records(records, source, tag_or_label, date_field):
    docs = []
    if not isinstance(records, list):
        return docs
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        name = _test_name_from_record(rec)
        tickets = _tickets_from_record(rec)
        who = (rec.get("by_whom") or "").strip()
        branch = (rec.get("branch") or "").strip()
        lst_file = (rec.get("lst_file") or "").strip()
        notes = (rec.get("notes") or "")[:400]
        text_parts = [
            name,
            " ".join(tickets),
            who,
            branch,
            lst_file,
            rec.get("cr_status") or "",
            notes,
            rec.get(date_field) or "",
        ]
        docs.append(_doc(
            f"{source}:{idx}:{name}",
            source,
            name or f"{source}-{idx}",
            " ".join(p for p in text_parts if p),
            fields={
                "testcase_name": name,
                "tickets": tickets,
                "by_whom": who,
                "branch": branch,
                "lst_file": lst_file,
                "date": rec.get(date_field) or "",
                "notes": notes,
                "cr_status": rec.get("cr_status") or "",
            },
        ))
    return docs


def _docs_from_rdm(patterns):
    docs = []
    rows = patterns
    if isinstance(patterns, dict):
        rows = patterns.get("patterns") or []
    if not isinstance(rows, list):
        return docs
    for idx, rec in enumerate(rows):
        if not isinstance(rec, dict):
            continue
        pid = rec.get("id") or f"rdm-{idx}"
        tickets = _tickets_from_record(rec)
        desc = rec.get("description") or ""
        root = rec.get("root_cause") or ""
        action = rec.get("action") or rec.get("comment_template") or ""
        category = rec.get("category") or ""
        regex = rec.get("regex") or ""
        if hasattr(regex, "pattern"):
            regex = regex.pattern
        text_parts = [str(pid), " ".join(tickets), category, desc, root, action, str(regex)]
        docs.append(_doc(
            f"rdm:{pid}",
            "rdm",
            str(pid),
            " ".join(p for p in text_parts if p),
            fields={
                "pattern_id": str(pid),
                "tickets": tickets,
                "category": category,
                "description": desc,
                "root_cause": root,
                "action": action,
            },
        ))
    return docs


def build_corpus(tag, loaders, regression_context="", cache_key=None):
    """Build (and optionally cache) retrieval documents for a tag."""
    loaders = loaders or {}
    fa = _safe_call(loaders.get("failed_analysis"), tag)
    ta = _safe_call(loaders.get("triage_accuracy"), tag)
    ho = _safe_call(loaders.get("handover"))
    de = _safe_call(loaders.get("deprecation"))
    rdm = _safe_call(loaders.get("rdm_patterns"))

    fa_n = len((fa or {}).get("results") or []) if isinstance(fa, dict) else 0
    ta_n = len((ta or {}).get("testcases") or []) if isinstance(ta, dict) else 0
    ho_n = len(ho) if isinstance(ho, list) else 0
    de_n = len(de) if isinstance(de, list) else 0
    rdm_n = (
        len(rdm.get("patterns") or []) if isinstance(rdm, dict)
        else (len(rdm) if isinstance(rdm, list) else 0)
    )
    fa_saved = (fa or {}).get("saved_at") if isinstance(fa, dict) else ""
    fingerprint = cache_key
    if fingerprint is None:
        fingerprint = (
            tag or "",
            fa_n,
            fa_saved,
            ta_n,
            ho_n,
            de_n,
            rdm_n,
            hash((regression_context or "")[:500]),
        )
    if fingerprint is not False:
        with _CACHE_LOCK:
            cached = _CORPUS_CACHE.get(fingerprint)
        if cached is not None:
            return cached

    docs = []
    if regression_context and str(regression_context).strip():
        ctx = str(regression_context).strip()
        docs.append(_doc(
            "qi-summary",
            "qi",
            f"QI summary {tag or ''}".strip(),
            ctx,
            fields={"context": ctx},
        ))
    docs.extend(_docs_from_failed_analysis(fa, tag or ""))
    docs.extend(_docs_from_triage(ta, tag or ""))
    docs.extend(_docs_from_records(ho if isinstance(ho, list) else [], "handover", tag, "handover_date"))
    docs.extend(_docs_from_records(de if isinstance(de, list) else [], "deprecation", tag, "deprecation_date"))
    docs.extend(_docs_from_rdm(rdm))

    if fingerprint is not False:
        with _CACHE_LOCK:
            _CORPUS_CACHE[fingerprint] = docs
    return docs


def _idf_map(docs):
    df = {}
    n = max(len(docs), 1)
    for doc in docs:
        for tok in set(doc.get("tokens") or []):
            df[tok] = df.get(tok, 0) + 1
    return {
        tok: math.log((n - count + 0.5) / (count + 0.5) + 1.0)
        for tok, count in df.items()
    }


def _avg_len(docs):
    if not docs:
        return 1.0
    return sum(d.get("length") or 1 for d in docs) / float(len(docs))


def _field_boosts(query, doc, tickets, tests, owner):
    score = 0.0
    fields = doc.get("fields") or {}
    name = (fields.get("testcase_name") or doc.get("title") or "").lower()
    doc_tickets = {normalize_ticket(t) for t in (fields.get("tickets") or [])}
    doc_owner = (fields.get("owner") or fields.get("by_whom") or "").lower()
    q = (query or "").lower()

    for ticket in tickets:
        if ticket in doc_tickets:
            score += 40.0
        elif ticket.lower() in (doc.get("text") or "").lower():
            score += 20.0
    for test in tests:
        tl = test.lower()
        if name == tl:
            score += 50.0
        elif tl in name or name in tl:
            score += 28.0
    if owner and doc_owner and owner.lower() == doc_owner:
        score += 22.0
    elif owner and owner.lower() in doc_owner:
        score += 12.0
    if name and name in q:
        score += 15.0
    return score


def retrieve(question, docs, k=_RETRIEVE_K):
    """BM25-style ranking with exact ticket / test-name / owner boosts."""
    if not question or not docs:
        return []
    q_tokens = tokenize(question)
    tickets = extract_tickets(question)
    tests = extract_test_names(question)
    owner = extract_owner(question)
    if not q_tokens and not tickets and not tests and not owner:
        return []

    idf = _idf_map(docs)
    avgdl = _avg_len(docs)
    scored = []
    for doc in docs:
        tf = {}
        for tok in doc.get("tokens") or []:
            tf[tok] = tf.get(tok, 0) + 1
        dl = doc.get("length") or 1
        bm25 = 0.0
        for tok in q_tokens:
            freq = tf.get(tok, 0)
            if not freq:
                continue
            denom = freq + _BM25_K1 * (1 - _BM25_B + _BM25_B * dl / avgdl)
            bm25 += idf.get(tok, 0.0) * (freq * (_BM25_K1 + 1)) / denom
        boost = _field_boosts(question, doc, tickets, tests, owner)
        total = bm25 + boost
        if total >= _MIN_RETRIEVE_SCORE or boost >= 20:
            scored.append((total, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [doc for _, doc in scored[:k]]


def _format_failed_or_triage(doc):
    f = doc.get("fields") or {}
    name = f.get("testcase_name") or doc.get("title") or "(unnamed)"
    tickets = ", ".join(f.get("tickets") or []) or "none"
    owner = f.get("owner") or "unassigned"
    status = f.get("status") or ""
    extra = f.get("exception_summary") or f.get("match_status") or ""
    lines = [f"- **{name}**"]
    meta = []
    if status:
        meta.append(status)
    meta.append(f"owner: {owner}")
    meta.append(f"tickets: {tickets}")
    if f.get("failure_stage"):
        meta.append(f"stage: {f['failure_stage']}")
    if f.get("triage_genie_ticket_id"):
        meta.append(f"TG: {f['triage_genie_ticket_id']}")
    lines.append(f"  {'; '.join(meta)}")
    if extra:
        lines.append(f"  {_truncate(extra, 280)}")
    return "\n".join(lines)


def _format_handover_like(doc, kind):
    f = doc.get("fields") or {}
    name = f.get("testcase_name") or doc.get("title") or "(unnamed)"
    tickets = ", ".join(f.get("tickets") or []) or "none"
    who = f.get("by_whom") or "unknown"
    date = f.get("date") or ""
    branch = f.get("branch") or ""
    lst_file = f.get("lst_file") or ""
    lines = [f"- **{name}** ({kind})"]
    lines.append(f"  by {who}; tickets: {tickets}")
    detail = []
    if date:
        detail.append(date)
    if branch:
        detail.append(branch)
    if lst_file:
        detail.append(lst_file)
    if f.get("cr_status"):
        detail.append(f"CR {f['cr_status']}")
    if detail:
        lines.append("  " + " · ".join(detail))
    if f.get("notes"):
        lines.append(f"  {_truncate(f['notes'], 200)}")
    return "\n".join(lines)


def _format_rdm(doc):
    f = doc.get("fields") or {}
    pid = f.get("pattern_id") or doc.get("title")
    tickets = ", ".join(f.get("tickets") or []) or "none"
    lines = [f"- **{pid}** ({f.get('category') or 'RDM'})"]
    if f.get("description"):
        lines.append(f"  {_truncate(f['description'], 280)}")
    if f.get("root_cause"):
        lines.append(f"  Root cause: {_truncate(f['root_cause'], 280)}")
    lines.append(f"  tickets: {tickets}")
    return "\n".join(lines)


def format_documents(docs, heading=None, limit=_LIST_LIMIT):
    if not docs:
        return ""
    blocks = []
    if heading:
        blocks.append(heading)
    for doc in docs[:limit]:
        source = doc.get("source")
        if source in ("failed_analysis", "triage"):
            blocks.append(_format_failed_or_triage(doc))
        elif source in ("handover", "deprecation"):
            blocks.append(_format_handover_like(doc, source))
        elif source == "rdm":
            blocks.append(_format_rdm(doc))
        elif source == "qi":
            blocks.append(_truncate(doc.get("text") or "", 1500))
        else:
            blocks.append(f"- **{doc.get('title')}**: {_truncate(doc.get('text'), 240)}")
    more = len(docs) - limit
    if more > 0:
        blocks.append(f"\n_…and {more} more matching records._")
    return "\n".join(blocks)


def _docs_matching_tickets(docs, tickets):
    wanted = {normalize_ticket(t) for t in tickets if t}
    if not wanted:
        return []
    hits = []
    for doc in docs:
        fields = doc.get("fields") or {}
        have = {normalize_ticket(t) for t in (fields.get("tickets") or [])}
        if have & wanted:
            hits.append(doc)
    return hits


def _docs_matching_tests(docs, tests):
    wanted = [t.lower() for t in tests if t]
    if not wanted:
        return []
    hits = []
    for doc in docs:
        name = ((doc.get("fields") or {}).get("testcase_name") or doc.get("title") or "").lower()
        if any(w == name or w in name or name in w for w in wanted):
            hits.append(doc)
    return hits


def _docs_matching_owner(docs, owner):
    if not owner:
        return []
    needle = owner.lower()
    hits = []
    for doc in docs:
        if doc.get("source") not in ("failed_analysis", "triage"):
            continue
        fields = doc.get("fields") or {}
        doc_owner = (fields.get("owner") or "").lower()
        if doc_owner and (needle == doc_owner or needle in doc_owner or doc_owner in needle):
            hits.append(doc)
    return hits


def _try_structured_lookup(intent, question, docs):
    tickets = extract_tickets(question)
    tests = extract_test_names(question)
    owner = extract_owner(question)

    if intent == INTENT_LOOKUP_TICKET and tickets:
        hits = _docs_matching_tickets(docs, tickets)
        if not hits:
            return None
        label = ", ".join(tickets)
        return {
            "reply": format_documents(hits, heading=f"Records for **{label}** ({len(hits)}):"),
            "source": SOURCE_LOCAL,
        }

    if intent == INTENT_LOOKUP_TEST and tests:
        hits = _docs_matching_tests(docs, tests)
        if not hits:
            return None
        return {
            "reply": format_documents(hits, heading=f"Records for **{tests[0]}**:"),
            "source": SOURCE_LOCAL,
        }

    if intent == INTENT_LOOKUP_OWNER:
        if not owner and tickets:
            hits = _docs_matching_tickets(docs, tickets)
            owners = sorted({
                (d.get("fields") or {}).get("owner")
                for d in hits
                if (d.get("fields") or {}).get("owner")
            })
            if owners:
                return {
                    "reply": (
                        f"**{', '.join(tickets)}** owner(s): **{', '.join(owners)}**\n\n"
                        + format_documents(hits)
                    ),
                    "source": SOURCE_LOCAL,
                }
            if hits:
                return {
                    "reply": format_documents(hits, heading=f"No owner field on records for **{', '.join(tickets)}**:"),
                    "source": SOURCE_LOCAL,
                }
            return None
        hits = _docs_matching_owner(docs, owner)
        if not hits:
            return None
        return {
            "reply": format_documents(
                hits,
                heading=f"Tests for owner **{owner}** ({len(hits)}):",
            ),
            "source": SOURCE_LOCAL,
        }

    if intent == INTENT_LOOKUP_HANDOVER:
        pool = [d for d in docs if d.get("source") == "handover"]
        hits = []
        if tests:
            hits = _docs_matching_tests(pool, tests)
        if not hits and tickets:
            hits = _docs_matching_tickets(pool, tickets)
        if not hits and (tests or tickets):
            return None
        if not hits:
            hits = retrieve(question, pool, k=_LIST_LIMIT)
        if not hits:
            hits = pool[:_LIST_LIMIT]
        if not hits:
            return None
        return {
            "reply": format_documents(hits, heading=f"Handover records ({len(hits)}):"),
            "source": SOURCE_LOCAL,
        }

    if intent == INTENT_LOOKUP_DEPRECATION:
        pool = [d for d in docs if d.get("source") == "deprecation"]
        hits = []
        if tests:
            hits = _docs_matching_tests(pool, tests)
        if not hits and tickets:
            hits = _docs_matching_tickets(pool, tickets)
        if not hits and (tests or tickets):
            return None
        if not hits:
            hits = retrieve(question, pool, k=_LIST_LIMIT) or pool[:_LIST_LIMIT]
        if not hits:
            return None
        return {
            "reply": format_documents(hits, heading=f"Deprecation records ({len(hits)}):"),
            "source": SOURCE_LOCAL,
        }

    if intent == INTENT_LIST_FAILED:
        failed = [d for d in docs if d.get("source") == "failed_analysis"]
        if not failed:
            return None
        return {
            "reply": format_documents(
                failed,
                heading=f"Failed analysis records ({len(failed)}):",
            ),
            "source": SOURCE_LOCAL,
        }

    return None


def _retrieved_context_for_ai(docs):
    chunks = []
    used = 0
    for i, doc in enumerate(docs, 1):
        fields = doc.get("fields") or {}
        body = format_documents([doc]).strip() or _truncate(doc.get("text") or "", _AI_CHUNK_CAP)
        chunk = f"[{i}] source={doc.get('source')} id={doc.get('id')}\n{body}"
        if fields.get("exception_summary"):
            chunk += f"\nexception: {_truncate(fields['exception_summary'], 400)}"
        chunk = _truncate(chunk, _AI_CHUNK_CAP)
        if used + len(chunk) > _AI_CONTEXT_CAP:
            break
        chunks.append(chunk)
        used += len(chunk)
    return "\n\n".join(chunks)


_SYNTH_SYSTEM = (
    "You are the RegX regression assistant. Answer ONLY from the retrieved "
    "records. If the records do not contain the answer, say so. Do not invent "
    "ticket IDs, owners, or root causes. Prefer concise markdown."
)


def _docs_matching_component(docs, component):
    if not component:
        return []
    needle = component.lower()
    hits = []
    for doc in docs:
        if doc.get("source") not in ("failed_analysis", "triage", "handover", "deprecation"):
            continue
        name = ((doc.get("fields") or {}).get("testcase_name") or doc.get("title") or "").lower()
        parts = re.split(r"[./_]", name)
        text = (doc.get("text") or "").lower()
        if needle in parts or re.search(rf"(?<![a-z0-9_]){re.escape(needle)}(?![a-z0-9_])", text):
            hits.append(doc)
    return hits


def _scope_failed_docs(question, docs):
    pool = [d for d in docs if d.get("source") in ("failed_analysis", "triage")]
    tests = extract_test_names(question)
    component = _extract_component(question)
    if tests:
        matched = _docs_matching_tests(pool, tests)
        if matched:
            pool = matched
    elif component:
        matched = _docs_matching_component(pool, component)
        if matched:
            pool = matched
    return pool, component, tests


def _ticket_groups(docs):
    counts = Counter()
    tg_counts = Counter()
    for doc in docs:
        fields = doc.get("fields") or {}
        for ticket in fields.get("tickets") or []:
            key = normalize_ticket(ticket)
            if key:
                counts[key] += 1
        tg = normalize_ticket(fields.get("triage_genie_ticket_id") or "")
        if tg:
            tg_counts[tg] += 1
            if tg not in counts:
                counts[tg] += 1
    return counts, tg_counts


def _docs_missing_key(docs, key):
    key = normalize_ticket(key)
    if not key:
        return list(docs)
    missing = []
    for doc in docs:
        have = {normalize_ticket(t) for t in ((doc.get("fields") or {}).get("tickets") or [])}
        tg = normalize_ticket((doc.get("fields") or {}).get("triage_genie_ticket_id") or "")
        if tg:
            have.add(tg)
        if key not in have:
            missing.append(doc)
    return missing


def _sample_names(docs, limit=_TICKET_SAMPLE):
    names = []
    seen = set()
    for doc in docs:
        name = (doc.get("fields") or {}).get("testcase_name") or doc.get("title") or ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _attach_payload(docs, key, component=""):
    test_ids = []
    comments_by_id = {}
    existing_tickets_by_id = {}
    for doc in docs:
        fields = doc.get("fields") or {}
        tid = (fields.get("testcase_id") or "").strip()
        if not tid or tid in test_ids:
            continue
        test_ids.append(tid)
        comments_by_id[tid] = fields.get("comments") or ""
        existing_tickets_by_id[tid] = [
            normalize_ticket(t) for t in (fields.get("tickets") or []) if t
        ]
    return {
        "action": "offer_attach",
        "attach_key": normalize_ticket(key),
        "test_ids": test_ids,
        "comments_by_id": comments_by_id,
        "existing_tickets_by_id": existing_tickets_by_id,
        "component": component or "",
    }


def try_create_ticket_answer(question, docs, intent=None):
    """Reuse existing FA Jira/TG keys; draft only when none exist. Never dump all rows."""
    intent = intent or classify_intent(question)
    attach_key, _is_confirm = parse_attach_request(question)
    preferred = attach_key or (extract_tickets(question)[0] if extract_tickets(question) else "")
    pool, component, tests = _scope_failed_docs(question, docs)

    if intent == INTENT_CREATE_TICKET and not component and not tests and not preferred:
        return {
            "reply": (
                "Which component or test should the ticket cover? "
                "For example: **create a ticket for the robo issue**.\n\n"
                "I will reuse an existing Failed Analysis Jira/TG key when one is already on those rows "
                "(same as the Failed Testcase Analysis table). I will not dump the QI summary."
            ),
            "source": SOURCE_LOCAL,
            "action": "need_scope",
        }

    if not pool:
        label = component or (tests[0] if tests else "this selection")
        return {
            "reply": (
                f"No failed-analysis / triage records found for **{label}** on the current tag. "
                "Run Failed Testcase Analysis for this tag first, then ask again."
            ),
            "source": SOURCE_LOCAL,
        }

    counts, tg_counts = _ticket_groups(pool)
    dominant = preferred if preferred in counts else (counts.most_common(1)[0][0] if counts else "")
    if preferred and not dominant:
        dominant = preferred

    if dominant:
        have_key = [d for d in pool if d not in _docs_missing_key(pool, dominant)]
        missing = _docs_missing_key(pool, dominant)
        top_lines = []
        for key, n in counts.most_common(5):
            url = f"{_JIRA_BROWSE_URL}{key}"
            extra = " (Triage Genie)" if key in tg_counts and n == tg_counts.get(key) else ""
            top_lines.append(f"- **{key}** on {n}/{len(pool)} tests — {url}{extra}")
        owners = sorted({
            (d.get("fields") or {}).get("owner")
            for d in have_key or pool
            if (d.get("fields") or {}).get("owner")
        })
        exceptions = []
        for d in have_key or pool:
            ex = ((d.get("fields") or {}).get("exception_summary") or "").strip()
            if ex and ex not in exceptions:
                exceptions.append(ex)
            if len(exceptions) >= 2:
                break
        sample = _sample_names(have_key or pool)
        scope_label = component or (tests[0] if tests else "matching tests")
        lines = [
            f"Do **not** create a new Jira ticket for **{scope_label}**.",
            f"**{len(have_key)}** of **{len(pool)}** failed tests already use **{dominant}**.",
            f"[{dominant}]({_JIRA_BROWSE_URL}{dominant})",
            "",
            "Existing keys:",
            *top_lines,
        ]
        if owners:
            lines.append(f"\nOwners: {', '.join(owners)}")
        if exceptions:
            lines.append("Exception: " + _truncate(exceptions[0], 240))
        if sample:
            lines.append("Sample tests:\n" + "\n".join(f"  - {n}" for n in sample))
        payload = {"reply": "\n".join(lines), "source": SOURCE_LOCAL, "attach_key": dominant}
        if missing:
            attachable = [d for d in missing if (d.get("fields") or {}).get("testcase_id")]
            cap_note = f" (up to 50 per request)" if len(attachable) > 50 else ""
            lines.append(
                f"\n**{len(missing)}** test(s) have no **{dominant}** yet. "
                f"Reply `attach {dominant}` to link it the same way Failed Analysis Bulk Update does{cap_note}."
            )
            payload["reply"] = "\n".join(lines)
            if attachable:
                payload.update(_attach_payload(attachable[:50], dominant, component or ""))
        return payload

    owners = sorted({
        (d.get("fields") or {}).get("owner")
        for d in pool
        if (d.get("fields") or {}).get("owner")
    })
    exceptions = []
    for d in pool:
        ex = ((d.get("fields") or {}).get("exception_summary") or "").strip()
        if ex and ex not in exceptions:
            exceptions.append(ex)
        if len(exceptions) >= 3:
            break
    sample = _sample_names(pool)
    scope_label = component or (tests[0] if tests else "these tests")
    lines = [
        f"No Jira / Triage Genie ticket is on the **{len(pool)}** **{scope_label}** failed-analysis row(s).",
        "I will not invent a ticket key. Draft for Failed Analysis:",
        f"- Component/scope: **{scope_label}**",
    ]
    if owners:
        lines.append(f"- Owners: {', '.join(owners)}")
    if exceptions:
        lines.append(f"- Exception: {_truncate(exceptions[0], 280)}")
    if sample:
        lines.append("- Tests:\n" + "\n".join(f"  - {n}" for n in sample))
    lines.append(
        f"\nOpen [{_JIRA_CREATE_URL}]({_JIRA_CREATE_URL}), create the issue, then "
        f"use Failed Analysis **Add ticket** / **Bulk Update**, or reply `attach KEY` "
        f"(for example `attach ENG-123456`)."
    )
    return {"reply": "\n".join(lines), "source": SOURCE_LOCAL, "action": "draft"}


def try_rag_answer(question, docs, intent, call_ai=None):
    """Retrieve top chunks; format locally or synthesize with AI."""
    component = _extract_component(question)
    pool = docs
    if component:
        scoped = _docs_matching_component(docs, component)
        if scoped:
            pool = scoped
    hits = retrieve(question, pool, k=_RETRIEVE_K)
    if not hits and pool is not docs:
        hits = retrieve(question, docs, k=_RETRIEVE_K)
    if not hits and component and pool is not docs:
        hits = pool[:_RETRIEVE_K]
    if not hits:
        return None
    heading = f"Retrieved {len(hits)} matching record(s) from local RegX data:"
    if component:
        heading = f"**{component}** — {len(hits)} matching record(s) from local RegX data:"
    formatted = format_documents(hits, heading=heading)
    if intent == INTENT_SYNTHESIZE and callable(call_ai):
        context = _retrieved_context_for_ai(hits)
        user = (
            f"Question: {question}\n\nRetrieved records:\n{context}\n\n"
            "Answer the question using only those records."
        )
        try:
            text = (call_ai(_SYNTH_SYSTEM, user) or "").strip()
            if text:
                return {"reply": text, "source": SOURCE_AI}
        except Exception as exc:
            logger.warning("[cursor-ai-rag] AI synthesis failed, using retrieved facts: %s", exc)
    return {"reply": formatted, "source": SOURCE_RAG}


def try_local_answer(question, docs, intent=None):
    """Deterministic lookups/lists. Returns a reply dict or None."""
    intent = intent or classify_intent(question)
    if intent == INTENT_EXISTING_LOCAL or intent == INTENT_NONE:
        return None
    if intent in (INTENT_CREATE_TICKET, INTENT_ATTACH_TICKET):
        return try_create_ticket_answer(question, docs, intent=intent)
    structured = _try_structured_lookup(intent, question, docs)
    if structured:
        return structured
    component = _extract_component(question)
    if component and intent == INTENT_RETRIEVE:
        hits = _docs_matching_component(docs, component)
        if hits:
            return {
                "reply": format_documents(
                    hits,
                    heading=f"**{component}** records in local RegX data ({len(hits)}):",
                ),
                "source": SOURCE_LOCAL,
            }
    return None


def answer_chat_question(
    question,
    tag=None,
    regression_context="",
    loaders=None,
    call_ai=None,
    cache_key=None,
):
    """Single entry used by Flask.

    Returns ``{"reply": str, "source": "local"|"rag"|"ai"}`` or ``None`` to
    fall through to Cursor Bridge.
    """
    question = (question or "").strip()
    if not question:
        return None
    intent = classify_intent(question)
    if intent == INTENT_EXISTING_LOCAL:
        return None
    if intent == INTENT_CONFIRM_ATTACH:
        return None
    if intent == INTENT_NONE and not extract_tickets(question) and not extract_test_names(question):
        return None

    docs = build_corpus(
        tag,
        loaders or {},
        regression_context=regression_context,
        cache_key=cache_key,
    )
    if not docs:
        return None

    local = try_local_answer(question, docs, intent=intent)
    if local and local.get("reply"):
        return local

    if intent in (
        INTENT_LOOKUP_TICKET,
        INTENT_LOOKUP_TEST,
        INTENT_LOOKUP_OWNER,
        INTENT_LOOKUP_HANDOVER,
        INTENT_LOOKUP_DEPRECATION,
        INTENT_LIST_FAILED,
        INTENT_CREATE_TICKET,
        INTENT_ATTACH_TICKET,
    ):
        # Structured ask with no matching rows — do not invent an answer.
        return None

    return try_rag_answer(question, docs, intent, call_ai=call_ai)
