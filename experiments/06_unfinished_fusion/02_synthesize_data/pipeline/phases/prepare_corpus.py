"""Phase 0 — Prepare Corpus.

Selects diverse seed recipes for every author and writes the flat CSV
that downstream step 03_evaluate_postgre uses to ingest recipes into
pgvector.

This phase is style-independent: the same CSV is shared by all query
categories. Running it multiple times is safe — the output is deterministic
and the file is simply overwritten.

Output: recipes_for_pgvector.csv (one row per selected seed recipe)
"""

import json
from pathlib import Path

import pandas as pd

from config import PGVECTOR_CSV_PATH
from utils import load_corpus_texts, load_tracking_data, select_recipe_seeds

OUTPUT_COLUMNS = [
    "recipe_uid", "author_id", "flow_id", "version_no",
    "connectors", "step_count", "text", "text_no_comments", "payload",
]


class PrepareCorpus:
    """
    Selects seed recipes and writes recipes_for_pgvector.csv.

    Parameters
    ----------
    output_path : destination CSV path (defaults to config.PGVECTOR_CSV_PATH)
    """

    def __init__(self, output_path: Path = PGVECTOR_CSV_PATH):
        self.output_path = output_path

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _make_row(author_id: int, seed: dict, corpus_texts: dict) -> dict:
        recipe_uid = f"{author_id}_{seed['flow_id']}_v{seed['version_no']}"
        key        = (seed["flow_id"], seed["version_no"])
        texts      = corpus_texts.get(key, {"text": "", "text_no_comments": ""})
        connectors = ", ".join(sorted(seed["connectors"]))
        payload    = json.dumps({
            "recipe_uid": recipe_uid,
            "author_id":  author_id,
            "flow_id":    seed["flow_id"],
            "version_no": seed["version_no"],
            "connectors": sorted(seed["connectors"]),
            "step_count": seed["step_count"],
        }, ensure_ascii=False)

        return {
            "recipe_uid":       recipe_uid,
            "author_id":        author_id,
            "flow_id":          seed["flow_id"],
            "version_no":       seed["version_no"],
            "connectors":       connectors,
            "step_count":       seed["step_count"],
            "text":             texts["text"],
            "text_no_comments": texts["text_no_comments"],
            "payload":          payload,
        }

    def _build_rows(
        self,
        author_index: dict,
        corpus_texts: dict,
    ) -> list[dict]:
        rows = []
        for author_id, all_recipes in sorted(author_index.items()):
            seeds = select_recipe_seeds(all_recipes)
            print(
                f"  Author {author_id:>10}  "
                f"{len(all_recipes):>4} recipes → {len(seeds):>3} seeds selected"
            )
            for seed in seeds:
                rows.append(self._make_row(author_id, seed, corpus_texts))
        return rows

    # ── Public interface ──────────────────────────────────────────────────────

    def run(self) -> pd.DataFrame:
        """Select seeds, write CSV, return the resulting DataFrame."""
        print("Loading recipe summaries ...")
        author_index, _ = load_tracking_data()
        corpus_texts    = load_corpus_texts()
        print(f"  {len(author_index)} authors loaded\n")

        rows = self._build_rows(author_index, corpus_texts)
        out  = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        out.to_csv(self.output_path, index=False)

        print(f"\n{'=' * 60}")
        print(f"Total seeds selected : {len(out)}")
        print(f"Authors              : {out['author_id'].nunique()}")
        print(f"Saved → {self.output_path}")

        return out
