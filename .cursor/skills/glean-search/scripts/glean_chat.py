#!/usr/bin/env python3
"""
Refrance - https://github.com/nutanix-scratch/glean-internal-search-skill/tree/default

Programmatic access to Glean's chat API using session cookies.

The okta-saml-hosted-login-session-store cookie is resolved in this order
(first source wins):
  1. Command-line argument (--okta-session-store)
  2. Environment variable (OKTA_SAML_HOSTED_LOGIN_SESSION_STORE)
  3. A .env file in the working directory

Usage:
    # Single question (thinking mode, the default)
    python glean_chat.py "What is Glean?"

    # Fast mode (no chain-of-thought reasoning)
    python glean_chat.py --mode fast "What is Glean?"

    # Deep research (detailed report, can take minutes)
    python glean_chat.py --mode deep_research "Analyze Nutanix AHV GPU support"

    # Interactive REPL (type a mode name to switch, e.g. 'fast', 'thinking')
    python glean_chat.py

    # List recent chats
    python glean_chat.py --list-chats

    # Resume a chat
    python glean_chat.py --chat-id <id> "follow-up question"

    # Explicit cookie on the command line
    python glean_chat.py --okta-session-store "TOKEN" "What is Glean?"
"""

from __future__ import annotations

import argparse
import enum
import json
import os
import sys
import textwrap
from collections.abc import Generator, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

requests = __import__("requests")

GLEAN_BE_HOST = "nutanix-be.glean.com"
GLEAN_BASE_URL = f"https://{GLEAN_BE_HOST}"
GLEAN_APP_ORIGIN = "https://app.glean.com"

COOKIE_ENV_MAP: dict[str, str] = {
    "okta-saml-hosted-login-session-store": "OKTA_SAML_HOSTED_LOGIN_SESSION_STORE",
}
REQUEST_TIMEOUT_SECONDS = 600


class AgentMode(enum.Enum):
    """Chat agent modes available in the Glean web app.

    Each mode maps to a value sent in ``agentConfig.agent`` in the chat API
    request payload.  The wire values were reverse-engineered from the Glean
    frontend webpack bundle and confirmed against the live API.

    Attributes
    ----------
    THINKING : Agentic reasoning loop.  Spends more time reasoning and can
        invoke tools (enterprise search, web search, etc.) over multiple
        iterations.  Best for complex or multi-step questions.  This is the
        default mode in the Glean web UI.
    FAST : Quick, single-pass response without the agentic reasoning loop.
        Best for simple, everyday questions where speed matters.
    AUTO : Lets Glean decide — fast answers for simple questions, deeper
        analysis for complex ones.
    DEEP_RESEARCH : Generates a detailed, long-form report.  Can take up to
        30 minutes.  Uses both company knowledge and web sources.
    DEFAULT : Server-side default (currently equivalent to THINKING/ADVANCED).
    UNIVERSAL : General-purpose agent with agentic reasoning.  Behaves
        similarly to THINKING but may differ in model routing.
    GPT_NO_WEB : Agentic reasoning without web search — only company
        knowledge is used.
    """

    THINKING = "ADVANCED"
    FAST = "FAST"
    AUTO = "AUTO"
    DEEP_RESEARCH = "DEEP_RESEARCH"
    DEFAULT = "DEFAULT"
    UNIVERSAL = "UNIVERSAL"
    GPT_NO_WEB = "GPT_NO_WEB"

    @classmethod
    def from_str(cls, name: str) -> "AgentMode":
        """Resolve a case-insensitive name to an AgentMode member.

        Args:
          name(str): Mode name supplied by the caller.

        Returns:
          AgentMode: Matching enum member.

        Raises:
          ValueError: If the provided mode is unknown.
        """
        try:
            return cls[name.upper()]
        except KeyError:
            valid = ", ".join(m.name.lower() for m in cls)
            raise ValueError(f"Unknown mode {name!r}. Choose from: {valid}") from None


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file.

    Args:
      path(Path): Path to the env file.

    Returns:
      dict[str, str]: Parsed env keys and values.
    """
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key:
            env[key.strip()] = value.strip()
    return env


def load_cookies(
    *,
    cli_cookies: dict[str, str] | None = None,
    env_file: Path = Path("~/.env").expanduser(),
) -> dict[str, str]:
    """Resolve Glean session cookies from multiple sources.

    Returns:
      dict[str, str]: Cookie mapping ready for requests.

    Raises:
      RuntimeError: Raised when required session cookie is missing.
    """
    file_env = _parse_env_file(env_file)
    cookies: dict[str, str] = {}

    for cookie_name, env_key in COOKIE_ENV_MAP.items():
        value = (
            (cli_cookies or {}).get(cookie_name)
            or os.environ.get(env_key)
            or file_env.get(env_key)
            or ""
        )
        if value:
            cookies[cookie_name] = value

    if not cookies.get("okta-saml-hosted-login-session-store"):
        raise RuntimeError(
            "No okta-saml-hosted-login-session-store cookie found. Provide it via:\n"
            "  - CLI:  --okta-session-store TOKEN\n"
            "  - Env:  export OKTA_SAML_HOSTED_LOGIN_SESSION_STORE=TOKEN\n"
            "  - File: add OKTA_SAML_HOSTED_LOGIN_SESSION_STORE=TOKEN to .env"
        )
    return cookies


@dataclass(slots=True)
class ChatMessage:
    author: str  # "USER" or "GLEAN_AI"
    text: str
    message_id: str | None = None
    message_type: str = "CONTENT"
    citations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ChatResponse:
    messages: list[ChatMessage]
    chat_id: str | None = None
    follow_ups: list[str] = field(default_factory=list)


class GleanChat:
    """Client for the Glean chat API using session-cookie authentication."""

    def __init__(
        self,
        cookies: dict[str, str],
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ):
        """Initialize a chat client.

        Args:
          cookies(dict[str, str]): Auth cookies for the Glean API.
          timeout(int): Request timeout in seconds.
        """
        self.cookies = cookies
        self.timeout = timeout
        self.session = requests.Session()
        self.session.cookies.update(self.cookies)
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Origin": GLEAN_APP_ORIGIN,
                "Referer": f"{GLEAN_APP_ORIGIN}/",
            }
        )

    def chat(
        self,
        message: str,
        chat_id: str | None = None,
        save: bool = False,
        mode: AgentMode = AgentMode.THINKING,
    ) -> ChatResponse:
        """Send a message and return the non-streaming response.

        Args:
          message(str): Prompt text for the assistant.
          chat_id(str | None): Existing chat id to continue.
          save(bool): Whether to save chat in Glean.
          mode(AgentMode): Agent mode used for the request.

        Returns:
          ChatResponse: Parsed chat response payload.
        """
        payload = self._build_payload(message, chat_id, save, mode)
        resp = self._post("chat", payload)
        return self._parse_response(resp.json())

    def chat_stream(
        self,
        message: str,
        chat_id: str | None = None,
        save: bool = False,
        mode: AgentMode = AgentMode.THINKING,
    ) -> Generator[ChatResponse, None, None]:
        """Send a message and yield incremental streaming responses.

        Args:
          message(str): Prompt text for the assistant.
          chat_id(str | None): Existing chat id to continue.
          save(bool): Whether to save chat in Glean.
          mode(AgentMode): Agent mode used for the request.

        Yields:
          ChatResponse: Parsed streaming chat chunks.
        """
        payload = self._build_payload(message, chat_id, save, mode)
        payload["stream"] = True
        with self.session.post(
            f"{GLEAN_BASE_URL}/api/v1/chat",
            json=payload,
            stream=True,
            timeout=self.timeout,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    yield self._parse_response(chunk)
                except json.JSONDecodeError:
                    continue

    def list_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent chat sessions.

        ``updated`` is whatever Glean returns in ``updateTime`` — empirically a
        unix timestamp (int), but typed as ``Any`` to be tolerant of schema
        drift. Callers that need a stable format should convert at the edge.

        Args:
          limit(int): Maximum number of chats to return.

        Returns:
          list[dict[str, Any]]: Summary dictionaries for saved chats.
        """
        resp = self._post("listchats", {})
        results = resp.json().get("chatResults", [])
        return [
            {
                "id": r["chat"]["id"],
                "name": r["chat"].get("name", "(untitled)"),
                "updated": r["chat"].get("updateTime"),
            }
            for r in results[:limit]
        ]

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        """Retrieve the full history of a saved chat.

        Note: the request field is ``id``, not ``chatId``. Using ``chatId``
        causes the API to return ``400 "Not enough user permissions"``.

        Args:
          chat_id(str): Saved chat identifier.

        Returns:
          dict[str, Any]: Raw chat payload from the API.
        """
        resp = self._post("getchat", {"id": chat_id})
        return resp.json()

    @staticmethod
    def _build_payload(
        message: str,
        chat_id: str | None,
        save: bool,
        mode: AgentMode = AgentMode.THINKING,
    ) -> dict[str, Any]:
        """Build the request payload for chat API calls.

        Args:
          message(str): Prompt text for the assistant.
          chat_id(str | None): Existing chat id to continue.
          save(bool): Whether to save chat in Glean.
          mode(AgentMode): Agent mode used for the request.

        Returns:
          dict[str, Any]: Payload dictionary for the API.
        """
        payload: dict[str, Any] = {
            "messages": [
                {"author": "USER", "fragments": [{"text": message}]},
            ],
            "agentConfig": {"agent": mode.value},
        }
        if chat_id:
            payload["chatId"] = chat_id
        if save:
            payload["saveChat"] = True
        return payload

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> ChatResponse:
        """Parse raw API JSON into strongly-typed response objects.

        Args:
          data(dict[str, Any]): Raw response dictionary from the API.

        Returns:
          ChatResponse: Parsed chat response object.
        """
        messages: list[ChatMessage] = []
        for m in data.get("messages", []):
            text_parts: list[str] = []
            citations: list[dict[str, Any]] = []
            for frag in m.get("fragments", []):
                if "text" in frag:
                    text_parts.append(frag["text"])
                if "citation" in frag:
                    citations.append(frag["citation"])
            messages.append(
                ChatMessage(
                    author=m.get("author", ""),
                    text="".join(text_parts),
                    message_id=m.get("messageId") or m.get("id"),
                    message_type=m.get("messageType", ""),
                    citations=citations,
                )
            )
        return ChatResponse(
            messages=messages,
            chat_id=data.get("chatId"),
            follow_ups=data.get("followUpPrompts", []),
        )

    def _post(self, endpoint: str, payload: dict[str, Any]) -> requests.Response:
        """Send a POST request to a Glean API endpoint.

        Args:
          endpoint(str): Endpoint path relative to ``/api/v1``.
          payload(dict[str, Any]): JSON payload for the request.

        Returns:
          requests.Response: HTTP response object.
        """
        resp = self.session.post(
            f"{GLEAN_BASE_URL}/api/v1/{endpoint}",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp


def _print_response(resp: ChatResponse) -> None:
    """Print a full response in human-readable format.

    Args:
      resp(ChatResponse): Parsed chat response to print.
    """
    for msg in resp.messages:
        if msg.message_type == "CONTENT" and msg.text:
            print(f"\n{msg.text}")
            if msg.citations:
                print("\nSources:")
                for c in msg.citations:
                    doc = c.get("sourceDocument", {})
                    print(f"  - {doc.get('title', '?')}: {doc.get('url', '')}")
    if resp.follow_ups:
        print("\nSuggested follow-ups:")
        for i, q in enumerate(resp.follow_ups, 1):
            print(f"  {i}. {q}")


def _content_deltas(
    chunks: Iterable[ChatResponse],
) -> Generator[tuple[ChatResponse, str], None, None]:
    """Yield text deltas from potentially cumulative streaming chunks.

    Args:
      chunks(Iterable[ChatResponse]): Streaming responses from the API.

    Yields:
      tuple[ChatResponse, str]: Tuple of chunk and new text delta.
    """
    prior_text: dict[str, str] = {}
    for chunk in chunks:
        for index, msg in enumerate(chunk.messages):
            if msg.message_type != "CONTENT" or not msg.text:
                continue
            key = msg.message_id or f"{chunk.chat_id or 'live'}:{msg.author}:{index}"
            previous = prior_text.get(key, "")
            if msg.text.startswith(previous):
                delta = msg.text[len(previous):]
                current = msg.text
            else:
                delta = msg.text
                current = previous + msg.text
            prior_text[key] = current
            if delta:
                yield chunk, delta


def _interactive(
    client: GleanChat,
    chat_id: str | None = None,
    mode: AgentMode = AgentMode.THINKING,
) -> None:
    """Run the interactive terminal chat loop.

    Args:
      client(GleanChat): Chat client used to send requests.
      chat_id(str | None): Optional existing chat id to continue.
      mode(AgentMode): Starting agent mode for interactions.
    """
    mode_names = [m.name.lower() for m in AgentMode]
    print(f"Glean Chat [mode={mode.name.lower()}]")
    print(f"  Commands: quit, new, {', '.join(mode_names)}\n")
    while True:
        try:
            question = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("quit", "exit", "q"):
            break
        if question.lower() == "new":
            chat_id = None
            print("(starting new conversation)")
            continue
        try:
            mode = AgentMode.from_str(question)
            print(f"(switched to {mode.name.lower()} mode)")
            continue
        except ValueError:
            pass

        print("\nGlean> ", end="", flush=True)
        for chunk, delta in _content_deltas(
            client.chat_stream(question, chat_id=chat_id, mode=mode)
        ):
            chat_id = chunk.chat_id or chat_id
            print(delta, end="", flush=True)
        print("\n")


def main() -> None:
    """Parse arguments and run one-shot or interactive chat.

    Returns:
      None
    """
    parser = argparse.ArgumentParser(
        description="Programmatic Glean chat via session cookies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            cookie resolution (first source wins):
              1. --okta-session-store CLI flag
              2. OKTA_SAML_HOSTED_LOGIN_SESSION_STORE env var
              3. .env file (KEY=VALUE, one per line)

            examples:
              %(prog)s "What is Glean?"                  # thinking (default)
              %(prog)s --mode fast "What is Glean?"      # fast, no reasoning
              %(prog)s --mode deep_research "Analyze X"  # long-form report
              %(prog)s --mode auto "Some question"       # let Glean decide
              %(prog)s --list-chats
              %(prog)s --chat-id abc123 "tell me more"
              %(prog)s                                   # interactive REPL
              %(prog)s --okta-session-store TOK "Hi"     # explicit cookie
        """),
    )
    parser.add_argument("question", nargs="?", help="question to ask (omit for REPL)")
    parser.add_argument("--chat-id", help="continue an existing chat")
    parser.add_argument(
        "--list-chats", action="store_true", help="list recent chat sessions"
    )
    parser.add_argument(
        "--get-chat", metavar="ID", help="print full history of a chat"
    )
    parser.add_argument("--save", action="store_true", help="save the chat in Glean")
    parser.add_argument(
        "--mode",
        type=AgentMode.from_str,
        default=AgentMode.THINKING,
        metavar="MODE",
        help=(
            "agent mode (default: thinking). Available: "
            + ", ".join(m.name.lower() for m in AgentMode)
        ),
    )
    parser.add_argument("--no-stream", action="store_true", help="disable streaming")
    parser.add_argument(
        "--json", action="store_true", help="output raw JSON instead of text"
    )
    parser.add_argument(
        "--okta-session-store",
        metavar="TOKEN",
        help="okta-saml-hosted-login-session-store cookie value (overrides env / .env)",
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        default="~/.env",
        help="path to .env file (default: ~/.env)",
    )
    args = parser.parse_args()

    cli_cookies: dict[str, str] = {}
    if args.okta_session_store:
        cli_cookies["okta-saml-hosted-login-session-store"] = args.okta_session_store

    try:
        cookies = load_cookies(
          cli_cookies=cli_cookies,
          env_file=Path(args.env_file).expanduser(),
        )
        client = GleanChat(cookies=cookies)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.list_chats:
            chats = client.list_chats()
            if args.json:
                print(json.dumps(chats, indent=2))
            else:
                for c in chats:
                    print(f"  {c['id'][:12]}…  {c['name']}")
            return

        if args.get_chat:
            data = client.get_chat(args.get_chat)
            print(json.dumps(data, indent=2))
            return

        if not args.question:
            _interactive(client, chat_id=args.chat_id, mode=args.mode)
            return

        if args.no_stream:
            resp = client.chat(
                args.question,
                chat_id=args.chat_id,
                save=args.save,
                mode=args.mode,
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "chat_id": resp.chat_id,
                            "messages": [
                                {
                                    "author": m.author,
                                    "text": m.text,
                                    "type": m.message_type,
                                }
                                for m in resp.messages
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                _print_response(resp)
        else:
            chat_id = args.chat_id
            for chunk, delta in _content_deltas(
                client.chat_stream(
                    args.question,
                    chat_id=chat_id,
                    save=args.save,
                    mode=args.mode,
                )
            ):
                chat_id = chunk.chat_id or chat_id
                if args.json:
                    print(json.dumps({"chat_id": chat_id, "text": delta}))
                else:
                    print(delta, end="", flush=True)
            if not args.json:
                print()
    except requests.RequestException as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
