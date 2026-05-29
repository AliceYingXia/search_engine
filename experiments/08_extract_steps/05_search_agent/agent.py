"""
agent.py — Recipe search agent backed by Qwen 3.5 35B (Baseten).

Uses search_recipes.py for hybrid BM25 + dense kNN + RRF search.
The agent classifies query intent and passes category/tag to the search tool.

Usage:
    python agent.py "Which recipes sync Salesforce and NetSuite?"
    python agent.py --interactive

Env vars (or .env at project root):
    BASETEN_API_KEY
    OPENSEARCH_URL   default http://localhost:9200
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langfuse import observe
from langfuse.openai import OpenAI
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from search_recipes import search_recipes as _search_recipes, extract_steps, TOP_K_DEFAULT

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASETEN_API_KEY  = os.environ["BASETEN_API_KEY"]
AGENT_MODEL      = "Qwen/Qwen3.5-35B-A3B"
AGENT_BASE_URL   = "https://model-3ydm6e43.api.baseten.co/environments/production/sync/v1"

_os_client         = OpenSearch(os.getenv("OPENSEARCH_URL", "http://localhost:9200"))
_agent_client      = OpenAI(api_key=BASETEN_API_KEY, base_url=AGENT_BASE_URL)
_extraction_client = OpenAI(api_key=os.environ["API_KEY"], base_url=os.environ["BASE_URL"])


def _llm_call(messages: list[dict], tools: list[dict] | None = None):
    kwargs: dict = {"model": AGENT_MODEL, "max_tokens": 2048, "messages": messages}
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    return _agent_client.chat.completions.create(**kwargs)

# ---------------------------------------------------------------------------
# Search tool
# ---------------------------------------------------------------------------

SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_recipes",
        "description": (
            "Search the recipe library using a hybrid BM25 + dense kNN + RRF search. "
            "You must classify the query intent before calling this tool and pass the result as 'category'. "
            "Use this whenever the user asks to find, list, or retrieve recipes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The user's search query, passed verbatim.",
                },
                "category": {
                    "type": "string",
                    "enum": ["technical", "mixed", "business_intent"],
                    "description": (
                        "Query intent category. "
                        "'technical': mentions specific field names (snake_case) or object identifiers. "
                        "'mixed': mentions connector/product names (Salesforce, NetSuite, Slack, etc.) with a business action. "
                        "'business_intent': pure business language, no technical terms or connector names."
                    ),
                },
                "tag": {
                    "type": "string",
                    "description": (
                        "Connector tag filter (snake_case). Only set when the user explicitly requests "
                        "filtering by tag, e.g. 'with tag salesforce'. Omit otherwise."
                    ),
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default 10).",
                    "default": TOP_K_DEFAULT,
                },
            },
            "required": ["query", "category"],
        },
    },
}

SYSTEM_PROMPT = """\
You are a helpful assistant for a Workato recipe automation platform.
You help users find relevant automation recipes by calling the search_recipes tool.

Before calling search_recipes, classify the query:
- technical: mentions specific field names (snake_case like sobject_name) or object identifiers
- mixed: mentions connector/product names (Salesforce, NetSuite, Slack, etc.) with a business action
- business_intent: pure business language, no technical terms or connector names

Only set 'tag' when the user explicitly asks to filter by tag (e.g. "with tag salesforce").

When answering:
- Always call search_recipes before answering recipe-related questions.
- For each relevant recipe, show: recipe ID, connectors used, and a brief description.
- From the steps, highlight only the steps directly relevant to the user's query.
- If no good results are found, say so honestly.
- Keep answers concise unless the user asks for detail.
"""


def _run_search(query: str, category: str, top_k: int = TOP_K_DEFAULT,
                tag: str | None = None) -> tuple[list[dict], bool]:
    results, tag_matched = _search_recipes(_os_client, query, category, top_k=top_k, tag=tag)
    results = extract_steps(_extraction_client, query, results)
    return results, tag_matched


def _format_results_for_llm(results: list[dict], tag: str | None = None,
                             tag_matched: bool = True) -> str:
    header = ""
    if tag and not tag_matched:
        header = f"Note: no recipes found with tag '{tag}'; showing closest general results instead.\n\n"
    matched = [r for r in results if r.get("relevant_steps")]
    if not matched:
        return header + "No recipes found with steps relevant to this query."
    lines = []
    for i, r in enumerate(matched, 1):
        desc = (r.get("description") or "").replace("\n", " ")
        steps_text = "\n".join(f"     - {s}" for s in r["relevant_steps"])
        lines.append(
            f"{i}. recipe_uid={r['recipe_uid']}  score={r['score']:.4f}\n"
            f"   description: {desc}\n"
            f"   relevant steps:\n{steps_text}"
        )
    return header + "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

@observe()
def run_agent(user_message: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    while True:
        response = _llm_call(messages, tools=[SEARCH_TOOL])
        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []

        # No tool call — final answer
        if not tool_calls:
            return msg.content or ""

        # Execute tool calls
        messages.append(msg.model_dump())
        for tc in tool_calls:
            args = json.loads(tc.function.arguments)
            query    = args["query"]
            category = args["category"]
            tag      = args.get("tag")
            top_k    = args.get("top_k", TOP_K_DEFAULT)

            print(f"[tool] search_recipes({query!r}, category={category!r}, tag={tag!r}, top_k={top_k})", flush=True)
            results, tag_matched = _run_search(query, category, top_k=top_k, tag=tag)
            tool_result = _format_results_for_llm(results, tag=tag, tag_matched=tag_matched)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })


def interactive_loop() -> None:
    print("Recipe search agent (type 'exit' to quit)\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input or user_input.lower() in ("exit", "quit"):
            break
        answer = run_agent(user_input)
        print(f"\nAgent: {answer}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Single query to run")
    parser.add_argument("--interactive", "-i", action="store_true")
    args = parser.parse_args()

    if args.interactive:
        interactive_loop()
    elif args.query:
        answer = run_agent(args.query)
        print(f"\nAgent: {answer}")
    else:
        parser.error("Provide a query or use --interactive")


if __name__ == "__main__":
    main()
