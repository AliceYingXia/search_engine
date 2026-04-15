"""Phase 3 — Filter Dataset.

Loads the raw relevance CSV, drops queries whose source recipe did not pass
the ground-truth check (Strongly Related by both models), then produces:

  1. A summary CSV  — one row per query with strong/weak candidate UID lists.
  2. A detail CSV   — every row enriched with recipe_summary.
  3. Up to 50 example Excel files for manual review.
  4. Histogram plots of strong/weak list size distributions.
"""

import random
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from pipeline.query_styles import QueryStyle
from utils import make_recipe_uid, source_in_both_strong, summarise_query_group


def filter_dataset(
    style: QueryStyle,
    input_path: Path,
    summary_path: Path,
    detail_path: Path,
    examples_dir: Path,
    base_dir: Path,
    summary_index: dict,
) -> None:
    """Filter, aggregate, and export the final evaluation dataset."""
    df = pd.read_csv(input_path)
    print(f"Loaded {len(df)} rows, {df['query_id'].nunique()} queries\n")

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

    # ── Filter: drop queries where source is not strong in both models ────────
    pass_mask = df.groupby("query_id").apply(source_in_both_strong)
    keep_ids  = pass_mask[pass_mask].index
    drop_ids  = pass_mask[~pass_mask].index

    print("=" * 70)
    print("QUERY FILTER SUMMARY")
    print(f"  Total queries : {len(pass_mask)}")
    print(f"  Kept          : {len(keep_ids)}")
    print(f"  Dropped       : {len(drop_ids)}")
    print("=" * 70)

    if len(drop_ids):
        print("\nDROPPED QUERIES (source recipe not Strongly Related by both models):")
        dropped = (
            df[df["query_id"].isin(drop_ids)]
            .drop_duplicates("query_id")[["query_id", "query", "source_flow_id"]]
        )
        for _, row in dropped.iterrows():
            print(f"  {row['query_id']:25s}  flow_id={row['source_flow_id']}")
            print(f'    "{row["query"]}"')
    else:
        print("\nNo queries dropped — all source recipes passed the ground truth check.")
    print()

    df = df[df["query_id"].isin(keep_ids)].copy()
    print(f"Proceeding with {df['query_id'].nunique()} queries ({len(df)} rows)\n")

    # ── 1. Summary ────────────────────────────────────────────────────────────
    summary = (
        df.groupby(["source_author_id", "query_id", "query", "source_flow_id"])
        .apply(summarise_query_group, include_groups=False)
        .reset_index()
    )

    _assert_disjoint_lists(summary)

    summary.to_csv(summary_path, index=False)
    print(f"[1/3] Summary saved → {summary_path}  ({len(summary)} rows)")
    print(f"      Authors : {summary['source_author_id'].nunique()}")
    print(f"      Queries : {len(summary)}\n")

    # ── 2. Detail ─────────────────────────────────────────────────────────────
    df["recipe_summary"] = df.apply(
        lambda r: summary_index.get(
            (int(r["candidate_flow_id"]), int(r["candidate_version_no"])), ""
        ),
        axis=1,
    )
    df.to_csv(detail_path, index=False)
    print(f"[2/3] Detail saved  → {detail_path}  ({len(df)} rows)\n")

    # ── 3. Examples ───────────────────────────────────────────────────────────
    examples_dir.mkdir(exist_ok=True)
    version_lookup = (
        df.drop_duplicates("candidate_flow_id")
        .set_index("candidate_flow_id")["candidate_version_no"]
        .to_dict()
    )

    _write_queries_txt(summary, examples_dir, style.name)

    random.seed(42)
    sample_ids = random.sample(summary["query_id"].tolist(), k=min(50, len(summary)))
    print(f"[3/3] Generating {len(sample_ids)} example Excel files in {examples_dir} ...")

    for i, query_id in enumerate(sample_ids, 1):
        q_sum       = summary[summary["query_id"] == query_id].iloc[0]
        strong_uids = [u for u in q_sum["strong_list"].split(", ") if u] if q_sum["strong_list"] else []
        weak_uids   = [u for u in q_sum["weak_list"].split(", ")   if u] if q_sum["weak_list"]   else []
        all_uids    = set(strong_uids + weak_uids)

        q_candidates = df[(df["query_id"] == query_id) & (df["recipe_uid"].isin(all_uids))].copy()
        q_candidates["list_membership"] = q_candidates["recipe_uid"].apply(
            lambda uid: "strong" if uid in strong_uids else "weak"
        )

        sheet1 = q_candidates[[
            "query_id", "query", "source_flow_id", "list_membership",
            "candidate_flow_id", "candidate_version_no", "candidate_author_id",
            "candidate_connectors", "relevance_gpt52", "relevance_claude",
        ]].sort_values(["list_membership", "candidate_flow_id"])

        src_fid     = int(q_sum["source_flow_id"])
        src_vno     = version_lookup.get(src_fid)
        src_summary = (
            summary_index.get((src_fid, src_vno), "(no summary available)")
            if src_vno else "(no summary available)"
        )
        sheet2 = pd.DataFrame({
            "field": ["query_id", "query", "source_flow_id", "source_recipe_summary"],
            "value": [query_id, q_sum["query"], src_fid, src_summary],
        })

        sheet3 = q_candidates[[
            "recipe_uid", "list_membership", "relevance_gpt52", "relevance_claude", "recipe_summary",
        ]].sort_values(["list_membership", "recipe_uid"]).reset_index(drop=True)

        out_path = examples_dir / f"example_{i}.xlsx"
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            sheet1.to_excel(writer, sheet_name="Query & Candidates",  index=False)
            sheet2.to_excel(writer, sheet_name="Source Summary",      index=False)
            sheet3.to_excel(writer, sheet_name="Candidate Summaries", index=False)

        print(f"  Example {i}  query_id={query_id}  → {out_path.name}")

    print()

    # ── Stats & plots ─────────────────────────────────────────────────────────
    print("=" * 60)
    for col, name in [("relevance_gpt52", "GPT-5.2"), ("relevance_claude", "Claude")]:
        strong = (df[col] == "Strongly Related").sum()
        weak   = (df[col] == "Weakly Related").sum()
        print(f"  {name:<10}  Strong={strong}  Weak={weak}")
    print(f"  Total rows kept : {len(df)}")

    for col, title in [
        ("strong_count", "Distribution of Strong List Counts per Query"),
        ("weak_count",   "Distribution of Weak List Counts per Query"),
    ]:
        _save_histogram(summary, col, title, base_dir / f"{style.name}_{col}.png")


def _assert_disjoint_lists(summary: pd.DataFrame) -> None:
    errors = []
    for _, row in summary.iterrows():
        strong_set = set(row["strong_list"].split(", ")) - {""} if row["strong_list"] else set()
        weak_set   = set(row["weak_list"].split(", "))   - {""} if row["weak_list"]   else set()
        overlap    = strong_set & weak_set
        if overlap:
            errors.append((row["query_id"], overlap))
    if errors:
        raise AssertionError(
            f"BUG: {len(errors)} queries have UIDs in both strong and weak lists:\n"
            + "\n".join(f"  {qid}: {uids}" for qid, uids in errors)
        )
    print("Sanity check passed: strong and weak lists are disjoint for all queries.\n")


def _write_queries_txt(summary: pd.DataFrame, examples_dir: Path, style_name: str) -> None:
    txt_path = examples_dir / "all_queries.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write(f"{style_name} Evaluation Queries  ({len(summary)} total)\n")
        f.write("=" * 70 + "\n\n")
        current_author = None
        for _, row in summary.sort_values(["source_author_id", "query_id"]).iterrows():
            if row["source_author_id"] != current_author:
                current_author = row["source_author_id"]
                f.write(f"Author {current_author}\n")
                f.write("-" * 40 + "\n")
            f.write(f"  {row['query_id']:25s}  {row['query']}\n")
        f.write("\n")
    print(f"  All queries saved → {txt_path}\n")


def _save_histogram(summary: pd.DataFrame, col: str, title: str, out_path: Path) -> None:
    fig, ax = plt.subplots()
    max_val = int(summary[col].max()) if summary[col].max() > 0 else 1
    bins    = range(0, max_val + 2)
    ax.hist(summary[col], bins=bins, align="left", rwidth=0.7, color="steelblue", edgecolor="white")
    ax.set_xlabel("Count per query")
    ax.set_ylabel("Number of queries")
    ax.set_title(title)
    ax.set_xticks(list(bins)[:-1])
    fig.savefig(out_path, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  Plot saved → {out_path}")
