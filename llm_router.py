"""
ProfitAgent LLM Router
Handles tool calling loop for both OpenAI and Anthropic Claude.
Sends the user's question + available tools to their chosen LLM,
executes the tools it selects, then gets the final structured answer.
"""

import json
import re
from typing import Any
from tools.analysis import TOOL_DESCRIPTIONS, run_tool

# ── SYSTEM PROMPT ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are ProfitAgent, an expert ecommerce profit intelligence analyst.
You have access to a set of statistical analysis tools that run on the user's real store data.

RULES:
1. Always call at least one analysis tool before answering — never guess from data alone.
2. Call multiple tools when the question requires it (e.g. "improve profitability" needs ROAS + margins + retention).
3. After receiving tool results, write a clear, specific, data-driven answer using the actual numbers.
4. Always end with 3-5 prioritised action recommendations with expected impact.
5. Be direct and specific — use the actual £ figures and percentages from the tool results.
6. Do not pad with generic advice. Every sentence must reference their actual data.

OUTPUT FORMAT — you MUST return a single valid JSON object with this exact structure:
{
  "question": "<the user's original question>",
  "tools_used": ["<tool1>", "<tool2>"],
  "summary": "<2-3 sentence executive summary with key numbers>",
  "findings": [
    {
      "title": "<finding headline>",
      "detail": "<specific explanation with numbers>",
      "severity": "critical|high|medium|low"
    }
  ],
  "recommendations": [
    {
      "priority": 1,
      "action": "<specific action>",
      "detail": "<why and how>",
      "expected_impact": "<quantified outcome>",
      "timeframe": "<This week|This month|Next quarter>"
    }
  ],
  "answer": "<full conversational answer, 150-300 words, referencing their actual numbers>",
  "confidence": "high|medium|low"
}

Return ONLY the JSON object. No markdown, no preamble, no explanation outside the JSON."""


# ── OPENAI TOOL CALLING ───────────────────────────────────────────────────────

def _openai_tools_format():
    """Convert tool descriptions to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }
        }
        for t in TOOL_DESCRIPTIONS
    ]


async def call_openai(question: str, store_data: dict, api_key: str, model: str) -> dict:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Store data: {json.dumps(store_data)}\n\nQuestion: {question}"}
    ]

    tools_used = []
    tool_results_summary = []

    # Tool calling loop — LLM calls tools until it's ready to answer
    for iteration in range(5):  # max 5 tool calls
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            tools=_openai_tools_format(),
            tool_choice="auto",
            max_tokens=4000,
            temperature=0.2
        )

        message = response.choices[0].message

        # No more tool calls — get the final answer
        if not message.tool_calls:
            final_text = message.content or ""
            return _parse_final_response(final_text, question, tools_used)

        # Execute each tool the LLM requested
        messages.append({"role": "assistant", "content": message.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in message.tool_calls
        ]})

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            tools_used.append(tool_name)
            result = run_tool(tool_name, store_data)
            tool_results_summary.append(result)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result)
            })

    return {"error": "Max tool iterations reached", "question": question}


# ── CLAUDE TOOL CALLING ───────────────────────────────────────────────────────

def _claude_tools_format():
    """Convert tool descriptions to Anthropic tool format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        for t in TOOL_DESCRIPTIONS
    ]


async def call_claude(question: str, store_data: dict, api_key: str, model: str) -> dict:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)

    messages = [
        {"role": "user", "content": f"Store data: {json.dumps(store_data)}\n\nQuestion: {question}"}
    ]

    tools_used = []

    for iteration in range(5):
        response = await client.messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=_claude_tools_format(),
            messages=messages,
            temperature=0.2
        )

        # Check if we're done
        if response.stop_reason == "end_turn":
            # Extract text from content blocks
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            return _parse_final_response(final_text, question, tools_used)

        # Process tool use blocks
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            final_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    final_text += block.text
            return _parse_final_response(final_text, question, tools_used)

        # Add assistant message with tool use
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools and add results
        tool_results = []
        for tool_use in tool_uses:
            tool_name = tool_use.name
            tools_used.append(tool_name)
            result = run_tool(tool_name, store_data)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(result)
            })

        messages.append({"role": "user", "content": tool_results})

    return {"error": "Max tool iterations reached", "question": question}


# ── RESPONSE PARSER ───────────────────────────────────────────────────────────

def _parse_final_response(text: str, question: str, tools_used: list) -> dict:
    """Parse the LLM's JSON response, with fallback for malformed output."""
    if not text:
        return _fallback_response(question, tools_used, "Empty response from LLM")

    # Strip markdown fences if present
    clean = re.sub(r"```(?:json)?", "", text).strip()
    # Find first { to last }
    start = clean.find("{")
    end = clean.rfind("}") + 1
    if start == -1 or end == 0:
        return _fallback_response(question, tools_used, text)

    json_str = clean[start:end]
    try:
        parsed = json.loads(json_str)
        # Ensure tools_used is populated even if LLM forgot to include it
        if not parsed.get("tools_used"):
            parsed["tools_used"] = tools_used
        return parsed
    except json.JSONDecodeError:
        return _fallback_response(question, tools_used, text)


def _fallback_response(question: str, tools_used: list, raw_text: str) -> dict:
    """Return a structured response even if JSON parsing fails."""
    return {
        "question": question,
        "tools_used": tools_used,
        "summary": "Analysis complete — see full answer below.",
        "findings": [],
        "recommendations": [],
        "answer": raw_text[:2000] if raw_text else "Unable to generate response.",
        "confidence": "low",
        "_parse_error": True
    }


# ── MAIN ENTRY POINT ──────────────────────────────────────────────────────────

async def run_analysis(
    question: str,
    store_data: dict,
    provider: str,
    api_key: str,
    model: str
) -> dict:
    """
    Main entry point. Routes to the correct LLM provider.
    provider: "openai" | "anthropic"
    """
    provider = provider.lower().strip()

    if provider == "openai":
        return await call_openai(question, store_data, api_key, model)
    elif provider in ("anthropic", "claude"):
        return await call_claude(question, store_data, api_key, model)
    else:
        return {
            "error": f"Unknown provider: {provider}. Use 'openai' or 'anthropic'.",
            "question": question
        }
