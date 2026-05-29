"""Eval Phase — Evaluate Examples.

Uses GPT-5.2 to independently review the example Excel files produced by
filter_dataset. For each file:

  1. Query quality — rates Clarity and Specificity (Good / Acceptable / Poor).
  2. Candidate label review — Agree or Reclassify each strong/weak candidate.

Output: evaluation_results.xlsx with two sheets.
"""

import time
from pathlib import Path

import pandas as pd
from openai import OpenAI

from pipeline.query_styles import QueryStyle
from utils import call_llm_json

_MODEL = "azure/gpt-5.2"

_SYSTEM_CANDIDATE_REVIEW = """\
You are reviewing candidate labels in a semantic search evaluation dataset \
for Workato automation recipes.

A search query has been issued and a set of candidate recipes have been labelled:
  strong — the recipe is a primary component of the business process the query describes
  weak   — the recipe plays a supporting or peripheral role in that process

You will be given the query and the recipe summaries for each candidate with \
their current labels. For each candidate decide:
  - "Agree"      : the assigned label is correct
  - "Reclassify" : the label should be changed

Return a single JSON array. Each element corresponds to one candidate \
(in the same order) and has exactly these keys:
  "recipe_uid"      : the recipe_uid string
  "verdict"         : "Agree" | "Reclassify"
  "suggested_label" : same as assigned_label if Agree, otherwise "strong" | "weak" | "not_related"
  "reason"          : one sentence

Return ONLY valid JSON — no markdown fences, no explanation."""


def evaluate_examples(
    style: QueryStyle,
    client: OpenAI,
    examples_dir: Path,
    output_path: Path,
) -> None:
    """Run GPT-5.2 quality checks over all example_*.xlsx files."""
    example_files = sorted(examples_dir.glob("example_*.xlsx"))
    if not example_files:
        raise FileNotFoundError(
            f"No example_*.xlsx files found in {examples_dir}. "
            "Run filter_dataset first."
        )

    quality_rows   = []
    candidate_rows = []

    for xlsx_path in example_files:
        print(f"\n{'=' * 60}")
        print(f"File: {xlsx_path.name}")
        print("=" * 60)

        sheet2 = pd.read_excel(xlsx_path, sheet_name="Source Summary")
        sheet3 = pd.read_excel(xlsx_path, sheet_name="Candidate Summaries")

        meta        = dict(zip(sheet2["field"], sheet2["value"]))
        query_id    = str(meta["query_id"])
        query_text  = str(meta["query"])
        src_summary = str(meta["source_recipe_summary"])

        print(f"  query_id : {query_id}")
        print(f'  query    : "{query_text}"')

        # ── 1. Query quality ──────────────────────────────────────────────────
        print("  [1/2] Evaluating query quality ...")
        user_quality = f'Query: "{query_text}"\n\nSource recipe summary:\n{src_summary}'
        result       = call_llm_json(
            client, style.quality_system_prompt, user_quality,
            max_tokens=200, label=f"{xlsx_path.name} quality",
        )

        if result:
            print(f"        clarity={result.get('clarity')}  specificity={result.get('specificity')}")
            print(f"        comment: {result.get('comment')}")
            quality_rows.append({
                "example_file": xlsx_path.name,
                "query_id":     query_id,
                "query":        query_text,
                "clarity":      result.get("clarity"),
                "specificity":  result.get("specificity"),
                "comment":      result.get("comment"),
            })
        else:
            quality_rows.append({
                "example_file": xlsx_path.name,
                "query_id":     query_id,
                "query":        query_text,
                "clarity":      None,
                "specificity":  None,
                "comment":      "parse error",
            })

        # ── 2. Candidate label review ─────────────────────────────────────────
        print(f"  [2/2] Reviewing {len(sheet3)} candidate labels ...")
        candidates_block = "\n\n---\n\n".join(
            f"recipe_uid: {row['recipe_uid']}\n"
            f"assigned_label: {row['list_membership']}\n"
            f"recipe_summary: {row['recipe_summary']}"
            for _, row in sheet3.iterrows()
        )
        user_candidates   = f'Query: "{query_text}"\n\nCandidates:\n\n{candidates_block}'
        result_candidates = call_llm_json(
            client, _SYSTEM_CANDIDATE_REVIEW, user_candidates,
            max_tokens=100 * len(sheet3) + 200,
            label=f"{xlsx_path.name} candidates",
        )
        label_lookup      = dict(zip(sheet3["recipe_uid"], sheet3["list_membership"]))

        if result_candidates and isinstance(result_candidates, list):
            for item in result_candidates:
                uid = item.get("recipe_uid")
                candidate_rows.append({
                    "example_file":    xlsx_path.name,
                    "query_id":        query_id,
                    "recipe_uid":      uid,
                    "assigned_label":  label_lookup.get(uid),
                    "gpt52_verdict":   item.get("verdict"),
                    "suggested_label": item.get("suggested_label"),
                    "reason":          item.get("reason"),
                })
            df_iter = pd.DataFrame(candidate_rows[-len(result_candidates):])
            for label in ["strong", "weak"]:
                subset = df_iter[df_iter["assigned_label"] == label]
                if not subset.empty:
                    agree      = (subset["gpt52_verdict"] == "Agree").sum()
                    reclassify = (subset["gpt52_verdict"] == "Reclassify").sum()
                    print(f"        {label:<6}  Agree={agree}  Reclassify={reclassify}")
        else:
            for _, row in sheet3.iterrows():
                candidate_rows.append({
                    "example_file":    xlsx_path.name,
                    "query_id":        query_id,
                    "recipe_uid":      row["recipe_uid"],
                    "assigned_label":  row["list_membership"],
                    "gpt52_verdict":   None,
                    "suggested_label": None,
                    "reason":          "parse error",
                })

        time.sleep(0.5)

    df_quality    = pd.DataFrame(quality_rows)
    df_candidates = pd.DataFrame(candidate_rows)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_quality.to_excel(writer,    sheet_name="Query Quality",    index=False)
        df_candidates.to_excel(writer, sheet_name="Candidate Labels", index=False)

    print(f"\n{'=' * 60}")
    print(f"Results saved → {output_path}")
    print(f"  Query Quality    : {len(df_quality)} rows")
    print(f"  Candidate Labels : {len(df_candidates)} rows")

    if not df_quality.empty:
        print("\nQuery Quality Summary:")
        for col in ["clarity", "specificity"]:
            counts = df_quality[col].value_counts()
            print(f"  {col}: " + "  ".join(f"{k}={v}" for k, v in counts.items()))

    if not df_candidates.empty and df_candidates["gpt52_verdict"].notna().any():
        print(f"\nCandidate Label Review ({len(example_files)} examples):")
        for label in ["strong", "weak"]:
            subset = df_candidates[df_candidates["assigned_label"] == label]
            if subset.empty:
                continue
            total      = subset["gpt52_verdict"].notna().sum()
            reclassify = (subset["gpt52_verdict"] == "Reclassify").sum()
            flag_pct   = f"  ({100 * reclassify / total:.0f}% flagged)" if total else ""
            print(f"  {label:<6}  Agree={total - reclassify}  Reclassify={reclassify}{flag_pct}")
