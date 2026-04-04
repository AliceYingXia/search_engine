"""
category_2_eval_dataset.py
==========================

Phase 3 of the Category 2 evaluation dataset pipeline.
Run this AFTER build_eval_category2_relevance.py.

What this script does
---------------------
1. Loads eval_category2.csv (Phase 2 output).
2. Drops queries where the source recipe is NOT Strongly Related by BOTH
   models — these queries failed their own ground truth check.
3. Produces two outputs:
     a. category2_eval_dataset.csv  — one row per query with strong/weak lists.
     b. eval_category2_detail.csv   — every remaining row enriched with
        recipe_summary for manual inspection.

Filter rule
-----------
  A query is KEPT only if, for its source_flow_id candidate row:
    relevance_gpt52  == "Strongly Related"
    AND
    relevance_claude == "Strongly Related"

  Queries that fail this check are printed and excluded from all outputs.

Inputs
------
  05_sythesize_eval_dataset/eval_category2.csv
  02_cleaning/cleaned/*_semantic.json

Output
------
  05_sythesize_eval_dataset/category2_eval_dataset.csv
  05_sythesize_eval_dataset/eval_category2_detail.csv

    Summary columns:
      source_author_id
      query_id
      query
      source_flow_id
      strong_list    comma-separated recipe UIDs rated Strongly Related by BOTH models
      strong_count
      weak_list      comma-separated recipe UIDs where both models gave a positive label
                     but did not both agree on Strongly Related:
                       case 1 — one model Strong, the other Weak  (S/W or W/S)
                       case 2 — both models Weak                  (W/W)
      weak_count

    Detail columns:
      all columns from eval_category2.csv  +  recipe_uid  +  recipe_summary

Usage
-----
    python 05_sythesize_eval_dataset/category_2_eval_dataset.py
"""

import json
import random
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR    = Path(__file__).parent
CLEANED_DIR = BASE_DIR.parent / "02_cleaning" / "cleaned"
INPUT_PATH  = BASE_DIR / "eval_category2.csv"

SUMMARY_PATH = BASE_DIR / "category2_eval_dataset.csv"
DETAIL_PATH  = BASE_DIR / "eval_category2_detail.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_summary_index() -> dict:
    """Return {(flow_id, version_no): recipe_summary} from cleaned/."""
    index = {}
    for sf in sorted(CLEANED_DIR.glob("*_semantic.json")):
        sem = json.loads(sf.read_text())
        index[(sem["flow_id"], sem["version_no"])] = sem["recipe_summary"]
    return index


def make_recipe_uid(row: pd.Series) -> str:
    return f"{int(row['candidate_author_id'])}_{int(row['candidate_flow_id'])}_v{int(row['candidate_version_no'])}"


def source_in_both_strong(group: pd.DataFrame) -> bool:
    """Return True if the source recipe is Strongly Related by BOTH models."""
    src = group["source_flow_id"].iloc[0]
    src_rows = group[group["candidate_flow_id"] == src]
    if src_rows.empty:
        return False
    in_gpt52  = (src_rows["relevance_gpt52"]  == "Strongly Related").any()
    in_claude = (src_rows["relevance_claude"] == "Strongly Related").any()
    return bool(in_gpt52 and in_claude)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = pd.read_csv(INPUT_PATH)
    print(f"Loaded {len(df)} rows, {df['query_id'].nunique()} queries from {INPUT_PATH}\n")

    # Support CSVs generated before the column rename
    df = df.rename(columns={
        "author_id":  "source_author_id",
        "flow_id":    "candidate_flow_id",
        "version_no": "candidate_version_no",
        "connectors": "candidate_connectors",
    })

    bad_rows = df[["candidate_author_id", "candidate_flow_id", "candidate_version_no"]].isna().any(axis=1)
    if bad_rows.any():
        print(f"WARNING: dropping {bad_rows.sum()} malformed row(s) with NaN in candidate ID columns.\n")
        df = df[~bad_rows].copy()

    df["recipe_uid"] = df.apply(make_recipe_uid, axis=1)

    # ── Filter: drop queries where source is not strong in both models ───────
    pass_mask  = df.groupby("query_id").apply(source_in_both_strong)
    keep_ids   = pass_mask[pass_mask].index
    drop_ids   = pass_mask[~pass_mask].index

    total_queries = len(pass_mask)
    print("=" * 70)
    print(f"QUERY FILTER SUMMARY")
    print(f"  Total queries   : {total_queries}")
    print(f"  Kept            : {len(keep_ids)}")
    print(f"  Dropped         : {len(drop_ids)}")
    print("=" * 70)

    if len(drop_ids):
        print(f"\nDROPPED QUERIES (source recipe not Strongly Related by both models):")
        dropped_queries = (
            df[df["query_id"].isin(drop_ids)]
            .drop_duplicates("query_id")[["query_id", "query", "source_flow_id"]]
        )
        for _, row in dropped_queries.iterrows():
            print(f"  {row['query_id']:25s}  flow_id={row['source_flow_id']}")
            print(f"    \"{row['query']}\"")
    else:
        print("\nNo queries dropped — all source recipes passed the ground truth check.")
    print()

    df = df[df["query_id"].isin(keep_ids)].copy()
    print(f"Proceeding with {df['query_id'].nunique()} queries ({len(df)} rows)\n")

    # ── 1. Summary ────────────────────────────────────────────────────────────
    def summarise(g):
        POSITIVE = {"Strongly Related", "Weakly Related"}
        both_strong_mask = (
            (g["relevance_gpt52"]  == "Strongly Related") &
            (g["relevance_claude"] == "Strongly Related")
        )
        both_positive_mask = (
            g["relevance_gpt52"].isin(POSITIVE) &
            g["relevance_claude"].isin(POSITIVE)
        )
        weak_mask   = both_positive_mask & ~both_strong_mask
        strong_uids = g.loc[both_strong_mask, "recipe_uid"].tolist()
        weak_uids   = g.loc[weak_mask,        "recipe_uid"].tolist()
        return pd.Series({
            "strong_list":  ", ".join(sorted(strong_uids)),
            "strong_count": len(strong_uids),
            "weak_list":    ", ".join(weak_uids),
            "weak_count":   len(weak_uids),
        })

    summary = (
        df.groupby(["source_author_id", "query_id", "query", "source_flow_id"])
        .apply(summarise, include_groups=False)
        .reset_index()
    )

    # ── Sanity check: strong and weak lists must be disjoint ─────────────────
    overlap_errors = []
    for _, row in summary.iterrows():
        strong_set = set(row["strong_list"].split(", ")) - {""} if row["strong_list"] else set()
        weak_set   = set(row["weak_list"].split(", "))   - {""} if row["weak_list"]   else set()
        overlap    = strong_set & weak_set
        if overlap:
            overlap_errors.append((row["query_id"], overlap))

    if overlap_errors:
        raise AssertionError(
            f"BUG: {len(overlap_errors)} queries have recipe UIDs in both strong and weak lists:\n"
            + "\n".join(f"  {qid}: {uids}" for qid, uids in overlap_errors)
        )
    print("Sanity check passed: strong and weak lists are disjoint for all queries.\n")

    summary.to_csv(SUMMARY_PATH, index=False)
    print(f"[1/2] Summary saved → {SUMMARY_PATH}  ({len(summary)} rows)")
    print(f"      Authors : {summary['source_author_id'].nunique()}")
    print(f"      Queries : {len(summary)}\n")

    # ── 2. Detail ─────────────────────────────────────────────────────────────
    print("Loading recipe summaries from cleaned/ ...")
    summary_index = load_summary_index()
    print(f"  {len(summary_index)} summaries loaded\n")

    df["recipe_summary"] = df.apply(
        lambda r: summary_index.get((int(r["candidate_flow_id"]), int(r["candidate_version_no"])), ""),
        axis=1,
    )

    df.to_csv(DETAIL_PATH, index=False)
    print(f"[2/2] Detail saved  → {DETAIL_PATH}  ({len(df)} rows)\n")

    # ── 3. Examples ───────────────────────────────────────────────────────────
    EXAMPLES_DIR = BASE_DIR / "category2_examples"
    EXAMPLES_DIR.mkdir(exist_ok=True)

    random.seed(42)
    sample_ids = random.sample(summary["query_id"].tolist(), k=min(50, len(summary)))
    print(f"[3/3] Generating {len(sample_ids)} example Excel files in {EXAMPLES_DIR} ...")

    # Write all queries to a txt file
    queries_txt_path = EXAMPLES_DIR / "all_queries.txt"
    with queries_txt_path.open("w", encoding="utf-8") as f:
        f.write(f"Category 2 Evaluation Queries  ({len(summary)} total)\n")
        f.write("=" * 70 + "\n\n")
        current_author = None
        for _, row in summary.sort_values(["source_author_id", "query_id"]).iterrows():
            if row["source_author_id"] != current_author:
                current_author = row["source_author_id"]
                f.write(f"Author {current_author}\n")
                f.write("-" * 40 + "\n")
            f.write(f"  {row['query_id']:25s}  {row['query']}\n")
        f.write("\n")
    print(f"  All queries saved → {queries_txt_path}\n")

    # Build a lookup: candidate_flow_id → candidate_version_no (any row will do)
    version_lookup = (
        df.drop_duplicates("candidate_flow_id")
        .set_index("candidate_flow_id")["candidate_version_no"]
        .to_dict()
    )

    for i, query_id in enumerate(sample_ids, 1):
        q_sum = summary[summary["query_id"] == query_id].iloc[0]

        strong_uids = [u for u in q_sum["strong_list"].split(", ") if u] if q_sum["strong_list"] else []
        weak_uids   = [u for u in q_sum["weak_list"].split(", ")   if u] if q_sum["weak_list"]   else []
        all_uids    = set(strong_uids + weak_uids)

        # Sheet 1: query info + candidates in strong/weak lists
        q_candidates = df[(df["query_id"] == query_id) & (df["recipe_uid"].isin(all_uids))].copy()
        q_candidates["list_membership"] = q_candidates["recipe_uid"].apply(
            lambda uid: "strong" if uid in strong_uids else "weak"
        )
        sheet1 = q_candidates[[
            "query_id", "query", "source_flow_id", "list_membership",
            "candidate_flow_id", "candidate_version_no", "candidate_author_id",
            "candidate_connectors", "relevance_gpt52", "relevance_claude",
        ]].sort_values(["list_membership", "candidate_flow_id"])

        # Sheet 2: source recipe summary
        src_fid = int(q_sum["source_flow_id"])
        src_vno = version_lookup.get(src_fid)
        src_summary = summary_index.get((src_fid, src_vno), "(no summary available)") if src_vno else "(no summary available)"
        sheet2 = pd.DataFrame({
            "field": ["query_id", "query", "source_flow_id", "source_recipe_summary"],
            "value": [query_id, q_sum["query"], src_fid, src_summary],
        })

        # Sheet 3: candidate recipe summaries
        sheet3 = q_candidates[[
            "recipe_uid", "list_membership", "relevance_gpt52", "relevance_claude", "recipe_summary",
        ]].sort_values(["list_membership", "recipe_uid"]).reset_index(drop=True)

        out_path = EXAMPLES_DIR / f"category2_example_{i}.xlsx"
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            sheet1.to_excel(writer, sheet_name="Query & Candidates", index=False)
            sheet2.to_excel(writer, sheet_name="Source Summary",     index=False)
            sheet3.to_excel(writer, sheet_name="Candidate Summaries", index=False)

        print(f"  Example {i}  query_id={query_id}  → {out_path}")

    print()

    # ── Quick stats ───────────────────────────────────────────────────────────
    print("=" * 60)
    for col, name in [("relevance_gpt52", "GPT-5.2"), ("relevance_claude", "Claude")]:
        strong = (df[col] == "Strongly Related").sum()
        weak   = (df[col] == "Weakly Related").sum()
        print(f"  {name:<10}  Strong={strong}  Weak={weak}")
    print(f"  Total rows kept : {len(df)}")

    # ── Plots ─────────────────────────────────────────────────────────────────
    for col, filename, title in [
        ("strong_count", "category2_eval_strong_count", "Distribution of Strong List Counts per Query"),
        ("weak_count",   "category2_eval_weak_count",   "Distribution of Weak List Counts per Query"),
    ]:
        fig, ax = plt.subplots()
        max_val = int(summary[col].max()) if summary[col].max() > 0 else 1
        bins    = range(0, max_val + 2)
        ax.hist(summary[col], bins=bins, align="left", rwidth=0.7, color="steelblue", edgecolor="white")
        ax.set_xlabel("Count per query")
        ax.set_ylabel("Number of queries")
        ax.set_title(title)
        ax.set_xticks(list(bins)[:-1])
        out_path = BASE_DIR / f"{filename}.png"
        fig.savefig(out_path, bbox_inches="tight", dpi=150)
        plt.close(fig)
        print(f"  Plot saved → {out_path}")


if __name__ == "__main__":
    main()
