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

# Candidate chat bases when a key is bound to a different NAI host/path.
# Order: explicit env base first, then common corp/beta gateway + v1 variants.
_CHAT_BASE_CANDIDATES = tuple(
    dict.fromkeys(
        [
            NAI_CHAT_BASE,
            "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
            "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/v1",
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1",
        ]
    )
)
_EMBED_BASE_CANDIDATES = tuple(
    dict.fromkeys(
        [
            NAI_EMBED_BASE,
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1",
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
            "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/v1",
            "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
        ]
    )
)

# Remember which base+auth style worked for this process (avoids repeated 401 probes).
_WORKING_CHAT: Dict[str, str] = {"base": "", "auth": "bearer"}
_WORKING_EMBED: Dict[str, str] = {"base": "", "auth": "bearer"}

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


def looks_like_key_name(value: Optional[str]) -> bool:
    """Heuristic: NAI 'Key Name' labels are not bearer tokens."""
    key = sanitize_api_key(value)
    if not key:
        return False
    # e.g. CDP-DPRO-5192-AINTNX-1047
    if re.fullmatch(r"[A-Z]{2,}(?:-[A-Z0-9]{2,}){2,}", key):
        return True
    if key.upper().startswith("CDP-DPRO-") or "AINTNX" in key.upper():
        return True
    return False

# Map UI / legacy model ids onto the NAI reasoning model.
_MODEL_ALIASES = {
    NAI_REASONING_DISPLAY: NAI_REASONING_MODEL,
    "nemotron-3-fp4-04": NAI_REASONING_MODEL,
    "nemotron-3-fp4-05": NAI_REASONING_MODEL,
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


def _headers(api_key: str, auth_style: str = "bearer") -> Dict[str, str]:
    key = sanitize_api_key(api_key)
    # Match the known-good curl sample for Reasoning: Authorization + Content-Type only.
    headers = {
        "Content-Type": "application/json",
    }
    style = (auth_style or "bearer").strip().lower()
    if style == "api-key":
        # Some Enterprise AI gateways accept raw api-key header.
        headers["Accept"] = "application/json"
        headers["api-key"] = key
        headers["x-api-key"] = key
    elif style == "both":
        # Gateway + upstream inference: send both common forms.
        headers["Accept"] = "application/json"
        headers["Authorization"] = f"Bearer {key}"
        headers["api-key"] = key
        headers["x-api-key"] = key
    else:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _post_json(
    url: str,
    payload: Dict[str, Any],
    api_key: str,
    timeout: int = 120,
    auth_style: str = "bearer",
) -> Dict[str, Any]:
    """POST JSON while preserving auth headers across redirects.

    stdlib urllib (and requests on cross-host redirects) strip ``Authorization``,
    which surfaces as NAI 401 ``API key is not provided`` on chat/completions
    even when the same token works for /embeddings.
    """
    headers = _headers(api_key, auth_style=auth_style)
    body_bytes = json.dumps(payload).encode("utf-8")

    # Prefer requests (already used by Flask app) with manual redirect following.
    try:
        import requests

        current = url
        for _ in range(6):
            resp = requests.post(
                current,
                data=body_bytes,
                headers=headers,
                timeout=timeout,
                verify=False,
                allow_redirects=False,
            )
            if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("Location") or ""
                if not loc:
                    break
                current = urllib.parse.urljoin(current, loc)
                # 303 must become GET per RFC; NAI gateways normally use 307/308.
                if resp.status_code == 303:
                    get_resp = requests.get(
                        current,
                        headers={k: v for k, v in headers.items() if k.lower() != "content-type"},
                        timeout=timeout,
                        verify=False,
                        allow_redirects=False,
                    )
                    if get_resp.status_code != 200:
                        raise NaiError(
                            f"NAI HTTP {get_resp.status_code}: {(get_resp.text or '')[:300]}",
                            status=get_resp.status_code,
                            body=(get_resp.text or "")[:500],
                        )
                    try:
                        return get_resp.json() if get_resp.text else {}
                    except ValueError as exc:
                        raise NaiError(
                            f"NAI returned non-JSON body: {exc}",
                            body=(get_resp.text or "")[:500],
                        ) from exc
                continue
            if resp.status_code != 200:
                raise NaiError(
                    f"NAI HTTP {resp.status_code}: {(resp.text or '')[:300]}",
                    status=resp.status_code,
                    body=(resp.text or "")[:500],
                )
            try:
                return resp.json() if resp.text else {}
            except ValueError as exc:
                raise NaiError(
                    f"NAI returned non-JSON body: {exc}",
                    body=(resp.text or "")[:500],
                ) from exc
        raise NaiError(f"NAI redirect loop or missing Location for {url}", status=502)
    except ImportError:
        pass
    except NaiError:
        raise
    except Exception as exc:
        # Fall through to urllib if requests transport fails unexpectedly.
        logger.warning("NAI requests transport failed (%s); falling back to urllib", exc)

    class _AuthRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
            newreq = urllib.request.HTTPRedirectHandler.redirect_request(
                self, req, fp, code, msg, headers, newurl
            )
            if newreq is None:
                return None
            # Re-attach auth headers urllib strips on redirect.
            for hdr in ("Authorization", "api-key", "x-api-key", "Api-Key", "X-Api-Key"):
                val = req.get_header(hdr) or req.headers.get(hdr)
                if val:
                    newreq.add_unredirected_header(hdr, val)
            return newreq

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=SSL_CTX),
        _AuthRedirectHandler(),
    )
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=timeout) as resp:
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


def _ordered_bases(candidates: Sequence[str], preferred: str = "") -> List[str]:
    out: List[str] = []
    pref = (preferred or "").rstrip("/")
    if pref:
        out.append(pref)
    for base in candidates:
        b = (base or "").rstrip("/")
        if b and b not in out:
            out.append(b)
    return out


def _pick_best_nai_error(errors: Sequence[Tuple[str, NaiError]]) -> NaiError:
    """Prefer corp Reasoning errors over beta 404 noise from wrong hosts."""
    if not errors:
        return NaiError("NAI request failed with no endpoints attempted", status=502)

    corp_marker = "nai-dre.corp.p10y.ntnxdpro.com"

    def score(item: Tuple[str, NaiError]) -> Tuple[int, int, int]:
        label, exc = item
        body = f"{exc} {exc.body}".lower()
        on_corp = 1 if corp_marker in label else 0
        # Deprioritize empty-key noise and wrong-host 404s.
        if "api key is not provided" in body:
            return (0, on_corp, exc.status or 0)
        if exc.status == 404 and not on_corp:
            return (0, on_corp, 0)
        if "multi-endpoint" in body:
            return (2, on_corp, exc.status or 0)
        if exc.status in (401, 403):
            return (3, on_corp, exc.status or 0)
        if on_corp and "bearer" in label:
            return (5, on_corp, exc.status or 0)
        if "bearer" in label:
            return (4, on_corp, exc.status or 0)
        return (1, on_corp, exc.status or 0)

    label, best = max(errors, key=score)
    detail = " | ".join(f"{lbl} -> {exc}" for lbl, exc in errors[:5])
    return NaiError(
        f"{best} (tried {len(errors)} endpoint/auth variants; best={label})",
        status=best.status,
        body=(best.body or "") + (f"\nAttempts: {detail}" if detail else ""),
    )


def _post_with_failover(
    path_suffix: str,
    payload: Dict[str, Any],
    api_key: str,
    *,
    candidates: Sequence[str],
    working: Dict[str, str],
    timeout: int = 120,
    auth_styles: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Try host/auth combinations until one accepts the key."""
    key = sanitize_api_key(api_key)
    # Do not pin a previously-failed beta host ahead of the known-good corp chat base.
    bases = [b for b in candidates if b] if candidates else []
    seen = set()
    ordered_bases: List[str] = []
    for base in bases:
        b = base.rstrip("/")
        if b and b not in seen:
            seen.add(b)
            ordered_bases.append(b)

    # Prefer Bearer (matches NAI curl samples); then both; api-key last.
    styles: List[str] = []
    preferred_auth = (working.get("auth") or "bearer").lower()
    for style in list(auth_styles or (preferred_auth, "bearer", "both", "api-key")):
        if style and style not in styles:
            styles.append(style)

    errors: List[Tuple[str, NaiError]] = []
    for base in ordered_bases:
        url = f"{base.rstrip('/')}/{path_suffix.lstrip('/')}"
        for style in styles:
            label = f"{url} [{style}]"
            try:
                data = _post_json(url, payload, key, timeout=timeout, auth_style=style)
                working["base"] = base.rstrip("/")
                working["auth"] = style
                logger.info("NAI %s succeeded via base=%s auth=%s", path_suffix, base, style)
                return data
            except NaiError as exc:
                errors.append((label, exc))
                # Wrong path: skip other auth styles on this host.
                if exc.status == 404:
                    break
                # Non-auth failures on a reachable host: don't keep thrashing styles.
                if exc.status and exc.status not in (401, 403):
                    raise
                continue
    raise _pick_best_nai_error(errors)


def _chat_base_candidates() -> List[str]:
    """Reasoning/chat is on corp gateway; embeddings are on beta — do not mix preference.

    Known-good curl:
      https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1/chat/completions
    """
    corp_gateway = "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1"
    preferred_working = (_WORKING_CHAT.get("base") or "").rstrip("/")
    # Only reuse a prior working chat base when it is the corp gateway (never beta).
    pinned = preferred_working if "nai-dre.corp." in preferred_working else ""
    return _ordered_bases(
        [
            pinned,
            NAI_CHAT_BASE,
            corp_gateway,
            "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/v1",
            # Beta chat paths are last-resort only; /embeddings living on beta does not
            # mean chat/completions is available there (often 404).
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/gateway/v1",
            "https://nai-dre.beta.p10y.ntnxdpro.com/enterpriseai/v1",
        ],
        "",
    )


def chat_completions(
    messages: Sequence[Dict[str, str]],
    *,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    max_tokens: Optional[int] = 4096,
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
    if looks_like_key_name(key):
        raise NaiError(
            "Value looks like an NAI Key Name (e.g. CDP-DPRO-...), not the Access Key/token. "
            "Paste the secret token issued for chat/completions.",
            status=401,
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
    # Bearer-first on corp gateway (exact curl shape); other styles only as fallback.
    return _post_with_failover(
        "chat/completions",
        payload,
        key,
        candidates=_chat_base_candidates(),
        working=_WORKING_CHAT,
        timeout=timeout,
        auth_styles=("bearer", "both"),
    )


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
    if looks_like_key_name(key):
        raise NaiError(
            "Value looks like an NAI Key Name (e.g. CDP-DPRO-...), not the Access Key/token. "
            "Paste the secret token for /embeddings.",
            status=401,
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
    data = _post_with_failover(
        "embeddings",
        payload,
        key,
        candidates=_EMBED_BASE_CANDIDATES,
        working=_WORKING_EMBED,
        timeout=timeout,
    )
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
    corp_chat = (
        "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1/chat/completions"
    )
    if not key:
        return {"valid": None, "message": "Not provided"}
    if looks_like_key_name(key):
        return {
            "valid": False,
            "message": (
                "This looks like an NAI Key Name (label), not the secret Access Key. "
                "Paste the token used in `Authorization: Bearer <token>` for "
                f"{corp_chat}."
            ),
        }
    try:
        # Exact shape from the known-good corp curl sample (no max_tokens / stream).
        # Force corp-first candidates (never prefer beta just because embeddings work there).
        _WORKING_CHAT["base"] = "https://nai-dre.corp.p10y.ntnxdpro.com/enterpriseai/gateway/v1"
        _WORKING_CHAT["auth"] = "bearer"
        resp = chat_completions(
            [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Reply with exactly one word: hello"},
            ],
            api_key=key,
            max_tokens=None,
            timeout=60,
        )
        text = extract_message_content(resp)
        used_base = _WORKING_CHAT.get("base") or NAI_CHAT_BASE
        return {
            "valid": True,
            "message": (
                f"Reasoning OK against {used_base} "
                f"(requested {NAI_REASONING_MODEL}, "
                f"auth={_WORKING_CHAT.get('auth') or 'bearer'})"
            ),
            "sample": (text or "")[:80],
            "endpoint": f"{used_base}/chat/completions",
        }
    except NaiError as exc:
        body = f"{exc} {exc.body}".lower()
        hint = (
            f" Save the corp chat Access Key (the Bearer token that works with "
            f"`curl {corp_chat}`) into NAI Reasoning Access Key. "
            "Do not reuse the beta embeddings token here — Embedding and Reasoning "
            "use different NAI hosts/keys."
        )
        if exc.status in (401, 403):
            return {
                "valid": False,
                "message": f"Unauthorized on Reasoning endpoint: {exc}.{hint}",
                "endpoint": corp_chat,
            }
        if exc.status == 404 or "404" in body:
            return {
                "valid": False,
                "message": (
                    f"Reasoning chat endpoint failed: {exc}.{hint} "
                    "If curl to corp gateway works, re-paste that same token and "
                    "restart the backend so it uses corp-first routing."
                ),
                "endpoint": corp_chat,
            }
        return {
            "valid": None,
            "message": f"Reasoning live check failed: {exc}.{hint}",
            "endpoint": corp_chat,
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

    Embedding is validated first so a successful embed host can be preferred for
    the Reasoning/chat failover (same NAI environment).
    """
    chat_key = sanitize_api_key(api_key)
    embed_key = sanitize_api_key(embed_api_key) or chat_key
    if not chat_key and not embed_key:
        return {"valid": None, "message": "Not provided"}

    # Embed first — seeds _WORKING_EMBED for chat host preference.
    embed_result = _validate_embed_key(embed_key) if embed_key else {
        "valid": None,
        "message": "Embedding key not provided",
    }
    # If Reasoning field empty but Embedding key works, try that token for chat too.
    chat_try_key = chat_key or (embed_key if embed_result.get("valid") is True else "")
    chat_result = _validate_chat_key(chat_try_key) if chat_try_key else {
        "valid": None,
        "message": "Reasoning key not provided",
    }
    # One more attempt: if dedicated Reasoning key failed with empty-key/redirect
    # symptoms, retry chat using the known-good Embedding token on the embed host.
    if (
        chat_result.get("valid") is False
        and embed_result.get("valid") is True
        and embed_key
        and chat_key
        and embed_key != chat_key
    ):
        retry = _validate_chat_key(embed_key)
        if retry.get("valid") is True:
            chat_result = retry
            chat_result["message"] = (
                (retry.get("message") or "")
                + " (used Embedding Access Key for chat — consider saving it as Reasoning key too)"
            )

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


# ---------------------------------------------------------------------------
# Deep testcase triage via NAI reasoning model
# ---------------------------------------------------------------------------

# JIRA wiki markup template for the FAILED test ("triage-cdp-test-failure") skill.
# Keeps the mandatory section checklist from
# .cursor/skills/triage-cdp-test-failure/report-template-reference.md so the
# NAI model emits a Skill Triage Report comparable to the Cursor-bridge path.
_CDP_SKILL_SYSTEM_PROMPT = """You are a senior Nutanix regression failure analyst running the
`triage-cdp-test-failure` skill without live MCP tool access. Classify each
failure as exactly one of: `Test Issue`, `Product Issue`, `Infra Issue`, or
`Flaky / Timing`.

Reporting discipline (apply to every field):
- Treat observations (what you can see in the provided logs / tickets) as
  facts; cite the source inline (log file name, line, ticket key).
- Mark inferences with hedging ("appears to", "is consistent with", "likely").
- Say "unknown from the provided logs" when evidence is missing — never
  fabricate log lines, ticket keys, commit hashes, or file paths.
- A similar JIRA ticket is a hypothesis, not proof: validate the Triage
  Genie suggestion against the actual failure signature.

Deliverable — respond with ONE JSON object only (no markdown fence outside
JSON, no prose before/after) using exactly these keys:

  root_cause           string  evidence-backed causal chain
  classification       string  one of the four classes above
  confidence           string  High | Medium | Low
  suggested_fix        string  concrete next step for the owner
  failing_code         object  { "file": str, "line_range": str, "snippet": str }
                               (use empty strings when the failing code is
                               not identifiable; never omit the keys)
  related_components   array of strings  (e.g. ["stargate", "pithos"])
  jira_duplicates      array of strings  (e.g. ["ENG-123456"])
  tg_ticket_validation object  { "ticket": str, "verdict":
                               "Correct|Incorrect|Partial|Missing",
                               "reason": str }
  triage_report        string  FULL JIRA wiki markup report following the
                               mandatory template below (not a short summary)

`triage_report` MUST follow this JIRA wiki markup template verbatim. Include
sections 1–4, 11, 12 unconditionally; include 5–10 only when the provided
evidence supports them (omit the whole section when it does not). Use `h2.`
and `h3.` for headers, `*bold*` with single asterisks, `[text|url]` for
links, and `{code}...{code}` or `{code:python}...{code}` for code blocks.
Do NOT prefix with ```wiki or any Markdown fences — emit raw JIRA wiki
markup inside the JSON string value.

```
h2. Bug Report: [Service] [Fatal / SIGSEGV / Core / Validation] - [Brief]

h3. Test Information
* *Testcase*: <full testcase name>
* *Cluster*: <cluster or "unknown">
* *NOS Version*: <version or "unknown">
* *Build Commit*: <commit or "unknown">
* *GBN*: <gbn or "unknown">
* *Date*: <YYYY-MM-DD if visible>
* *External Storage*: <vendor / N/A>

h3. Cluster Configuration
{code:python}
<Python pformat of base_config summary if available, else write
"unknown from provided evidence">
{code}

h3. Failure Summary
<Factual observed-vs-inferred narrative with log citations. State disposition
(product bug / test bug / infra / flaky) and flag any evidence gaps.>

h3. Integrity / Test Failures   (conditional — include only when steps.log
                                 shows IO integrity / workload failures)
<time, VM, disk table in {code} blocks>

h3. Error Injection Timeline   (conditional — include only when background
                                job logs show EI events)
{code}
StartTime            EndTime               Component
{code}

h3. Fatal Error / Signal Error / Core   (conditional — include only when
                                         fatals / SIGSEGV / cores exist)
* *CVMs Affected*: <ips>
* *Service*: <service>
* *Time*: <YYYY-MM-DD HH:MM:SS>
* *Type*: Fatal | SIGSEGV | Core
{code}
<fatal / signal line>
{code}

h3. Stack Trace   (conditional — include only when stack trace available)
{code}
<stack frames>
{code}

h3. Activity Trace   (conditional — include only when traces correlate)
{code}
<activity trace lines>
{code}

h3. Log Context   (conditional — include only when ±50 lines around the
                   fatal are available)
{code}
<log context>
{code}

h3. Related Tickets
* *ENG-XXXXX*: <summary> — *Disposition*: Duplicate|Similar — *Status*:
  Open|Resolved — Fix: [Gerrit NNNN|https://nugerrit.ntnxdpro.com/c/main/+/NNNN]
  (list each candidate ticket; write "None found" when no evidence links any)

h3. Links
* [Log Bundle|<test_log_url>]
* <additional error.json / CVM / base config / test log links when visible>
```

Rules:
- Never emit the ```wiki / ```json fences outside the JSON object.
- The outermost response must parse as a single JSON object.
- Keep the triage_report in JIRA wiki markup (no Markdown ##, **, or `[text](url)`).
- When evidence is missing for a section marked (conditional), omit that
  entire section header; do not write "N/A" rows.
- Always include the top-level log URL as the first "Log Bundle" link.
"""


# JIRA wiki markup template for the SKIPPED / RDM deployment-failure skill.
_RDM_SKILL_SYSTEM_PROMPT = """You are a senior Nutanix regression analyst running the
`triage-rdm-deployment-failure` skill without live MCP tool access.
Classify the deployment failure as one of: `Foundation Issue`,
`Infra Issue`, `Product Issue`, `Config Issue`, `Plugin Issue`,
`Intermittent`, or `Other`.

Reporting discipline:
- Cite observations from the RDM failure message, deployment logs, or
  pre-fetched JIRA tickets. Hedge inferences. Say "unknown from provided
  evidence" when a link in the causal chain cannot be verified.
- A similar DIAL / ENG ticket is a hypothesis — only recommend
  `link_existing` when the ticket describes the same root cause.
- Do NOT file JIRA tickets yourself; recommend one of
  `link_existing | rerun | disable_node_and_rerun | create_jira`.

Deliverable — respond with ONE JSON object only (no markdown fences outside
JSON, no prose before/after) using exactly these keys:

  root_cause              string
  classification          string  (one of the 7 classes above)
  issue_category          string  FOUNDATION | INFRA | PRODUCT | CONFIG |
                                   PLUGIN | INTERMITTENT | OTHER
  confidence              string  High | Medium | Low
  failing_code            object  { "file": str, "line_range": str,
                                     "snippet": str } (empty strings OK)
  suggested_fix           string
  related_components      array of strings
  existing_tickets        array of objects
                           { "ticket": "DIAL-XXXX", "project": "DIAL|ENG",
                             "match": "...reason..." }
  jira_duplicates         array of ticket keys
  recommended_action      string  link_existing | create_jira | rerun |
                                   disable_node_and_rerun
  suggested_comment       string  e.g. "regx_rerun (DIAL-23079)"
  suggested_jira_project  string  DIAL or ENG
  tg_ticket_validation    object  { "ticket": str, "verdict":
                                     "Correct|Incorrect|Partial|Missing",
                                     "reason": str }
  triage_report           string  FULL triage report in JIRA wiki markup

`triage_report` MUST follow this template (keep the headings, drop
conditional sections when evidence is absent, do not output ```json or
```wiki fences inside the string):

```
h2. Skipped Test Triage: <testcase>

h3. Test Information
* *Testcase*: <full testcase name>
* *JITA Task*: [<task_id>|https://jita.eng.nutanix.com/results?task_ids=<task_id>]
* *RDM Scheduled Deployment*: [<rdm url>|<rdm url>]
* *Skip Reason*: <exception_summary / rdm_message>

h3. Deployment Failure Summary
<Observed-vs-inferred narrative; cite the RDM failure message, deployment
log lines, Foundation node names, etc. Flag evidence gaps explicitly.>

h3. Recommended Action
* *Action*: <recommended_action>
* *Suggested Comment*: {{<suggested_comment>}}
* *Suggested Project*: <DIAL|ENG>

h3. Related Tickets
* *DIAL-XXXXX* / *ENG-XXXXX*: <summary> — *Match*: same root cause / similar
  / unrelated — *Status*: Open|Resolved
  (list "None found" when no evidence links any)

h3. Links
* [RDM / Deployment Log|<rdm_url or deployment log url>]
* [JITA Task|https://jita.eng.nutanix.com/results?task_ids=<task_id>]
```

Rules:
- Return raw JIRA wiki markup inside `triage_report`; no Markdown ##, **, [text](url).
- Keep tg_ticket_validation and recommended_action consistent (e.g. a
  Correct TG ticket typically implies `link_existing`).
- Never invent ticket keys, node names, or RDM log lines.
"""


def _format_ticket_hint(ticket: Any) -> str:
    """Render a glean / jira ticket row in a compact, model-friendly form."""
    if isinstance(ticket, dict):
        key = ticket.get("ticket") or ticket.get("key") or ""
        summary = (
            ticket.get("jira_summary")
            or ticket.get("glean_title")
            or ticket.get("summary")
            or ticket.get("title")
            or ""
        )
        status = ticket.get("jira_status") or ticket.get("status") or ""
        parts = [str(key)]
        if status:
            parts.append(f"[{status}]")
        if summary:
            parts.append(f"— {summary}")
        return " ".join(p for p in parts if p).strip()
    return str(ticket)


def _format_snippet_hint(snippet: Any) -> str:
    if isinstance(snippet, dict):
        title = snippet.get("title") or snippet.get("source") or "Untitled"
        body = (snippet.get("snippet") or snippet.get("text") or "")[:220]
        url = snippet.get("url") or ""
        line = f"- {title}"
        if url:
            line += f" ({url})"
        if body:
            line += f": {body}"
        return line
    return f"- {str(snippet)[:220]}"


def _normalize_failing_code(value: Any) -> Dict[str, str]:
    """Coerce the model's `failing_code` into the UI's expected object shape."""
    if isinstance(value, dict):
        return {
            "file": str(value.get("file") or value.get("path") or "").strip(),
            "line_range": str(
                value.get("line_range")
                or value.get("lines")
                or value.get("line")
                or ""
            ).strip(),
            "snippet": str(value.get("snippet") or value.get("code") or "").strip(),
        }
    text = str(value or "").strip()
    if not text:
        return {"file": "", "line_range": "", "snippet": ""}
    # Legacy: model emitted plain text — surface it as the snippet so the UI
    # still shows something under "Failing Code".
    return {"file": "", "line_range": "", "snippet": text}


def _normalize_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_tg_validation(value: Any, fallback_ticket: str = "") -> Dict[str, str]:
    if isinstance(value, dict):
        return {
            "ticket": str(value.get("ticket") or fallback_ticket or "").strip(),
            "verdict": str(value.get("verdict") or "").strip(),
            "reason": str(value.get("reason") or "").strip(),
        }
    return {"ticket": str(fallback_ticket or ""), "verdict": "", "reason": ""}


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
    """Deep testcase analysis via NAI reasoning model (Cursor-bridge compatible shape).

    The system prompt bundles the ``triage-cdp-test-failure`` /
    ``triage-rdm-deployment-failure`` skill's mandatory report template so
    the NAI reasoning model produces a JIRA-wiki markup *Skill Triage
    Report* comparable to the Cursor SDK path (which runs the real skill
    through Sourcegraph/Glean MCP). NAI has no live MCP access, so the
    model is told to work from the provided evidence only and to flag
    missing data instead of fabricating it.
    """
    tickets = list(jira_tickets or [])
    glean = list(glean_tickets or [])
    snippets = list(glean_snippets or [])
    atype = (analysis_type or "failed").strip().lower()

    system = _RDM_SKILL_SYSTEM_PROMPT if atype == "skipped" else _CDP_SKILL_SYSTEM_PROMPT

    ticket_hints = "\n".join(f"- {_format_ticket_hint(t)}" for t in tickets[:12]) or "- none provided"
    glean_hints = "\n".join(f"- {_format_ticket_hint(t)}" for t in glean[:12]) or "- none pre-fetched"
    snippet_hints = "\n".join(_format_snippet_hint(s) for s in snippets[:6]) or "- none pre-fetched"

    user_parts = [
        f"Analysis mode: {atype}",
        f"Testcase: {testcase_name}",
        f"Failure stage: {failure_stage or 'unknown'}",
        f"Triage Genie suggested ticket: {triage_genie_ticket or 'none'}",
        f"Test log URL: {test_log_url or 'unknown'}",
    ]
    if atype == "skipped" and rdm_url:
        user_parts.append(f"RDM scheduled-deployment URL: {rdm_url}")
    user_parts.append(
        f"Exception summary:\n{(exception_summary or rdm_message or 'N/A')[:2000]}"
    )
    user_parts.append(
        f"Exception / traceback:\n```\n{(exception or rdm_message or 'N/A')[:4000]}\n```"
    )
    user_parts.append(f"Linked Jira tickets:\n{ticket_hints}")
    user_parts.append(f"Pre-fetched tickets from error-message search:\n{glean_hints}")
    user_parts.append(f"Pre-fetched Glean snippets:\n{snippet_hints}")

    if steps_log:
        user_parts.append(
            f"steps.log (truncated):\n```\n{str(steps_log)[:6000]}\n```"
        )
    if nutest_test_log:
        user_parts.append(
            f"nutest_test.log (truncated):\n```\n{str(nutest_test_log)[:6000]}\n```"
        )

    user_parts.append(
        "Return ONLY the single JSON object described in the system prompt. "
        "`triage_report` must be the FULL JIRA wiki markup report, not a "
        "paragraph summary. Omit conditional sections when the evidence does "
        "not support them, but always include Test Information, Failure "
        "Summary, Related Tickets, and Links."
    )

    content = chat_text(
        system,
        "\n\n".join(user_parts),
        model=model,
        api_key=api_key,
        username=username,
        max_tokens=6000,
        timeout=240,
    )
    parsed = parse_json_object(content)
    if not parsed:
        # Model produced free-form text instead of JSON. Keep that output
        # inside `triage_report` so the UI still shows something, and
        # surface a clear root_cause stub for the badges.
        parsed = {
            "root_cause": (content[:4000] or "NAI returned an empty analysis").strip(),
            "classification": "Unknown",
            "confidence": "Low",
            "suggested_fix": "",
            "failing_code": {},
            "related_components": [],
            "jira_duplicates": [],
            "triage_report": content.strip() if content else "",
        }

    triage_report_raw = parsed.get("triage_report")
    if isinstance(triage_report_raw, (dict, list)):
        triage_report_text = json.dumps(triage_report_raw, indent=2)
    else:
        triage_report_text = str(triage_report_raw or "").strip()
    if not triage_report_text:
        # Last-ditch: expose the raw model output so the "Skill Triage
        # Report" section is never silently empty on the NAI path.
        triage_report_text = (content or "").strip()

    analysis: Dict[str, Any] = {
        "root_cause": str(parsed.get("root_cause") or "").strip() or (content[:2000] if content else ""),
        "classification": str(parsed.get("classification") or "Unknown").strip() or "Unknown",
        "confidence": str(parsed.get("confidence") or "Medium").strip() or "Medium",
        "suggested_fix": str(parsed.get("suggested_fix") or "").strip(),
        "failing_code": _normalize_failing_code(parsed.get("failing_code")),
        "related_components": _normalize_str_list(parsed.get("related_components")),
        "jira_duplicates": _normalize_str_list(parsed.get("jira_duplicates")),
        "tg_ticket_validation": _normalize_tg_validation(
            parsed.get("tg_ticket_validation"), fallback_ticket=triage_genie_ticket
        ),
        "triage_report": triage_report_text,
        "provider": "nai",
        "model": resolve_model(model),
    }

    if atype == "skipped":
        analysis["issue_category"] = str(parsed.get("issue_category") or "").strip()
        analysis["recommended_action"] = str(parsed.get("recommended_action") or "").strip()
        analysis["suggested_comment"] = str(parsed.get("suggested_comment") or "").strip()
        analysis["suggested_jira_project"] = str(parsed.get("suggested_jira_project") or "").strip()
        existing = parsed.get("existing_tickets") or []
        if isinstance(existing, list):
            analysis["existing_tickets"] = [
                {
                    "ticket": str((t or {}).get("ticket") or "").strip(),
                    "project": str((t or {}).get("project") or "").strip(),
                    "match": str((t or {}).get("match") or "").strip(),
                }
                for t in existing
                if isinstance(t, dict)
            ]
        else:
            analysis["existing_tickets"] = []

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
