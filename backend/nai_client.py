"""Nutanix Enterprise AI (NAI) client for RegX-AI.

Replaces Cursor SDK / legacy hack-reason endpoints for chat completions
and embeddings. Per-user Access Keys are stored in User Settings
(`nai_api_key`); env vars remain as optional server-wide fallbacks.

Endpoints (override via env):
  Chat:       NAI_CHAT_BASE  (gateway chat/completions)
  Embeddings: NAI_EMBED_BASE (/embeddings)
Models:
  Reasoning:  NAI_REASONING_MODEL  (API id: nemotron3-fp4-uni)
  Embedding:  NAI_EMBEDDING_MODEL  (eng-embed-01)
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

# Display name shown in UI vs API model id used in requests.
NAI_REASONING_DISPLAY = "nemotron-3-fp4-04"
NAI_REASONING_MODEL = os.getenv("NAI_REASONING_MODEL", "nemotron3-fp4-uni")
NAI_EMBEDDING_MODEL = os.getenv("NAI_EMBEDDING_MODEL", "eng-embed-01")

NAI_CHAT_BASE = os.getenv(
    "NAI_CHAT_BASE",
    "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
).rstrip("/")
NAI_EMBED_BASE = os.getenv(
    "NAI_EMBED_BASE",
    "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1",
).rstrip("/")

# Legacy aliases still honored as env fallbacks (never hardcode secrets in git).
_ENV_KEY_NAMES = ("NAI_API_KEY", "AI_API_KEY")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Map UI / legacy model ids onto the NAI reasoning model.
_MODEL_ALIASES = {
    NAI_REASONING_DISPLAY: NAI_REASONING_MODEL,
    "nemotron-3-fp4-04": NAI_REASONING_MODEL,
    "nemotron3-fp4-uni": NAI_REASONING_MODEL,
    "hack-reason": NAI_REASONING_MODEL,
    "claude-sonnet-4-5": NAI_REASONING_MODEL,
    "claude-haiku-4-5": NAI_REASONING_MODEL,
    "claude-sonnet-4-6": NAI_REASONING_MODEL,
    "claude-sonnet-4.6": NAI_REASONING_MODEL,
    "claude-sonnet-4.6-high": NAI_REASONING_MODEL,
    "auto-smart": NAI_REASONING_MODEL,
}


class NaiError(Exception):
    """Raised when an NAI request fails."""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body or ""


def resolve_model(model: Optional[str] = None) -> str:
    raw = (model or "").strip()
    if not raw:
        return NAI_REASONING_MODEL
    return _MODEL_ALIASES.get(raw, _MODEL_ALIASES.get(raw.lower(), raw))


def env_api_key() -> str:
    for name in _ENV_KEY_NAMES:
        val = (os.getenv(name) or "").strip()
        if val:
            return val
    return ""


def resolve_api_key(
    username: Optional[str] = None,
    explicit: Optional[str] = None,
) -> str:
    """Prefer explicit → per-user Settings key → env fallback."""
    if explicit and str(explicit).strip() and "****" not in str(explicit):
        return str(explicit).strip()
    uname = (username or "").strip()
    if uname:
        try:
            from user_keys import get_user_key

            user_key = get_user_key(uname, "nai_api_key")
            if user_key and str(user_key).strip():
                return str(user_key).strip()
        except Exception as exc:
            logger.warning("Could not load nai_api_key for %s: %s", uname, exc)
    return env_api_key()


def _headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _post_json(
    url: str,
    payload: Dict[str, Any],
    api_key: str,
    timeout: int = 120,
) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(api_key), method="POST")
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if resp.getcode() != 200:
                raise NaiError(f"NAI HTTP {resp.getcode()}", status=resp.getcode(), body=raw[:500])
            try:
                return json.loads(raw) if raw else {}
            except json.JSONDecodeError as exc:
                raise NaiError(f"NAI returned non-JSON body: {exc}", body=raw[:500]) from exc
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        except Exception:
            body = ""
        raise NaiError(
            f"NAI HTTP {exc.code}: {(body or str(exc))[:300]}",
            status=exc.code,
            body=body[:500],
        ) from exc
    except urllib.error.URLError as exc:
        raise NaiError(f"NAI unreachable: {exc}") from exc


def chat_completions(
    messages: Sequence[Dict[str, str]],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: Optional[float] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """Call NAI chat/completions. Returns the raw JSON response."""
    key = resolve_api_key(username=username, explicit=api_key)
    if not key:
        raise NaiError(
            "NAI Access Key missing. Save it under Settings → API Keys → NAI Access Key.",
            status=403,
        )
    payload: Dict[str, Any] = {
        "model": resolve_model(model),
        "messages": list(messages),
        "max_tokens": int(max_tokens),
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    url = f"{NAI_CHAT_BASE}/chat/completions"
    return _post_json(url, payload, key, timeout=timeout)


def extract_message_content(response: Dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        raise NaiError("NAI returned no choices")
    content = (choices[0].get("message") or {}).get("content", "")
    return (content or "").strip()


def chat_text(
    system_prompt: str,
    user_content: str,
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    max_tokens: int = 2048,
    timeout: int = 90,
) -> str:
    """Convenience wrapper: system + user → assistant text."""
    messages = [
        {"role": "system", "content": system_prompt or "You are a helpful assistant."},
        {"role": "user", "content": user_content or ""},
    ]
    resp = chat_completions(
        messages,
        model=model,
        api_key=api_key,
        username=username,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return extract_message_content(resp)


def chat_messages(
    messages: Sequence[Dict[str, str]],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> str:
    resp = chat_completions(
        messages,
        model=model,
        api_key=api_key,
        username=username,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    return extract_message_content(resp)


def embeddings(
    inputs: Union[str, Sequence[str]],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    timeout: int = 60,
) -> List[List[float]]:
    """Return embedding vectors for one or more input strings."""
    key = resolve_api_key(username=username, explicit=api_key)
    if not key:
        raise NaiError(
            "NAI Access Key missing. Save it under Settings → API Keys → NAI Access Key.",
            status=403,
        )
    if isinstance(inputs, str):
        input_list: List[str] = [inputs]
    else:
        input_list = [str(x) for x in inputs]
    payload = {
        "model": (model or NAI_EMBEDDING_MODEL).strip() or NAI_EMBEDDING_MODEL,
        "input": input_list,
        "encoding_format": "float",
    }
    url = f"{NAI_EMBED_BASE}/embeddings"
    data = _post_json(url, payload, key, timeout=timeout)
    items = data.get("data") or []
    # Preserve input order by index when present.
    ordered = sorted(items, key=lambda row: row.get("index", 0))
    vectors: List[List[float]] = []
    for row in ordered:
        emb = row.get("embedding")
        if isinstance(emb, list):
            vectors.append([float(x) for x in emb])
    if len(vectors) != len(input_list):
        raise NaiError(
            f"NAI embeddings count mismatch: got {len(vectors)} for {len(input_list)} inputs"
        )
    return vectors


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def validate_api_key(api_key: str) -> Dict[str, Any]:
    """Best-effort live check against chat/completions."""
    key = (api_key or "").strip()
    if not key or "****" in key:
        return {"valid": None, "message": "Not provided"}
    try:
        text = chat_text(
            "You are helpful",
            "Reply with exactly one word: hello",
            api_key=key,
            max_tokens=16,
            timeout=30,
        )
        return {
            "valid": True,
            "message": f"NAI reachable (model {NAI_REASONING_MODEL})",
            "sample": (text or "")[:80],
        }
    except NaiError as exc:
        if exc.status in (401, 403):
            return {"valid": False, "message": f"Unauthorized: {exc}"}
        return {"valid": None, "message": f"Live check failed: {exc}"}
    except Exception as exc:
        return {"valid": None, "message": f"Could not reach NAI: {exc}"}


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.I)


def parse_json_object(text: str) -> Dict[str, Any]:
    """Best-effort extract of a JSON object from model output."""
    raw = (text or "").strip()
    if not raw:
        return {}
    fence = _JSON_FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def analyze_testcase_with_nai(
    *,
    testcase_name: str,
    exception_summary: str = "",
    exception: str = "",
    steps_log: str = "",
    nutest_test_log: str = "",
    test_log_url: str = "",
    jira_tickets: Optional[Iterable[Any]] = None,
    failure_stage: str = "",
    triage_genie_ticket: str = "",
    glean_tickets: Optional[Iterable[Any]] = None,
    glean_snippets: Optional[Iterable[Any]] = None,
    analysis_type: str = "failed",
    rdm_url: str = "",
    rdm_message: str = "",
    username: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Deep testcase analysis via NAI reasoning model (Cursor-bridge compatible shape)."""
    tickets = list(jira_tickets or [])
    glean = list(glean_tickets or [])
    snippets = list(glean_snippets or [])
    system = (
        "You are a senior Nutanix regression failure analyst. "
        "Classify failures as Test Issue, Product Issue, Infra Issue, or Flaky / Timing. "
        "Respond with a single JSON object only (no markdown outside JSON) using keys: "
        "root_cause, classification, confidence, suggested_fix, failing_code, "
        "related_components (array), jira_duplicates (array), triage_report."
    )
    user_parts = [
        f"Analysis type: {analysis_type}",
        f"Testcase: {testcase_name}",
        f"Failure stage: {failure_stage or 'unknown'}",
        f"Exception summary: {(exception_summary or rdm_message or '')[:1500]}",
        f"Exception: {(exception or rdm_message or '')[:2500]}",
        f"Log URL: {test_log_url or rdm_url or ''}",
        f"RDM URL: {rdm_url or ''}",
        f"Triage Genie ticket: {triage_genie_ticket or ''}",
        f"Jira tickets: {json.dumps(tickets)[:1500]}",
        f"Glean tickets: {json.dumps(glean)[:1500]}",
        f"Glean snippets: {json.dumps(snippets)[:1200]}",
        f"steps.log (truncated):\n{(steps_log or '')[:4000]}",
        f"nutest log (truncated):\n{(nutest_test_log or '')[:4000]}",
    ]
    content = chat_text(
        system,
        "\n\n".join(user_parts),
        model=model,
        api_key=api_key,
        username=username,
        max_tokens=3500,
        timeout=180,
    )
    parsed = parse_json_object(content)
    if not parsed:
        parsed = {
            "root_cause": content[:4000] or "NAI returned an empty analysis",
            "classification": "Unknown",
            "confidence": "low",
            "suggested_fix": "",
            "failing_code": "",
            "related_components": [],
            "jira_duplicates": [],
            "triage_report": content[:6000],
        }
    analysis = {
        "root_cause": str(parsed.get("root_cause") or content[:2000] or "").strip(),
        "classification": str(parsed.get("classification") or "Unknown").strip(),
        "confidence": str(parsed.get("confidence") or "medium").strip(),
        "suggested_fix": str(parsed.get("suggested_fix") or "").strip(),
        "failing_code": str(parsed.get("failing_code") or "").strip(),
        "related_components": parsed.get("related_components") or [],
        "jira_duplicates": parsed.get("jira_duplicates") or [],
        "triage_report": str(parsed.get("triage_report") or content[:6000] or "").strip(),
        "provider": "nai",
        "model": resolve_model(model),
    }
    if not isinstance(analysis["related_components"], list):
        analysis["related_components"] = [str(analysis["related_components"])]
    if not isinstance(analysis["jira_duplicates"], list):
        analysis["jira_duplicates"] = [str(analysis["jira_duplicates"])]
    return analysis


def follow_up_with_nai(
    question: str,
    *,
    prior_analysis: Optional[Dict[str, Any]] = None,
    recovery_context: Optional[Dict[str, Any]] = None,
    username: Optional[str] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Answer a Deep AI follow-up using NAI + prior analysis context."""
    prior = prior_analysis or {}
    ctx = recovery_context or {}
    system = (
        "You are continuing a regression triage conversation. "
        "Use the prior analysis as authoritative context. "
        "Respond with JSON only: follow_up_answer, root_cause, classification, "
        "suggested_fix, triage_report."
    )
    user = (
        f"Prior analysis:\n{json.dumps(prior, indent=2)[:5000]}\n\n"
        f"Recovery context:\n{json.dumps(ctx, indent=2)[:2000]}\n\n"
        f"User question:\n{(question or '').strip()}"
    )
    content = chat_text(
        system,
        user,
        model=model,
        api_key=api_key,
        username=username,
        max_tokens=2500,
        timeout=120,
    )
    parsed = parse_json_object(content)
    return {
        "follow_up_answer": str(
            parsed.get("follow_up_answer") or content or ""
        ).strip(),
        "root_cause": str(parsed.get("root_cause") or prior.get("root_cause") or "").strip(),
        "classification": str(
            parsed.get("classification") or prior.get("classification") or "Unknown"
        ).strip(),
        "suggested_fix": str(
            parsed.get("suggested_fix") or prior.get("suggested_fix") or ""
        ).strip(),
        "triage_report": str(
            parsed.get("triage_report") or prior.get("triage_report") or ""
        ).strip(),
        "provider": "nai",
        "model": resolve_model(model),
    }


def sse_chat_events(
    reply: str,
    *,
    model: str = "",
    agent_id: str = "",
    session_id: str = "",
    source: str = "nai",
) -> Iterable[bytes]:
    """Yield SSE chunks compatible with CursorAI streaming UI."""
    text = reply or ""
    # Chunk for progressive UI without needing true token streaming.
    step = 48
    for i in range(0, len(text), step):
        piece = text[i : i + step]
        yield f"data: {json.dumps({'type': 'token', 'text': piece})}\n\n".encode("utf-8")
    done = {
        "type": "done",
        "reply": text,
        "model": model or NAI_REASONING_DISPLAY,
        "agent_id": agent_id or "",
        "session_id": session_id or "",
        "source": source,
        "provider": "nai",
    }
    yield f"data: {json.dumps(done)}\n\n".encode("utf-8")
