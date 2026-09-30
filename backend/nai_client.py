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
_ENV_EMBED_KEY_NAMES = ("NAI_EMBED_API_KEY", "NAI_API_KEY", "AI_API_KEY")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def sanitize_api_key(value: Optional[str]) -> str:
    """Normalize pasted keys: trim, drop quotes, strip a leading 'Bearer '."""
    key = str(value or "").strip()
    if not key or "****" in key:
        return ""
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()
    # Users often paste the full header value from curl samples.
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key

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
        val = sanitize_api_key(os.getenv(name) or "")
        if val:
            return val
    return ""


def env_embed_api_key() -> str:
    for name in _ENV_EMBED_KEY_NAMES:
        val = sanitize_api_key(os.getenv(name) or "")
        if val:
            return val
    return ""


def resolve_api_key(
    username: Optional[str] = None,
    explicit: Optional[str] = None,
    *,
    purpose: str = "chat",
) -> str:
    """Prefer explicit → per-user Settings key → env fallback.

    ``purpose``:
      - ``chat`` / ``reasoning`` → ``nai_api_key``
      - ``embed`` / ``embedding`` → ``nai_embed_api_key`` then ``nai_api_key``
    """
    cleaned = sanitize_api_key(explicit)
    if cleaned:
        return cleaned
    uname = (username or "").strip()
    want_embed = purpose in ("embed", "embedding", "embeddings")
    key_names = (
        ("nai_embed_api_key", "nai_api_key") if want_embed else ("nai_api_key",)
    )
    if uname:
        try:
            from user_keys import get_user_key

            for key_name in key_names:
                user_key = sanitize_api_key(get_user_key(uname, key_name) or "")
                if user_key:
                    return user_key
        except Exception as exc:
            logger.warning("Could not load NAI key for %s: %s", uname, exc)
    return env_embed_api_key() if want_embed else env_api_key()


def _headers(api_key: str) -> Dict[str, str]:
    key = sanitize_api_key(api_key)
    return {
        "Authorization": f"Bearer {key}",
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
    key = resolve_api_key(username=username, explicit=api_key, purpose="chat")
    if not key:
        raise NaiError(
            "NAI Reasoning Access Key missing. Save it under Settings → API Keys → NAI Reasoning Access Key.",
            status=403,
        )
    # Match Enterprise AI gateway samples: model + messages are required.
    # Keep optional fields minimal — some gateway key types reject extras.
    payload: Dict[str, Any] = {
        "model": resolve_model(model),
        "messages": list(messages),
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
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
    key = resolve_api_key(username=username, explicit=api_key, purpose="embed")
    if not key:
        raise NaiError(
            "NAI Embedding Access Key missing. Save it under Settings → API Keys "
            "(NAI Embedding Access Key, or Reasoning key if shared).",
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


def _validate_chat_key(api_key: str) -> Dict[str, Any]:
    """Live check against reasoning chat/completions gateway."""
    key = sanitize_api_key(api_key)
    if not key:
        return {"valid": None, "message": "Not provided"}
    try:
        # Closest to the NAI curl sample (system+user, tiny reply).
        text = chat_text(
            "You are helpful",
            "Reply with exactly one word: hello",
            api_key=key,
            max_tokens=16,
            timeout=45,
        )
        return {
            "valid": True,
            "message": (
                f"Reasoning OK against {NAI_CHAT_BASE} "
                f"(model {NAI_REASONING_DISPLAY} / {NAI_REASONING_MODEL})"
            ),
            "sample": (text or "")[:80],
            "endpoint": f"{NAI_CHAT_BASE}/chat/completions",
        }
    except NaiError as exc:
        body = (exc.body or str(exc)).lower()
        hint = ""
        if "multi-endpoint" in body or exc.status in (401, 403):
            hint = (
                " This key is not authorized for the Reasoning/chat gateway. "
                "Use a chat/completions Access Key for corp "
                f"({NAI_CHAT_BASE}), not an embeddings-only key/name."
            )
        if exc.status in (401, 403):
            return {
                "valid": False,
                "message": f"Unauthorized on Reasoning endpoint: {exc}.{hint}",
                "endpoint": f"{NAI_CHAT_BASE}/chat/completions",
            }
        return {
            "valid": None,
            "message": f"Reasoning live check failed: {exc}",
            "endpoint": f"{NAI_CHAT_BASE}/chat/completions",
        }
    except Exception as exc:
        return {"valid": None, "message": f"Could not reach NAI Reasoning: {exc}"}


def _validate_embed_key(api_key: str) -> Dict[str, Any]:
    """Live check against embeddings endpoint."""
    key = sanitize_api_key(api_key)
    if not key:
        return {"valid": None, "message": "Not provided"}
    try:
        vectors = embeddings(["nai key validation ping"], api_key=key, timeout=45)
        dims = len(vectors[0]) if vectors else 0
        return {
            "valid": True,
            "message": (
                f"Embedding OK against {NAI_EMBED_BASE} "
                f"(model {NAI_EMBEDDING_MODEL}, dims={dims})"
            ),
            "endpoint": f"{NAI_EMBED_BASE}/embeddings",
        }
    except NaiError as exc:
        body = (exc.body or str(exc)).lower()
        hint = ""
        if "multi-endpoint" in body or exc.status in (401, 403):
            hint = (
                " This key is not authorized for embeddings. "
                "Use the Embedding Access Key / API key for "
                f"{NAI_EMBED_BASE} (model {NAI_EMBEDDING_MODEL})."
            )
        if exc.status in (401, 403):
            return {
                "valid": False,
                "message": f"Unauthorized on Embedding endpoint: {exc}.{hint}",
                "endpoint": f"{NAI_EMBED_BASE}/embeddings",
            }
        return {
            "valid": None,
            "message": f"Embedding live check failed: {exc}",
            "endpoint": f"{NAI_EMBED_BASE}/embeddings",
        }
    except Exception as exc:
        return {"valid": None, "message": f"Could not reach NAI Embedding: {exc}"}


def validate_api_key(api_key: str, embed_api_key: Optional[str] = None) -> Dict[str, Any]:
    """Validate Reasoning and Embedding keys against their real endpoints.

    Returns overall ``valid`` True only if Reasoning succeeds (required for AI ops).
    Embedding is reported separately; a shared key is tried for both when embed
    key is omitted.
    """
    chat_key = sanitize_api_key(api_key)
    embed_key = sanitize_api_key(embed_api_key) or chat_key
    if not chat_key and not embed_key:
        return {"valid": None, "message": "Not provided"}

    chat_result = _validate_chat_key(chat_key) if chat_key else {
        "valid": None,
        "message": "Reasoning key not provided",
    }
    embed_result = _validate_embed_key(embed_key) if embed_key else {
        "valid": None,
        "message": "Embedding key not provided",
    }

    parts = [
        f"Reasoning: {chat_result.get('message')}",
        f"Embedding: {embed_result.get('message')}",
    ]
    if chat_result.get("valid") is True:
        overall = True
    elif chat_result.get("valid") is False:
        overall = False
    else:
        overall = None

    return {
        "valid": overall,
        "message": " | ".join(parts),
        "chat": chat_result,
        "embedding": embed_result,
    }


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
