from pathlib import Path

import pandas as pd

from config import BASE_DIR, MODEL_GPT52, PGVECTOR_CSV_PATH
from pipeline.phases.adjudicate import adjudicate_disagreements
from pipeline.phases.dataset import filter_dataset
from pipeline.phases.evaluate import evaluate_examples
from pipeline.phases.prepare_corpus import PrepareCorpus
from pipeline.phases.queries import build_queries
from pipeline.phases.relevance import exhaust_relevance
from pipeline.phases.select_queries import select_queries
from pipeline.query_styles import QueryStyle
from utils import load_tracking_data, make_openai_client

ALL_PHASES = ("prepare", "queries", "select", "relevance", "adjudicate", "dataset", "evaluate")


class SynthesizePipeline:
    """
    End-to-end pipeline for synthesising an evaluation dataset.

    All phase methods are driven by the QueryStyle passed at construction —
    swap the style to produce a different category of queries without touching
    any other code.

    Usage
    -----
        pipeline = SynthesizePipeline(CAT1)
        pipeline.run()                             # all phases
        pipeline.run(("queries", "relevance"))     # subset of phases
    """

    def __init__(self, style: QueryStyle, base_dir: Path = BASE_DIR):
        self.style    = style
        self.base_dir = base_dir
        self.client   = make_openai_client()

        n = style.name
        self.queries_path          = base_dir / f"{n}_queries.json"
        self.selected_queries_path = base_dir / f"{n}_selected_queries.json"
        self.raw_path             = base_dir / f"{n}_raw.csv"
        self.checkpoint_path      = base_dir / f"{n}_checkpoint.json"
        self.adjudicated_path     = base_dir / f"{n}_adjudicated.csv"
        self.adjudicate_ckpt_path = base_dir / f"{n}_adjudicate_checkpoint.json"
        self.summary_path         = base_dir / f"{n}_dataset.csv"
        self.detail_path          = base_dir / f"{n}_detail.csv"
        self.examples_dir         = base_dir / f"{n}_examples"
        self.eval_path            = self.examples_dir / "evaluation_results.xlsx"

    # ── Phases ────────────────────────────────────────────────────────────────

    def prepare_corpus(self) -> None:
        """Phase 0 — select seed recipes and write recipes_for_pgvector.csv.

        Style-independent: the same CSV is shared by all categories and by
        03_evaluate_embeddings. Safe to re-run; output is deterministic.
        """
        self._print_phase_header("Phase 0 — Prepare Corpus")
        PrepareCorpus().run()

    def build_queries(self) -> None:
        """Phase 1 — generate one query per seed recipe.

        Reads seeds from recipes_for_pgvector.csv (produced by `prepare`).
        Run the `prepare` phase first if the CSV does not exist.
        """
        self._print_phase_header("Phase 1 — Build Queries")
        self._require(PGVECTOR_CSV_PATH, "prepare")
        _, summary_index = load_tracking_data()
        seeds_by_author  = self._load_seeds_by_author()
        build_queries(
            style=self.style,
            client=self.client,
            seeds_by_author=seeds_by_author,
            summary_index=summary_index,
            output_path=self.queries_path,
            model=MODEL_GPT52,
        )

    def select_queries(self) -> None:
        """Phase 1.5 — select 50 diverse queries using embedding similarity."""
        self._print_phase_header("Phase 1.5 — Select Queries")
        self._require(self.queries_path, "build_queries")
        select_queries(
            queries_path=self.queries_path,
            output_path=self.selected_queries_path,
        )

    def exhaust_relevance(self) -> None:
        """Phase 2 — score every (query, seed) pair with two models."""
        self._print_phase_header("Phase 2 — Exhaust Relevance")
        # Prefer the deduplicated selection if it exists
        input_queries = (
            self.selected_queries_path
            if self.selected_queries_path.exists()
            else self.queries_path
        )
        self._require(input_queries, "build_queries or select_queries")
        author_index, summary_index = load_tracking_data()
        exhaust_relevance(
            style=self.style,
            client=self.client,
            queries_path=input_queries,
            author_index=author_index,
            summary_index=summary_index,
            output_path=self.raw_path,
            checkpoint_path=self.checkpoint_path,
        )

    def adjudicate(self) -> None:
        """Phase 2.5 — resolve S/W and W/S disagreements with a third LLM call."""
        self._print_phase_header("Phase 2.5 — Adjudicate Disagreements")
        self._require(self.raw_path, "exhaust_relevance")
        _, summary_index = load_tracking_data()
        adjudicate_disagreements(
            style=self.style,
            client=self.client,
            raw_path=self.raw_path,
            summary_index=summary_index,
            output_path=self.adjudicated_path,
            checkpoint_path=self.adjudicate_ckpt_path,
            model=MODEL_GPT52,
        )

    def filter_dataset(self) -> None:
        """Phase 3 — filter, aggregate, and export the final dataset."""
        self._print_phase_header("Phase 3 — Filter Dataset")
        # Use adjudicated CSV if available, otherwise fall back to raw
        input_path = self.adjudicated_path if self.adjudicated_path.exists() else self.raw_path
        self._require(input_path, "exhaust_relevance")
        _, summary_index = load_tracking_data()
        filter_dataset(
            style=self.style,
            input_path=input_path,
            summary_path=self.summary_path,
            detail_path=self.detail_path,
            examples_dir=self.examples_dir,
            base_dir=self.base_dir,
            summary_index=summary_index,
        )

    def evaluate_examples(self) -> None:
        """Eval — GPT-5.2 quality review of sampled example files."""
        self._print_phase_header("Eval — Evaluate Examples")
        evaluate_examples(
            style=self.style,
            client=self.client,
            examples_dir=self.examples_dir,
            output_path=self.eval_path,
        )

    def run(self, phases: tuple[str, ...] = ALL_PHASES) -> None:
        """Run one or more phases in order."""
        phase_map = {
            "prepare":    self.prepare_corpus,
            "queries":    self.build_queries,
            "select":     self.select_queries,
            "relevance":  self.exhaust_relevance,
            "adjudicate": self.adjudicate,
            "dataset":    self.filter_dataset,
            "evaluate":   self.evaluate_examples,
        }
        unknown = set(phases) - phase_map.keys()
        if unknown:
            raise ValueError(f"Unknown phase(s): {unknown}. Valid: {ALL_PHASES}")
        for phase in phases:
            phase_map[phase]()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_seeds_by_author(self) -> dict[int, list[dict]]:
        """Load recipes_for_pgvector.csv and group seeds by author_id."""
        df = pd.read_csv(PGVECTOR_CSV_PATH)
        seeds_by_author: dict[int, list[dict]] = {}
        for _, row in df.iterrows():
            seeds_by_author.setdefault(int(row["author_id"]), []).append({
                "flow_id":    int(row["flow_id"]),
                "version_no": int(row["version_no"]),
                "connectors": [c.strip() for c in str(row["connectors"]).split(",")],
                "step_count": int(row["step_count"]),
            })
        return seeds_by_author

    def _print_phase_header(self, title: str) -> None:
        print(f"\n{'=' * 70}")
        print(f"{title}  [{self.style.name}]")
        print("=" * 70 + "\n")

    def _require(self, path: Path, preceding_phase: str) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. Run {preceding_phase} first."
            )
