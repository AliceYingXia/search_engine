# 02_synthesize_data — Evaluation Dataset Pipeline

Synthesises ground-truth evaluation datasets for semantic search over Workato automation recipes.

**Search scope:** global across all authors (no tenant isolation).  
**Source data:** `01_process_data/cleaned/recipe_summaries.parquet` — all recipes from the 30 authors selected in `01_process_data` (top 30 authors by recipe count from the described recipe pool — see [process_data.md](../01_process_data/process_data.md)). Uses `recipe_summary_with_comment`.

---

## Query Categories

| Category       | Style                                                                                      | Example query                                                                   |
| -------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| **Category 1** | Process-oriented — broad business workflow, no system names                                | _"Which recipes handle our employee onboarding?"_                               |
| **Category 2** | Action-oriented — names systems, trigger, and outcome                                      | _"Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"_ |
| **Category 3** | Dependency-oriented — names a specific technical artifact; used for change-impact analysis | _"Which recipes use the Workday Call Operation: Add Additional Job action?"_    |

All categories run through the same pipeline. The only difference is the prompt passed via `QueryStyle`.

---

## Run Order

### One-shot (all phases)

```bash
cd pipeline/02_synthesize_data

python run.py --style cat1   # Category 1
python run.py --style cat2   # Category 2
python run.py --style cat3   # Category 3
python run.py --style all    # all categories back-to-back
```

### Step-by-step (recommended — allows review between phases)

```bash
cd pipeline/02_synthesize_data

# Phase 0 — select seed recipes and write recipes_for_pgvector.csv
# Style-independent: run once, shared by all categories and 03_evaluate_postgre.
python run.py --style cat1 --phase prepare

# Phase 1 — generate queries (one per seed recipe)
python run.py --style cat2 --phase queries
# → Review the printed queries before continuing.

# Phase 1.5 — select 50 diverse queries via embedding similarity
python run.py --style cat2 --phase select
# → Check the printed selection. If fewer than 50 were selected,
#   raise _SIM_THRESHOLD in pipeline/phases/select_queries.py (e.g. 0.85 → 0.90)
#   and re-run this phase.

# Phase 2 — score every (query, recipe) pair with two LLMs
python run.py --style cat2 --phase relevance

# Phase 2.5 — resolve model disagreements
python run.py --style cat2 --phase adjudicate

# Phase 3 — filter, aggregate, and export the final dataset
python run.py --style cat2 --phase dataset

# Eval — GPT-5.2 quality review of sampled examples
python run.py --style cat2 --phase evaluate
```

**Styles:** `cat1` | `cat2` | `cat3` | `all`  
**Phases:** `prepare` | `queries` | `select` | `relevance` | `adjudicate` | `dataset` | `evaluate` (comma-separated, or omit for all)

> **Note:** When running `--style all`, the `prepare` phase runs once per style invocation but is idempotent — it overwrites the same CSV each time with identical output.

---

## File Structure

```
02_synthesize_data/
├── config.py                        # Paths, model names, hyperparameters
├── utils.py                         # Shared utilities: LLM calls, data loading,
│                                    # seed selection, dataset helpers
├── run.py                           # CLI entry point
│
└── pipeline/
    ├── query_styles.py              # QueryStyle dataclass + CAT1, CAT2, CAT3 instances
    ├── synthesize_pipeline.py       # SynthesizePipeline class — orchestrates all phases
    └── phases/
        ├── prepare_corpus.py        # Phase 0   — PrepareCorpus class
        ├── queries.py               # Phase 1   — build_queries()
        ├── select_queries.py        # Phase 1.5 — select_queries()
        ├── relevance.py             # Phase 2   — exhaust_relevance()
        ├── adjudicate.py            # Phase 2.5 — adjudicate_disagreements()
        ├── dataset.py               # Phase 3   — filter_dataset()
        └── evaluate.py              # Eval      — evaluate_examples()
```

---

## Phase Details

### Phase 0 — Prepare Corpus (`phases/prepare_corpus.py`)

Selects diverse seed recipes for every author and writes `recipes_for_pgvector.csv`. This file is the single source of seeds used by all downstream phases — seed selection runs exactly once here rather than being repeated in each phase.

**Seed selection rules:**

1. Identify infrastructure connectors (present in >50% of an author's recipes) and exclude them from diversity scoring.
2. Rank recipes by total distinct connectors (desc), then step count (desc).
3. Skip recipes with an empty signal connector set (only infra connectors).
4. Skip recipes with fewer than 3 total distinct connectors.
5. Greedily select every recipe whose signal connectors overlap ≤50% with all already-selected seeds.

**Style-independent:** the same CSV is shared by all query categories and by `03_evaluate_postgre`. Safe to re-run — output is deterministic.

**Input:** `01_process_data/cleaned/recipe_summaries.parquet`  
**Output:** `recipes_for_pgvector.csv`

---

### Phase 1 — Build Queries (`phases/queries.py`)

For each seed recipe (loaded from `recipes_for_pgvector.csv`), calls GPT-5.2 (`temperature=0.4`) to generate one natural-language query per seed.

**Input:** `recipes_for_pgvector.csv` (requires `prepare` phase), `.env`  
**Output:** `{name}_queries.json`

```json
{
  "query_id": "618946_q1",
  "author_id": 618946,
  "source_flow_id": 51356784,
  "source_version_no": 3,
  "source_connectors": ["salesforce", "slack"],
  "query": "Which recipes handle our employee onboarding?"
}
```

---

### Phase 1.5 — Select Queries (`phases/select_queries.py`)

Selects 50 diverse queries per category from the full generated set.

**How it works:**

1. Ranks all queries by length — longest first (longer queries tend to be more specific and informative).
2. Embeds all queries in batches of 20 using **Qwen3-Embedding-8B** via Baseten.
3. Greedily selects queries longest-first: a candidate is kept only if its cosine similarity to every already-selected query is ≤ 0.5. Shorter queries that are too similar to a longer one are dropped.
4. Stops once 50 queries are selected.

**Input:** `{name}_queries.json`  
**Output:** `{name}_selected_queries.json`

> If `{name}_selected_queries.json` exists, Phase 2 will use it automatically instead of `{name}_queries.json`.

**Embedding model:** `Qwen/Qwen3-Embedding-8B` — requires `BASETEN_API_KEY` in `.env`.

---

### Phase 2 — Exhaust Relevance (`phases/relevance.py`)

Scores every (query, seed recipe) pair using **two independent models**: GPT-5.2 and Claude. Each query is scored against the full global seed pool (all authors combined).

**How it works:**

- The global seed pool (~200+ recipes) is shuffled randomly per query to reduce position bias, then split into chunks of 20.
- Each chunk is sent to both models independently in separate API calls.
- Labels from all chunks are merged per model.
- Rows where **both** models return `Not Related` are excluded. All other rows are written to the output CSV.
- Progress is checkpointed per query — safe to interrupt and resume.

**Models:**
| Model | ID |
|---|---|
| GPT-5.2 | `azure/gpt-5.2` |
| Claude | `bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0` |

**Relevance labels vary by category** — the definitions are injected from `QueryStyle.relevance_definitions`:

| Label              | Cat 1 & 2 meaning                                     | Cat 3 meaning                                                                 |
| ------------------ | ----------------------------------------------------- | ----------------------------------------------------------------------------- |
| `Strongly Related` | Primary component of the process/automation described | Recipe directly uses/references the exact artifact named                      |
| `Weakly Related`   | Supporting or peripheral role                         | Recipe interacts with the same connector/system but not the specific artifact |
| `Not Related`      | No meaningful connection — excluded from output       | No meaningful connection — excluded from output                               |

**Input:** `{name}_selected_queries.json` (preferred) or `{name}_queries.json`, cleaned recipe data  
**Output:** `{name}_raw.csv`, `{name}_checkpoint.json`

---

### Phase 2.5 — Adjudicate Disagreements (`phases/adjudicate.py`)

Resolves cases where the two models disagree — one says `Strongly Related`, the other says `Weakly Related` (S/W or W/S). A focused third LLM call is made for each disagreement, showing both model labels alongside the recipe summary.

**Resolution logic:**
| Model A | Model B | Action |
|---|---|---|
| Strongly Related | Strongly Related | `relevance_final = Strongly Related` (no call) |
| Weakly Related | Weakly Related | `relevance_final = Weakly Related` (no call) |
| Strongly Related | Weakly Related | Adjudication LLM call → `relevance_final` |
| Weakly Related | Strongly Related | Adjudication LLM call → `relevance_final` |

- Progress is checkpointed per query.
- If adjudication fails for a row after all retries, falls back to the stronger of the two labels.

**Input:** `{name}_raw.csv`  
**Output:** `{name}_adjudicated.csv` (same columns + `relevance_final`), `{name}_adjudicate_checkpoint.json`

---

### Phase 3 — Filter Dataset (`phases/dataset.py`)

Filters queries, aggregates candidates into strong/weak lists, and generates inspection artefacts.

**Filter rule:** A query is kept only if its source recipe is rated `Strongly Related` in `relevance_final` (or by both models if no adjudication was run). Queries that fail this check are printed and dropped.

**Strong vs weak list logic (using `relevance_final`):**
| `relevance_final` | List |
|---|---|
| `Strongly Related` | `strong_list` |
| `Weakly Related` | `weak_list` |

**Outputs:**

| File                              | Description                                                                  |
| --------------------------------- | ---------------------------------------------------------------------------- |
| `{name}_dataset.csv`              | One row per query — `strong_list`, `strong_count`, `weak_list`, `weak_count` |
| `{name}_detail.csv`               | Every row enriched with `recipe_summary` for manual inspection               |
| `{name}_examples/example_N.xlsx`  | Up to 50 sampled queries as 3-sheet Excel files                              |
| `{name}_examples/all_queries.txt` | All queries grouped by author                                                |
| `{name}_strong_count.png`         | Histogram of strong list sizes                                               |
| `{name}_weak_count.png`           | Histogram of weak list sizes                                                 |

**Excel file structure (per example):**

- **Sheet 1 — Query & Candidates:** query metadata + all strong/weak candidates with labels from both models
- **Sheet 2 — Source Summary:** query text and source recipe summary
- **Sheet 3 — Candidate Summaries:** recipe summaries for all strong/weak candidates

**Recipe UID format:** `{candidate_author_id}_{flow_id}_v{version_no}`  
Example: `618946_51356784_v3`

---

### Eval — Evaluate Examples (`phases/evaluate.py`)

Uses GPT-5.2 to independently review the sampled example Excel files. For each file:

1. **Query quality** — rates Clarity and Specificity (`Good` / `Acceptable` / `Poor`) with a one-sentence comment.
2. **Candidate label review** — for each strong/weak candidate, verdict is `Agree` or `Reclassify` (with suggested label and reason).

**Input:** `{name}_examples/example_*.xlsx`  
**Output:** `{name}_examples/evaluation_results.xlsx`

| Sheet            | Columns                                                                                                  |
| ---------------- | -------------------------------------------------------------------------------------------------------- |
| Query Quality    | `example_file`, `query_id`, `query`, `clarity`, `specificity`, `comment`                                 |
| Candidate Labels | `example_file`, `query_id`, `recipe_uid`, `assigned_label`, `gpt52_verdict`, `suggested_label`, `reason` |

---

## Adding a New Query Category

Define a new `QueryStyle` instance in `pipeline/query_styles.py` and register it in `run.py`. No other code changes needed.

```python
# pipeline/query_styles.py
CAT3 = QueryStyle(
    name="category3",
    query_id_prefix="c3q",
    system_prompt=_CAT3_SYSTEM_PROMPT,
    relevance_definitions=_CAT3_RELEVANCE_DEFINITIONS,
    quality_system_prompt=_CAT3_QUALITY_PROMPT,
)
```

```python
# run.py
styles = {"cat1": [CAT1], "cat2": [CAT2], "cat3": [CAT3], "all": [CAT1, CAT2, CAT3]}[args.style]
```

---

## Configuration (`config.py`)

| Constant                | Value                                                | Description                                                             |
| ----------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------- |
| `MODEL_GPT52`           | `azure/gpt-5.2`                                      | Primary model for query generation, relevance, adjudication, evaluation |
| `MODEL_CLAUDE`          | `bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0` | Second model for relevance scoring                                      |
| `CHUNK_SIZE`            | `20`                                                 | Max recipes per LLM relevance call                                      |
| `MAX_CONNECTOR_OVERLAP` | `0.50`                                               | Max signal-connector overlap between any two seeds                      |
| `INFRA_CONNECTOR_FREQ`  | `0.50`                                               | Threshold for identifying infrastructure connectors                     |
| `MIN_CONNECTORS`        | `3`                                                  | Minimum total connectors required for a seed recipe                     |
| `LLM_MAX_ATTEMPTS`      | `3`                                                  | Total LLM call attempts (1 original + 2 retries)                        |
| `LLM_BACKOFF_BASE`      | `2`                                                  | Exponential backoff base in seconds (2s, 4s)                            |
| `PGVECTOR_CSV_PATH`     | `BASE_DIR / "recipes_for_pgvector.csv"`              | Output path for the corpus CSV (shared with `03_evaluate_postgre`)   |

---

## Runtime State Files

| File                                | Description                                                                    |
| ----------------------------------- | ------------------------------------------------------------------------------ |
| `recipes_for_pgvector.csv`          | Selected seed recipes — produced by Phase 0, consumed by Phase 1 and `03`     |
| `{name}_queries.json`               | All generated queries from Phase 1                                             |
| `{name}_selected_queries.json`      | 50 selected queries from Phase 1.5 — delete to re-run selection                |
| `{name}_checkpoint.json`            | Completed query IDs for Phase 2 — delete to restart from scratch               |
| `{name}_adjudicate_checkpoint.json` | Completed query IDs for Phase 2.5 — delete to re-adjudicate                    |
