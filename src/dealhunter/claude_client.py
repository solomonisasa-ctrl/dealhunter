"""
Thin wrapper around the Anthropic SDK for getting reliable structured JSON
back from Claude: we force a single tool call whose input_schema is the
shape we want, rather than asking Claude to "return JSON" in prose and
parsing it ourselves.
"""
from __future__ import annotations

from typing import Any

import anthropic


def call_structured(
    client: anthropic.Anthropic,
    model: str,
    system: str,
    user_content: str | list[dict[str, Any]],
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    max_tokens: int = 1500,
) -> dict[str, Any]:
    """Call Claude and force it to respond via a single tool call, returning
    that tool call's input dict. Raises RuntimeError if Claude doesn't call
    the tool (shouldn't happen with tool_choice=forced, but defensive)."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        tools=[
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": input_schema,
            }
        ],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return block.input
    raise RuntimeError(f"Claude did not call the expected tool '{tool_name}'")
