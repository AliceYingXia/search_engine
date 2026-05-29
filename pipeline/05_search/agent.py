"""
agent.py — Recipe search agent backed by Qwen 3.5 35B (Baseten).

Uses search_recipes.py for hybrid BM25 + dense kNN + RRF search.
The agent emits (query, dense_query, tag); routing is decided server-side
from the dictionary filter count.

Usage:
    python agent.py "Which recipes sync Salesforce and NetSuite?"
    python agent.py --interactive

Env vars (or .env at project root):
    BASETEN_API_KEY
    OPENSEARCH_URL   default http://localhost:9200
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langfuse import observe
from langfuse.openai import OpenAI
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent.parent / ".env")

from search_recipes import search_recipes as _search_recipes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASETEN_API_KEY  = os.environ["BASETEN_API_KEY"]
AGENT_MODEL      = "Qwen/Qwen3.5-35B-A3B"
AGENT_BASE_URL   = "https://model-3ydm6e43.api.baseten.co/environments/production/sync/v1"

_os_client    = OpenSearch(os.getenv("OPENSEARCH_URL", "http://localhost:9200"))
_agent_client = OpenAI(api_key=BASETEN_API_KEY, base_url=AGENT_BASE_URL)


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
        "name": "hybrid_search",
        "description": (
            "Search the recipe library using a hybrid BM25 + dense kNN + RRF search. "
            "Use this whenever the user asks to find, list, or retrieve recipes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Keyword-focused query for BM25 search. "
                        "Strip filler/conversational words ('please', 'can you', 'I want to', 'show me', 'find me', 'which', 'that') "
                        "and vague intent words ('help', 'related', 'something', 'any', 'all'). "
                        "Keep connector names, object/field names, action verbs (sync, create, update, send, trigger), "
                        "and snake_case identifiers as-is. "
                        "Note: high-frequency corpus boilerplate ('automation', 'workato', 'recipe', 'function', 'triggered', "
                        "'operations', 'when') is filtered server-side by the index analyzer — you do NOT need to strip it. "
                        "Example: 'Can you find me recipes that sync Salesforce leads?' → 'sync Salesforce leads'."
                    ),
                },
                "dense_query": {
                    "type": "string",
                    "description": (
                        "Semantic-rich query for dense kNN search. ALWAYS provide this — the server decides "
                        "whether dense is actually used. "
                        "Phrase as a clean noun-phrase description of the information need ('for ...', 'between ...', 'that handle ...'). "
                        "Unlike `query`, KEEP meaning-bearing context (prepositions, articles, modifiers) — embeddings need "
                        "surrounding semantics to anchor. "
                        "Strip corpus-stopwords manually (the embedding does NOT pre-filter them, unlike BM25): "
                        "'automation', 'workato', 'recipe(s)', 'function', 'triggered', 'operations', 'when'. "
                        "DO NOT invent or append words that weren't in the user's input — never add 'automation', 'recipes', "
                        "'workflow', or similar generic padding. If the user's input is already a clean noun phrase, pass it "
                        "through (lower-cased, light pluralization OK). "
                        "Examples:\n"
                        "  'Can you find me recipes for customer support?'     → 'for customer support'\n"
                        "  'recipes that sync between salesforce and netsuite' → 'sync data between Salesforce and NetSuite'\n"
                        "  'slack channel'                                     → 'slack channels'\n"
                        "  NOT: 'slack channel' → 'Slack channel automation recipes' (forbidden — pads with corpus boilerplate)."
                    ),
                },
                "tag": {
                    "type": "string",
                    "description": (
                        "Connector tag filter. Only set when the user explicitly requests "
                        "filtering by tag, e.g. 'with tag salesforce'. Omit otherwise."
                    ),
                },
            },
            "required": ["query", "dense_query"],
        },
    },
}

SYSTEM_PROMPT = """\
You are a helpful assistant for a Workato recipe automation platform.
You help users find relevant automation recipes by calling the hybrid_search tool.

Before filling in any tool parameters, expand any nicknames and abbreviations in the user's
message to the canonical form used in the corpus. This rewrite happens upstream of parameter
generation, so the expanded form is used throughout.

Connector shorthand:
  SF / SFDC       → Salesforce
  NS              → NetSuite
  HS              → HubSpot
  MS Teams / MST  → Microsoft Teams
  O365 / M365     → Microsoft 365
  GH              → GitHub
  GS              → Google Sheets   (Google Slides only if context mentions slides/presentation)
  GDrive          → Google Drive
  GCal            → Google Calendar
  BQ / BigQ       → BigQuery
  SNOW            → ServiceNow
  ZD              → Zendesk
  DBX             → Dropbox
  S3              → Amazon S3
  AAD             → Azure Active Directory
  MC              → Mailchimp       (Marketing Cloud only if context mentions Salesforce/email marketing)

Business-process shorthand → spell out the phrase AND add the likely connectors:
  Q2C / QTC       → "quote to cash" + Salesforce + NetSuite
  O2C             → "order to cash" + Salesforce + NetSuite
  P2P             → "procure to pay" + NetSuite + Coupa
  L2C             → "lead to cash" + Salesforce
  R2R             → "record to report" + NetSuite

Leave generic category words (CRM, ERP) unchanged unless context disambiguates them.

Examples:
  "SF NS sync"             → "Salesforce NetSuite sync"
  "SFDC opp to NS invoice" → "Salesforce opportunity to NetSuite invoice"
  "Q2C automation"         → "quote to cash Salesforce NetSuite"
  "post to MS Teams"       → "post to Microsoft Teams"

When answering:
- Always call hybrid_search before answering recipe-related questions.
- The tool returns a ranked list. The top 20 results carry `recipe_uid`, `connectors`,
  and `description`; any results beyond rank 20 carry only `recipe_uid`.
- Return the final answer as a list mirroring that shape:
    * For each of the top 20 results, show: recipe_id, connectors, description.
    * For each remaining result (rank > 20), show: recipe_id only.
- Do not add scores or other fields per item.
- If no good results are found, say so honestly.
- Keep any surrounding prose concise unless the user asks for detail.
"""


def _save_results_csv(query: str, results: list[dict],
                       requested_tag: str | None, tag_exists: bool) -> None:
    out_dir = Path(__file__).parent / "search_results"
    out_dir.mkdir(exist_ok=True)
    safe_query = "".join(c if c.isalnum() or c in " _-" else "_" for c in query).strip()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{safe_query}_{timestamp}.csv"
    fieldnames = [
        "query", "requested_tag", "tag_exists",
        "recipe_uid", "score", "score_type",
        "description", "connectors",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow({
                **r,
                "query": query,
                "requested_tag": requested_tag or "",
                "tag_exists": tag_exists,
            })
    print(f"[search] results saved to {path}", flush=True)


def _run_search(query: str, dense_query: str,
                tag: str | None = None) -> tuple[list[dict], bool]:
    results, tag_matched = _search_recipes(
        _os_client, query, dense_query=dense_query, tag=tag,
    )
    # tag_exists is meaningful only when a tag was requested; True otherwise.
    tag_exists = tag_matched if tag else True
    _save_results_csv(query, results, requested_tag=tag, tag_exists=tag_exists)
    return results, tag_matched


def _format_results_for_llm(results: list[dict], tag: str | None = None,
                             tag_matched: bool = True) -> str:
    header = ""
    if tag and not tag_matched:
        header = f"Note: no recipes found with tag '{tag}'; showing closest general results instead.\n\n"
    if not results:
        return header + "No recipes found."
    lines = []
    for i, r in enumerate(results, 1):
        if "description" in r:
            desc = (r.get("description") or "").replace("\n", " ")
            connectors = r.get("connectors") or []
            connectors_str = ", ".join(connectors) if connectors else "(none)"
            lines.append(
                f"{i}. recipe_uid={r['recipe_uid']}  score={r['score']:.4f}\n"
                f"   connectors: {connectors_str}\n"
                f"   description: {desc}"
            )
        else:
            lines.append(f"{i}. recipe_uid={r['recipe_uid']}  score={r['score']:.4f}")
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
            query       = args["query"]
            dense_query = args["dense_query"]
            tag         = args.get("tag")

            print(
                f"[tool] hybrid_search(query={query!r}, "
                f"dense_query={dense_query!r}, tag={tag!r})",
                flush=True,
            )
            results, tag_matched = _run_search(query, dense_query=dense_query, tag=tag)
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
