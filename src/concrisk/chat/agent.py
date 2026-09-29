import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast

import anthropic
from sqlalchemy.orm import Session

from concrisk.chat.prompts import SYSTEM_PROMPT
from concrisk.chat.tools import TOOL_SCHEMAS, execute_tool
from concrisk.config import get_settings
from concrisk.db.session import SessionLocal

logger = logging.getLogger(__name__)

MAX_ROUNDS = 6
MAX_TOKENS = 2048


@dataclass(frozen=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    result: dict[str, Any]


@dataclass
class ChatResult:
    text: str
    trace: list[ToolCall] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    truncated: bool = False


def _json_default(obj: Any) -> Any:
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"cannot serialize {type(obj).__name__}")


def _extract_text(content_blocks: list[Any]) -> str:
    parts: list[str] = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n\n".join(parts).strip()


def _serialize_assistant_content(content_blocks: list[Any]) -> list[dict[str, Any]]:
    """Convert Anthropic response content blocks into a JSON-shape messages entry."""
    out: list[dict[str, Any]] = []
    for block in content_blocks:
        if block.type == "text":
            out.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            out.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
    return out


def run_chat(
    user_message: str,
    history: list[dict[str, Any]] | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> ChatResult:
    """Run one user turn through the Anthropic agent loop.

    Up to `MAX_ROUNDS` tool-call rounds per SPEC §10. Stops early on
    end_turn. `history` is the messages list returned by a previous
    ChatResult; pass None for a fresh conversation. `session_factory`
    yields the SQLAlchemy sessions tools need; defaults to SessionLocal.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        return ChatResult(
            text=(
                "ANTHROPIC_API_KEY is not configured. Set it in `.env` and "
                "restart the dashboard."
            ),
        )

    factory = session_factory or SessionLocal
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": user_message})
    trace: list[ToolCall] = []

    content: list[Any] = []
    for round_idx in range(MAX_ROUNDS):
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=cast(Any, TOOL_SCHEMAS),
            messages=cast(Any, messages),
        )
        content = list(resp.content)
        messages.append(
            {"role": "assistant", "content": _serialize_assistant_content(content)}
        )

        tool_uses = [b for b in content if b.type == "tool_use"]
        if resp.stop_reason == "end_turn" or not tool_uses:
            return ChatResult(
                text=_extract_text(content),
                trace=trace,
                messages=messages,
                rounds=round_idx + 1,
            )

        tool_results: list[dict[str, Any]] = []
        with factory() as session:
            for tu in tool_uses:
                tu_input = cast(dict[str, Any], tu.input)
                logger.info("tool call: %s(%s)", tu.name, tu_input)
                result = execute_tool(tu.name, tu_input, session)
                trace.append(ToolCall(name=tu.name, input=tu_input, result=result))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result, default=_json_default),
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return ChatResult(
        text=_extract_text(content) + "\n\n(hit tool-call round limit — answer may be incomplete)",
        trace=trace,
        messages=messages,
        rounds=MAX_ROUNDS,
        truncated=True,
    )
