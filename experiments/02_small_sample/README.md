# Semantic Search — Description Intent

End-to-end pipeline for building ground-truth evaluation datasets for the Acumen semantic search system. The system enables non-technical business users to discover automation recipes using natural language queries.

For the full project proposal see [`Semantic Search for Acumen.md`](Semantic%20Search%20for%20Acumen.md).

---

## Pipeline Sequence

```
data/bt_prod.parquet                          (10,754 recipes, 222 authors)
data/gpt-5.2-*_bt_prod_descriptions_recipe.parquet   (9,764 LLM descriptions)
        │
        ▼  Step 1 — 01_sampling/sample_recipes.py
data/bt_prod_sample.parquet                   (801 recipes, 10 authors)
        │
        ▼  Step 2 — 02_cleaning/clean_pii_recipes.py
02_cleaning/cleaned/
  *_tracking.json                             (payload: connectors, steps, author)
  *_semantic.json                             (text: connector list + step outline)
        │
        ├──▶  Step 3a — 03_step_text/build_step_text.py
        │     03_step_text/step_texts/            (per-step embed text, Category 2)
        │
        └──▶  Step 3b — 04_consistency_check/check_description_consistency.py   (optional QA)
              04_consistency_check/consistency_results.csv
                      │
                      ├──▶  06-pgvector/prepare_pgvector_data.py
                      │     06-pgvector/recipes_for_pgvector.csv          ← seed recipes ready for embedding
                      │
                      ├──▶  Category 1 eval — 05_sythesize_eval_dataset/build_eval_category1_queries.py   [Phase 1]
                      │     05_sythesize_eval_dataset/eval_category1_queries.json
                      │              │
                      │              ▼  05_sythesize_eval_dataset/build_eval_category1_relevance.py   [Phase 2]
                      │              05_sythesize_eval_dataset/eval_category1.csv
                      │                       │
                      │                       ▼  05_sythesize_eval_dataset/build_eval_category1_summary.py   [Phase 3]
                      │                       05_sythesize_eval_dataset/eval_category1_summary.csv   ← final Cat 1 dataset
                      │
                      └──▶  Category 2 eval — 05_sythesize_eval_dataset/build_eval_category2_queries.py   [Phase 1]
                            05_sythesize_eval_dataset/eval_category2_queries.json
                                     │
                                     ▼  05_sythesize_eval_dataset/build_eval_category2_relevance.py   [Phase 2]
                                     05_sythesize_eval_dataset/eval_category2.csv
                                              │
                                              ▼  05_sythesize_eval_dataset/build_eval_category2_summary.py   [Phase 3]
                                              05_sythesize_eval_dataset/eval_category2_summary.csv   ← final Cat 2 dataset
```

---

## Steps

### Step 1 — Sample (`01_sampling/sample_recipes.py`)

Draws a development-sized sample from the full production dataset.

| | |
|---|---|
| **Input** | `data/bt_prod.parquet`, `data/gpt-5.2-*_descriptions_recipe.parquet` |
| **Output** | `data/bt_prod_sample.parquet` (801 rows, 10 authors) |
| **Docs** | [`01_sampling/sampling.md`](01_sampling/sampling.md) |

Filters to recipes with LLM descriptions, then selects the 10 authors with 50–99 recipes each.

---

### Step 2 — Clean (`02_cleaning/clean_pii_recipes.py`)

Parses the nested recipe JSON and writes two files per recipe: structured payload and embed-ready text.

| | |
|---|---|
| **Input** | `data/bt_prod_sample.parquet` |
| **Output** | `02_cleaning/cleaned/<flow_id>_<version_no>_tracking.json`, `..._semantic.json` |
| **Docs** | [`02_cleaning/cleaning-process-pii.md`](02_cleaning/cleaning-process-pii.md), [`02_cleaning/recipe_schema.md`](02_cleaning/recipe_schema.md) |

**`_tracking.json`** — Qdrant payload fields:

| Field | Description |
|---|---|
| `flow_id`, `version_no`, `author_id` | Identity |
| `connectors` | Sorted list of distinct connectors used |
| `steps` | Flat list of steps with keyword, provider, name, depth, parent |

**`_semantic.json`** — Text fields:

| Field | Description |
|---|---|
| `recipe_summary` | Connector list + indented step tree (no `flow_id` — carries no semantic meaning) |
| `steps` | Per-step text entries for Category 2 (step-level) search |

---

### Step 3a — Step embed text (`03_step_text/build_step_text.py`)

Builds per-step embed strings for Category 2 (step-level) search.

| | |
|---|---|
| **Input** | `02_cleaning/cleaned/*_semantic.json` |
| **Output** | `03_step_text/step_texts/<flow_id>_<version_no>_step_texts.json` |

---

### Step 3b — Consistency check (`04_consistency_check/check_description_consistency.py`) — optional QA

Verifies whether the LLM-generated description fields (`usage`, `short_user_intent`, `verbose_user_intent`) are consistent with `recipe_summary` extracted directly from the raw recipe JSON.

| | |
|---|---|
| **Input** | `02_cleaning/cleaned/`, `data/gpt-5.2-*_descriptions_recipe.parquet` |
| **Output** | `04_consistency_check/consistency_results.csv` (one row per recipe) |

---

### Step 4 — pgvector data prep (`06-pgvector/prepare_pgvector_data.py`)

Applies the same seed-selection filters as the evaluation pipeline to select 115 diverse recipes and writes them ready for embedding and pgvector ingestion.

| | |
|---|---|
| **Input** | `02_cleaning/cleaned/*_tracking.json`, `*_semantic.json` |
| **Output** | `06-pgvector/recipes_for_pgvector.csv` (115 rows) |
| **Docs** | [`06-pgvector/README.md`](06-pgvector/README.md) |

| Column | Description |
|---|---|
| `recipe_uid` | `"{author_id}_{flow_id}_v{version_no}"` — unique key |
| `text` | `recipe_summary` — the field to embed |
| `payload` | JSON with all metadata for pgvector filtering |

---

### Category 1 Evaluation (`05_sythesize_eval_dataset/`) — recipe-level, process-oriented queries

A Category 1 query is a broad business-language question — *"Which recipes handle our employee onboarding?"*

| Phase | Script | Output |
|---|---|---|
| 1 | `build_eval_category1_queries.py` | `eval_category1_queries.json` |
| 2 | `build_eval_category1_relevance.py` | `eval_category1.csv` |
| 3 | `build_eval_category1_summary.py` | `eval_category1_summary.csv` ← **final dataset** |

**Relevance scope:** global — all seed recipes from all authors are candidates for every query.

Each recipe in `strong_list` / `weak_list` is identified by `{candidate_author_id}_{flow_id}_v{version_no}` (e.g. `618946_51356784_v3`).

**`eval_category1_summary.csv`** — final dataset, one row per query:

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_q{n}"` |
| `query` | str | Natural-language process-oriented query |
| `strong_count` | int | Number of Strongly Related candidate recipes |
| `strong_list` | str | Comma-separated recipe UIDs rated Strongly Related |
| `weak_count` | int | Number of Weakly Related candidate recipes |
| `weak_list` | str | Comma-separated recipe UIDs rated Weakly Related |

Docs: [`05_sythesize_eval_dataset/README.md`](05_sythesize_eval_dataset/README.md)

---

### Category 2 Evaluation (`05_sythesize_eval_dataset/`) — recipe-level, action-oriented queries

A Category 2 query targets a specific automation outcome — *"Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"*

| Phase | Script | Output |
|---|---|---|
| 1 | `build_eval_category2_queries.py` | `eval_category2_queries.json` |
| 2 | `build_eval_category2_relevance.py` | `eval_category2.csv` |
| 3 | `build_eval_category2_summary.py` | `eval_category2_summary.csv` ← **final dataset** |

**Relevance scope:** global — all seed recipes from all authors are candidates for every query.

Each recipe in `strong_list` / `weak_list` is identified by `{candidate_author_id}_{flow_id}_v{version_no}` (e.g. `618946_51356784_v3`).

**`eval_category2_summary.csv`** — final dataset, one row per query:

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_c2q{n}"` |
| `query` | str | Natural-language action-oriented query |
| `strong_count` | int | Number of Strongly Related candidate recipes |
| `strong_list` | str | Comma-separated recipe UIDs rated Strongly Related |
| `weak_count` | int | Number of Weakly Related candidate recipes |
| `weak_list` | str | Comma-separated recipe UIDs rated Weakly Related |

Docs: [`05_sythesize_eval_dataset/README.md`](05_sythesize_eval_dataset/README.md)

---

## Run Order

```bash
cd /Users/alice/project/semantic_search/description_intent

# Step 1 — sample
python 01_sampling/sample_recipes.py

# Step 2 — clean (generates 02_cleaning/cleaned/)
python 02_cleaning/clean_pii_recipes.py

# Step 3a — step embed text (Category 2)
python 03_step_text/build_step_text.py

# Step 3b — check LLM description consistency (optional QA)
python 04_consistency_check/check_description_consistency.py

# Build supporting DataFrames (run once)
python 05_sythesize_eval_dataset/build_recipe_df.py
python 05_sythesize_eval_dataset/build_step_df.py

# Step 4 — prepare seed recipes for pgvector
python 06-pgvector/prepare_pgvector_data.py

# Category 1 — Phase 1: generate queries, review, then continue
python 05_sythesize_eval_dataset/build_eval_category1_queries.py
python 05_sythesize_eval_dataset/build_eval_category1_relevance.py
python 05_sythesize_eval_dataset/build_eval_category1_summary.py

# Category 2 — Phase 1: generate queries, review, then continue
python 05_sythesize_eval_dataset/build_eval_category2_queries.py
python 05_sythesize_eval_dataset/build_eval_category2_relevance.py
python 05_sythesize_eval_dataset/build_eval_category2_summary.py
```

---

## File Tree

```
description_intent/
│
├── README.md                                         ← this file
├── Semantic Search for Acumen.md                     ← project proposal
│
├── data/                                             ← all input data
│   ├── bt_prod.parquet                               ←   full production recipes (10,754)
│   ├── bt_prod_sample.parquet                        ←   dev sample (801 recipes, 10 authors)
│   ├── gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet  ← LLM recipe descriptions
│   ├── gpt-5.2-2025-12-11_bt_prod_descriptions_step.parquet    ← LLM step descriptions
│   └── edges.json                                    ←   recipe dependency graph
│
├── 01_sampling/                                      ← Step 1
│   ├── sample_recipes.py                             ←   script
│   └── sampling.md                                   ←   documentation
│
├── 02_cleaning/                                      ← Step 2
│   ├── clean_pii_recipes.py                          ←   script
│   ├── cleaning-process-pii.md                       ←   documentation
│   ├── recipe_schema.md                              ←   bt_prod.parquet schema reference
│   └── cleaned/                                      ←   output (801 × 2 JSON files)
│       ├── *_tracking.json                           ←     payload fields
│       └── *_semantic.json                           ←     text fields
│
├── 03_step_text/                                     ← Step 3a (Category 2)
│   ├── build_step_text.py                            ←   script
│   └── step_texts/                                   ←   output (*_step_texts.json)
│
├── 04_consistency_check/                             ← Step 3b (optional QA)
│   ├── check_description_consistency.py              ←   script
│   ├── consistency_results.csv                       ←   output (one row per recipe)
│   └── consistency_checkpoint.json                   ←   resume checkpoint
│
├── 06-pgvector/                                          ← Step 4: pgvector ingestion data
│   ├── README.md                                         ←   documentation
│   ├── prepare_pgvector_data.py                          ←   script
│   └── recipes_for_pgvector.csv                          ←   output (115 seeds, text + payload)
│
└── 05_sythesize_eval_dataset/                                          ← Category 1 & 2 evaluation datasets
    ├── README.md                                     ←   documentation
    ├── eval_utils.py                                 ←   shared utilities
    ├── build_recipe_df.py                            ←   supporting DataFrame: recipes
    ├── build_step_df.py                              ←   supporting DataFrame: steps
    │
    ├── build_eval_category1_queries.py               ←   Cat 1 Phase 1
    ├── build_eval_category1_relevance.py             ←   Cat 1 Phase 2
    ├── build_eval_category1_summary.py               ←   Cat 1 Phase 3
    │
    ├── build_eval_category2_queries.py               ←   Cat 2 Phase 1
    ├── build_eval_category2_relevance.py             ←   Cat 2 Phase 2
    ├── build_eval_category2_summary.py               ←   Cat 2 Phase 3
    │
    ├── recipe_df.parquet                             ←   recipe-level DataFrame (801 × 14)
    ├── step_df.parquet                               ←   step-level DataFrame (~8,010 × 15)
    │
    ├── eval_category1_queries.json                   ←   Cat 1 Phase 1 output
    ├── eval_category1.csv                            ←   Cat 1 Phase 2 output
    ├── eval_category1_summary.csv                    ←   Cat 1 Phase 3 output ← final dataset
    ├── eval_category1_detail.csv                     ←   Cat 1 Phase 3: per-pair detail with recipe summaries
    ├── eval_category1_query_overlaps.csv             ←   Cat 1 Phase 3: queries sharing identical strong_list
    ├── eval_category1_checkpoint.json                ←   Cat 1 Phase 2 resume state
    │
    ├── eval_category2_queries.json                   ←   Cat 2 Phase 1 output
    ├── eval_category2.csv                            ←   Cat 2 Phase 2 output
    ├── eval_category2_summary.csv                    ←   Cat 2 Phase 3 output ← final dataset
    ├── eval_category2_detail.csv                     ←   Cat 2 Phase 3: per-pair detail with recipe summaries
    ├── eval_category2_query_overlaps.csv             ←   Cat 2 Phase 3: queries sharing identical strong_list
    ├── eval_category2_diagnostic.txt                 ←   Cat 2 Phase 3: full source+candidate summaries for all queries
    └── eval_category2_checkpoint.json                ←   Cat 2 Phase 2 resume state
```
