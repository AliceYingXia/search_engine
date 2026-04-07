"""
evaluate_category1_examples.py
================================

Uses GPT-5.2 to independently evaluate the Category 1 example Excel files
produced by category_1_eval_dataset.py.

What this script does
---------------------
For each example (category1_example_1.xlsx ... category1_example_50.xlsx):

  1. Query quality assessment
     GPT-5.2 rates the query on two dimensions:
       - Clarity     : Is the query unambiguous and well-formed?
       - Specificity : Is it appropriately broad for a Category 1 query
                       (describes a business process, not a single action)?
     Rating scale: Good / Acceptable / Poor
     Plus a one-sentence comment.

  2. Candidate label review
     For each strong and weak candidate, GPT-5.2 is shown the query and
     the candidate's recipe summary and asked whether it agrees with the
     assigned label (strong / weak) or would reclassify it.
     Response per candidate: Agree / Reclassify → <suggested_label>
     Plus a one-sentence reason.

Output
------
  05_sythesize_eval_dataset/category1_examples/evaluation_results.xlsx

    Sheet "Query Quality"
      example_file, query_id, query, clarity, specificity, comment

    Sheet "Candidate Labels"
      example_file, query_id, recipe_uid, assigned_label,
      gpt52_verdict (Agree / Reclassify), suggested_label, reason

Usage
-----
    python 05_sythesize_eval_dataset/evaluate_category1_examples.py
"""

import json
import re
import time
from pathlib import Path

import pandas as pd

from eval_utils import make_openai_client

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
BASE_DIR     = Path(__file__).parent
EXAMPLES_DIR = BASE_DIR / "category1_examples"
OUTPUT_PATH  = EXAMPLES_DIR / "evaluation_results.xlsx"

MODEL = "azure/gpt-5.2"

EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("category1_example_*.xlsx"))


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_QUERY_QUALITY = """\
You are evaluating the quality of search queries in an evaluation dataset for \
a semantic search system over Workato automation recipes.

Category 1 queries describe a broad business process rather than a specific \
action. A good Category 1 query:
  - Is unambiguous and clearly written.
  - Describes a process or goal (e.g. "Which recipes automate syncing employee \
records between HR and payroll?"), not a specific system action.
  - Could plausibly match several different automation recipes.

You will be given a query and the recipe summary of the source recipe that \
generated it.

Return a single JSON object with exactly these keys:
  "clarity"     : "Good" | "Acceptable" | "Poor"
  "specificity" : "Good" | "Acceptable" | "Poor"
  "comment"     : one sentence explaining your ratings

Return ONLY valid JSON — no markdown fences, no explanation."""


SYSTEM_CANDIDATE_REVIEW = """\
You are reviewing candidate labels in a semantic search evaluation dataset for \
Workato automation recipes.

A search query has been issued and a set of candidate recipes have been labelled:
  strong — the recipe is a primary component of the business process the query describes
  weak   — the recipe plays a supporting or peripheral role in that process

You will be given the query and the recipe summaries for each candidate with \
their current labels. For each candidate decide:
  - "Agree"      : the assigned label is correct
  - "Reclassify" : the label should be changed (provide suggested_label: "strong" or "weak" or "not_related")

Return a single JSON array. Each element corresponds to one candidate \
(in the same order) and has exactly these keys:
  "recipe_uid"      : the recipe_uid string
  "verdict"         : "Agree" | "Reclassify"
  "suggested_label" : same as assigned_label if Agree, otherwise the correct label
  "reason"          : one sentence

Return ONLY valid JSON — no markdown fences, no explanation."""


# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------

def call_llm(client, system: str, user: str, max_tokens: int = 800) -> str:
    """Call GPT-5.2 and return raw text content."""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()


def strip_fences(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json(raw: str, label: str) -> dict | list | None:
    """Parse JSON from LLM response; return None on failure."""
    raw = strip_fences(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"    WARNING: JSON parse error in {label} — skipping")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not EXAMPLE_FILES:
        raise FileNotFoundError(
            f"No category1_example_*.xlsx files found in {EXAMPLES_DIR}. "
            "Run category_1_eval_dataset.py first."
        )

    client = make_openai_client()

    quality_rows   = []
    candidate_rows = []

    for xlsx_path in EXAMPLE_FILES:
        print(f"\n{'=' * 60}")
        print(f"File: {xlsx_path.name}")
        print("=" * 60)

        sheet1 = pd.read_excel(xlsx_path, sheet_name="Query & Candidates")
        sheet2 = pd.read_excel(xlsx_path, sheet_name="Source Summary")
        sheet3 = pd.read_excel(xlsx_path, sheet_name="Candidate Summaries")

        # Extract query metadata from Sheet 2
        meta        = dict(zip(sheet2["field"], sheet2["value"]))
        query_id    = str(meta["query_id"])
        query_text  = str(meta["query"])
        src_summary = str(meta["source_recipe_summary"])

        print(f"  query_id : {query_id}")
        print(f"  query    : \"{query_text}\"")

        # ── 1. Query quality ──────────────────────────────────────────────────
        print("  [1/2] Evaluating query quality ...")
        user_quality = (
            f"Query: \"{query_text}\"\n\n"
            f"Source recipe summary:\n{src_summary}"
        )
        raw_quality = call_llm(client, SYSTEM_QUERY_QUALITY, user_quality, max_tokens=200)
        result_quality = parse_json(raw_quality, f"{xlsx_path.name} quality")

        if result_quality:
            print(f"        clarity={result_quality.get('clarity')}  "
                  f"specificity={result_quality.get('specificity')}")
            print(f"        comment: {result_quality.get('comment')}")
            quality_rows.append({
                "example_file": xlsx_path.name,
                "query_id":     query_id,
                "query":        query_text,
                "clarity":      result_quality.get("clarity"),
                "specificity":  result_quality.get("specificity"),
                "comment":      result_quality.get("comment"),
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

        # Build candidate block: one entry per candidate
        candidates_block_parts = []
        for _, row in sheet3.iterrows():
            candidates_block_parts.append(
                f"recipe_uid: {row['recipe_uid']}\n"
                f"assigned_label: {row['list_membership']}\n"
                f"recipe_summary: {row['recipe_summary']}"
            )
        candidates_block = "\n\n---\n\n".join(candidates_block_parts)

        user_candidates = (
            f"Query: \"{query_text}\"\n\n"
            f"Candidates:\n\n{candidates_block}"
        )

        raw_candidates = call_llm(
            client, SYSTEM_CANDIDATE_REVIEW, user_candidates,
            max_tokens=100 * len(sheet3) + 200,
        )
        result_candidates = parse_json(raw_candidates, f"{xlsx_path.name} candidates")

        if result_candidates and isinstance(result_candidates, list):
            # Build lookup: recipe_uid → assigned label from Sheet 3
            label_lookup = dict(zip(sheet3["recipe_uid"], sheet3["list_membership"]))

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
                if subset.empty:
                    continue
                agree      = (subset["gpt52_verdict"] == "Agree").sum()
                reclassify = (subset["gpt52_verdict"] == "Reclassify").sum()
                print(f"        {label:<6}  Agree={agree}  Reclassify={reclassify}")
        else:
            # fallback: record parse failure for every candidate
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

        time.sleep(0.5)   # light rate-limit buffer between examples

    # ── Save results ──────────────────────────────────────────────────────────
    df_quality    = pd.DataFrame(quality_rows)
    df_candidates = pd.DataFrame(candidate_rows)

    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        df_quality.to_excel(writer,    sheet_name="Query Quality",    index=False)
        df_candidates.to_excel(writer, sheet_name="Candidate Labels", index=False)

    print(f"\n{'=' * 60}")
    print(f"Results saved → {OUTPUT_PATH}")
    print(f"  Query Quality    : {len(df_quality)} rows")
    print(f"  Candidate Labels : {len(df_candidates)} rows")

    # Quick summary
    if not df_quality.empty:
        print("\nQuery Quality Summary:")
        for col in ["clarity", "specificity"]:
            print(f"  {col}: " + "  ".join(
                f"{k}={v}" for k, v in df_quality[col].value_counts().items()
            ))

    if not df_candidates.empty and df_candidates["gpt52_verdict"].notna().any():
        print(f"\nCandidate Label Review (all {len(EXAMPLE_FILES)} examples):")
        for label in ["strong", "weak"]:
            subset = df_candidates[df_candidates["assigned_label"] == label]
            if subset.empty:
                continue
            total      = subset["gpt52_verdict"].notna().sum()
            reclassify = (subset["gpt52_verdict"] == "Reclassify").sum()
            print(f"  {label:<6}  Agree={total - reclassify}  Reclassify={reclassify}"
                  + (f"  ({100 * reclassify / total:.0f}% flagged)" if total else ""))


if __name__ == "__main__":
    main()
