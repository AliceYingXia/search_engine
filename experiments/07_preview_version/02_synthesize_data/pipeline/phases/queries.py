"""Phase 1 — Query Generation.

For each seed recipe (pre-selected by PrepareCorpus), calls the LLM with
the style's system_prompt to generate one natural-language search query.

Prints all generated queries for human review before proceeding to Phase 2.

Requires: recipes_for_pgvector.csv (run the `prepare` phase first).
"""

import json
from pathlib import Path

from openai import OpenAI

from pipeline.query_styles import QueryStyle
from utils import call_llm


def build_queries(
    style: QueryStyle,
    client: OpenAI,
    seeds_by_author: dict[int, list[dict]],
    summary_index: dict,
    output_path: Path,
    model: str = "azure/gpt-5.2",
) -> list[dict]:
    """Generate one query per seed recipe and save to output_path.

    Parameters
    ----------
    seeds_by_author : pre-selected seeds from PrepareCorpus, grouped by author_id.
                      Each seed dict must have: flow_id, version_no, connectors (list).
    summary_index   : (flow_id, version_no) → recipe_summary_with_comment
    """
    results = []

    for author_id, seeds in sorted(seeds_by_author.items()):
        print(f"Author {author_id}  ({len(seeds)} seeds)")

        for i, seed in enumerate(seeds, 1):
            key     = (seed["flow_id"], seed["version_no"])
            summary = summary_index.get(key, "")
            if not summary:
                print(f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} — no summary, skipping")
                continue

            print(
                f"  [{i}/{len(seeds)}] flow_id={seed['flow_id']} "
                f"({len(set(seed['connectors']))} connectors) ...",
                end=" ", flush=True,
            )

            query = _generate_query(client, model, style.system_prompt, summary)
            if query is None:
                print("FAILED (all retries exhausted) — skipping")
                continue
            print(f'"{query}"')

            results.append({
                "query_id":          f"{author_id}_{style.query_id_prefix}{i}",
                "author_id":         author_id,
                "source_flow_id":    seed["flow_id"],
                "source_version_no": seed["version_no"],
                "source_connectors": seed["connectors"],
                "query":             query,
            })

        print()

    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    print("=" * 70)
    print(f"ALL {len(results)} GENERATED QUERIES — please review before running Phase 2")
    print("=" * 70)
    current_author = None
    for r in results:
        if r["author_id"] != current_author:
            current_author = r["author_id"]
            print(f"\nAuthor {current_author}")
            print("-" * 40)
        print(f"  {r['query_id']:20s}  {r['query']}")

    print(f"\nSaved → {output_path}")
    return results


def _generate_query(
    client: OpenAI, model: str, system_prompt: str, recipe_summary: str
) -> str | None:
    result = call_llm(
        client,
        system=system_prompt,
        user=f"recipe_summary:\n{recipe_summary}",
        max_tokens=120,
        model=model,
        temperature=0.4,
    )
    return result.strip('"').strip("'") if result is not None else None
