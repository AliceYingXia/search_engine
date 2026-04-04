# 05_sythesize_eval_dataset — Category 1 & Category 2 Evaluation Datasets

Ground-truth evaluation datasets for semantic search over Workato automation recipes.

**Search scope:** global across all authors (no tenant isolation).
**Source data:** 801 recipes, 10 authors.

| Category | Query type | Retrieval unit | Example query |
|---|---|---|---|
| **Category 1** | Process-oriented | Recipe | *"Which recipes handle our employee onboarding?"* |
| **Category 2** | Action-oriented | Recipe | *"Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"* |

---

## Files

### Shared utilities

| File | Purpose |
|---|---|
| `eval_utils.py` | Shared functions: `make_openai_client`, `load_tracking_data`, `get_infra_connectors`, `select_recipe_seeds`. Reads `API_KEY` and `BASE_URL` from `RAG_Json/.env`. |

### Supporting DataFrames

| Script | Input → Output |
|---|---|
| `build_recipe_df.py` | tracking + semantic + descriptions → `recipe_df.parquet` (801 × 14) |
| `build_step_df.py` | tracking steps + semantic steps + step_texts + step descriptions → `step_df.parquet` (~8,010 × 15) |

### Category 1 scripts

| Script | Phase | Input → Output |
|---|---|---|
| `build_eval_category1_queries.py` | Phase 1 | tracking + semantic → `eval_category1_queries.json` |
| `build_eval_category1_relevance.py` | Phase 2 | queries JSON + tracking + semantic → `eval_category1.csv` |
| `category_1_eval_dataset.py` | Phase 3 | `eval_category1.csv` → `category1_eval_dataset.csv` ← **final dataset** |
| `evaluate_category1_examples.py` | Evaluation | `category1_examples/*.xlsx` → `category1_examples/evaluation_results.xlsx` |

### Category 2 scripts

| Script | Phase | Input → Output |
|---|---|---|
| `build_eval_category2_queries.py` | Phase 1 | `step_df.parquet` + tracking → `eval_category2_queries.json` |
| `build_eval_category2_relevance.py` | Phase 2 | queries JSON + tracking + semantic → `eval_category2.csv` |
| `category_2_eval_dataset.py` | Phase 3 | `eval_category2.csv` → `category2_eval_dataset.csv` ← **final dataset** |
| `evaluate_category2_examples.py` | Evaluation | `category2_examples/*.xlsx` → `category2_examples/evaluation_results.xlsx` |

### Data outputs

#### `recipe_df.parquet`

One row per recipe version (801 rows × 14 columns). Combines tracking payload with text fields for use in eval scripts.

| Column | Type | Description |
|---|---|---|
| `flow_id` | int | Recipe identifier |
| `version_no` | int | Recipe version |
| `author_id` | int | Recipe owner |
| `connectors` | list[str] | Sorted list of distinct connectors used |
| `step_count` | int | Total number of steps in the recipe |
| `has_comment` | bool | Whether any step carries a user comment |
| `recipe_summary` | str | Connector list + indented step tree (from `*_semantic.json`) |
| `usage` | str | LLM-generated usage description |
| `short_user_intent` | str | LLM-generated short user intent |
| `verbose_user_intent` | str | LLM-generated verbose user intent |
| `title` | str | Recipe title |
| `description` | str | Recipe description |
| … | | (remaining columns from tracking/semantic JSON) |

#### `step_df.parquet`

One row per step across all recipes (~8,010 rows × 18 columns). Combines tracking step payload with semantic step fields, embed text, and step-level LLM descriptions.

| Column | Type | Description |
|---|---|---|
| `flow_id` | int | Recipe identifier |
| `version_no` | int | Recipe version |
| `author_id` | int | Recipe owner |
| `as` | str | Step identifier handle (unique within a recipe) |
| `number` | int | Step order number (0-indexed) |
| `keyword` | str | Step type (e.g. `action`, `if`, `foreach`) |
| `provider` | str | Connector name (e.g. `salesforce`, `slack`) |
| `name` | str | Action name within the connector |
| `parent_as` | str | `as` handle of the parent step (None for root steps) |
| `parent_keyword` | str | Keyword of the parent step |
| `depth` | int | Nesting depth (0 = top-level) |
| `has_comment` | bool | Step-level flag: whether this step carries a user comment |
| `block_context` | str | Description of the enclosing block (None if top-level) |
| `prev_step` | dict | `{keyword, provider, name}` of the preceding step |
| `next_step` | dict | `{keyword, provider, name}` of the following step |
| `step_text` | str | Embed-ready step text (from `03_step_text/`) |
| `description` | str | LLM-generated technical prose describing what this step does |
| `step_intent` | str | LLM-generated one-line intent description of this step |

#### `eval_category1_queries.json`

Generated Category 1 queries. One entry per diverse seed recipe, one query per entry (~219 entries).

| Field | Type | Description |
|---|---|---|
| `query_id` | str | `"{author_id}_q{n}"` — unique query identifier |
| `author_id` | int | Author whose seed recipe generated this query |
| `source_flow_id` | int | `flow_id` of the seed recipe used to generate the query |
| `source_version_no` | int | `version_no` of the seed recipe |
| `source_connectors` | list[str] | Connectors of the seed recipe |
| `query` | str | Generated natural-language query |

#### `eval_category1.csv`

One row per (query, candidate recipe) pair assessed by two models independently. Rows where **both** models return `Not Related` are excluded; all other rows are kept with both labels recorded.

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_q{n}"` |
| `query` | str | The Category 1 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `flow_id` | int | Candidate recipe being judged |
| `version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |

#### `category1_eval_dataset.csv`

Final Category 1 dataset. One row per query. Only queries where the source recipe appears in `strong_list` are retained.

| Column | Type | Description |
|---|---|---|
| `source_author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_q{n}"` |
| `query` | str | The Category 1 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `strong_list` | str | Comma-separated recipe UIDs agreed as Strongly Related by both models |
| `strong_count` | int | Number of candidates in the strong list |
| `weak_list` | str | Comma-separated recipe UIDs that both models rated positively but did not both rate as Strong |
| `weak_count` | int | Number of candidates in the weak list |

Recipe UID format: `{candidate_author_id}_{flow_id}_v{version_no}` (e.g. `618946_51356784_v3`).

#### `eval_category1_detail.csv`

`eval_category1.csv` enriched with `recipe_uid` and `recipe_summary` for manual auditing. One row per (query, candidate recipe) pair. Generated by `category_1_eval_dataset.py`.

| Column | Type | Description |
|---|---|---|
| `source_author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_q{n}"` |
| `query` | str | The Category 1 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `candidate_flow_id` | int | Candidate recipe being judged |
| `candidate_version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `candidate_connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `recipe_uid` | str | `{candidate_author_id}_{candidate_flow_id}_v{candidate_version_no}` |
| `recipe_summary` | str | Full recipe summary of the candidate |

#### `category1_examples/evaluation_results.xlsx`

GPT-5.2 evaluation of the 5 sampled Category 1 example files. Generated by `evaluate_category1_examples.py`.

| Sheet | Columns | Description |
|---|---|---|
| **Query Quality** | `example_file`, `query_id`, `query`, `clarity`, `specificity`, `comment` | Per-query quality ratings (`Good` / `Acceptable` / `Poor`) |
| **Candidate Labels** | `example_file`, `query_id`, `recipe_uid`, `assigned_label`, `gpt52_verdict`, `suggested_label`, `reason` | Per-candidate verdict (`Agree` / `Reclassify`) with reason |

#### `eval_category2_queries.json`

Generated Category 2 queries. One entry per diverse seed recipe (~219 entries).

| Field | Type | Description |
|---|---|---|
| `query_id` | str | `"{author_id}_c2q{n}"` — unique query identifier |
| `author_id` | int | Author whose seed recipe generated this query |
| `source_flow_id` | int | `flow_id` of the seed recipe used to generate the query |
| `source_version_no` | int | `version_no` of the seed recipe |
| `source_connectors` | list[str] | Connectors of the seed recipe |
| `source_step_as_list` | list[str] | `as` handles of all steps in the seed recipe — cross-reference to `step_df.parquet` via `(source_flow_id, source_version_no, as)` |
| `query` | str | Generated action-oriented natural-language query |

#### `eval_category2.csv`

One row per (query, candidate recipe) pair assessed by two models independently. Rows where **both** models return `Not Related` are excluded; all other rows are kept with both labels recorded.

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_c2q{n}"` |
| `query` | str | The Category 2 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `flow_id` | int | Candidate recipe being judged |
| `version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |

#### `category2_eval_dataset.csv`

Final Category 2 dataset. One row per query. Only queries where the source recipe appears in `strong_list` are retained.

| Column | Type | Description |
|---|---|---|
| `source_author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_c2q{n}"` |
| `query` | str | The Category 2 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `strong_list` | str | Comma-separated recipe UIDs agreed as Strongly Related by both models |
| `strong_count` | int | Number of candidates in the strong list |
| `weak_list` | str | Comma-separated recipe UIDs that both models rated positively but did not both rate as Strong |
| `weak_count` | int | Number of candidates in the weak list |

Recipe UID format: `{candidate_author_id}_{flow_id}_v{version_no}` (e.g. `618946_51356784_v3`).

#### `eval_category2_detail.csv`

`eval_category2.csv` enriched with `recipe_uid` and `recipe_summary` for manual auditing. One row per (query, candidate recipe) pair. Generated by `category_2_eval_dataset.py`.

| Column | Type | Description |
|---|---|---|
| `source_author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_c2q{n}"` |
| `query` | str | The Category 2 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `candidate_flow_id` | int | Candidate recipe being judged |
| `candidate_version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `candidate_connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `recipe_uid` | str | `{candidate_author_id}_{candidate_flow_id}_v{candidate_version_no}` |
| `recipe_summary` | str | Full recipe summary of the candidate |

#### `category2_examples/evaluation_results.xlsx`

GPT-5.2 evaluation of the 5 sampled Category 2 example files. Generated by `evaluate_category2_examples.py`.

| Sheet | Columns | Description |
|---|---|---|
| **Query Quality** | `example_file`, `query_id`, `query`, `clarity`, `specificity`, `comment` | Per-query quality ratings (`Good` / `Acceptable` / `Poor`) |
| **Candidate Labels** | `example_file`, `query_id`, `recipe_uid`, `assigned_label`, `gpt52_verdict`, `suggested_label`, `reason` | Per-candidate verdict (`Agree` / `Reclassify`) with reason |

### Runtime state

| File | Description |
|---|---|
| `eval_category1_checkpoint.json` | Completed Category 1 query IDs — delete to restart Phase 2 from scratch |
| `eval_category2_checkpoint.json` | Completed Category 2 query IDs — delete to restart Phase 2 from scratch |

---

## Run Order

```bash
cd "/Users/alice/project/semantic_search/RAG_Json/generation of evaluation dataset with Sasha data"

# Supporting DataFrames (run once)
python 05_sythesize_eval_dataset/build_recipe_df.py
python 05_sythesize_eval_dataset/build_step_df.py

# Category 1 — Phase 1: generate queries, then REVIEW before continuing
python 05_sythesize_eval_dataset/build_eval_category1_queries.py

# Category 1 — Phase 2: run only after approving the queries above
python 05_sythesize_eval_dataset/build_eval_category1_relevance.py

# Category 1 — Phase 3: synthesise final dataset
python 05_sythesize_eval_dataset/category_1_eval_dataset.py

# Category 1 — Evaluation (optional): GPT-5.2 spot-check of 5 sampled examples
python 05_sythesize_eval_dataset/evaluate_category1_examples.py

# Category 2 — Phase 1: generate queries, then REVIEW before continuing
python 05_sythesize_eval_dataset/build_eval_category2_queries.py

# Category 2 — Phase 2: run only after approving the queries above
python 05_sythesize_eval_dataset/build_eval_category2_relevance.py

# Category 2 — Phase 3: synthesise final dataset
python 05_sythesize_eval_dataset/category_2_eval_dataset.py

# Category 2 — Evaluation (optional): GPT-5.2 spot-check of 5 sampled examples
python 05_sythesize_eval_dataset/evaluate_category2_examples.py
```

---

## Category 1 Detail

### Seed selection

For each author, seed recipes are selected using `eval_utils.select_recipe_seeds()`:

1. Identify infrastructure connectors (present in >50% of the author's recipes).
2. Rank recipes by total distinct connectors desc, step_count desc.
3. Skip recipes with empty signal connector set (only infra connectors).
4. Skip recipes with fewer than 3 total distinct connectors.
5. Greedily pick every remaining recipe whose *signal* connector set overlaps ≤50% with every already-selected seed.

**Seed counts per author (after fixes):**

| Author | Recipes | Infra excluded |
|---|---|---|
| 206503 | 74 | `workato_db_table` |
| 618946 | 96 | `byin_workato_recipe_ops_connector` |
| 973497 | 90 | `workato_recipe_function`, `workato_variable` |
| 1873345 | 80 | `workato_recipe_function` *(Salesforce-heavy catalog)* |
| 2136196 | 70 | `salesforce`, `workato_recipe_function` |
| 2973760 | 95 | *(none — naturally diverse)* |
| 3000083 | 79 | `salesforce`, `workato_recipe_function`, `workato_variable` |
| 3165547 | 73 | `lookup_table`, `workato_recipe_function` |
| 3511776 | 71 | `snowflake`, `workato_recipe_function`, `workato_variable` |
| 5770830 | 73 | `workato_genie` |

**LLM settings (query gen):** `azure/gpt-5.2` | temperature 0.4 | max tokens 120
**LLM settings (relevance):** `azure/gpt-5.2` + `bedrock/claude-sonnet-4` | temperature 0.0 | max tokens 2000 | chunk size 20

### Relevance scope

Phase 2 assesses against a **global seed pool** — all seed recipes from all authors combined, not just those belonging to the query's author. This enables cross-author retrieval evaluation.

### Recipe unique ID format

`{candidate_author_id}_{flow_id}_v{version_no}` — used in `strong_list` / `weak_list`

`candidate_author_id` is the author who **owns** the candidate recipe (not necessarily the author who generated the query).

Example: `618946_51356784_v3` — recipe 51356784 (version 3) owned by author 618946.

### `eval_category1_queries.json` schema

| Field | Type | Description |
|---|---|---|
| `query_id` | str | `"{author_id}_q{n}"` — unique query identifier |
| `author_id` | int | Author whose seed recipe generated this query |
| `source_flow_id` | int | `flow_id` of the seed recipe used to generate the query |
| `source_version_no` | int | `version_no` of the seed recipe |
| `source_connectors` | list[str] | Connectors of the seed recipe |
| `query` | str | Generated natural-language query |

```json
[
  {
    "query_id":           "618946_q1",
    "author_id":          618946,
    "source_flow_id":     51356784,
    "source_version_no":  3,
    "source_connectors":  ["salesforce", "slack", "workato_recipe_function"],
    "query":              "Which recipes handle our employee onboarding process?"
  }
]
```

### `eval_category1.csv` schema

One row per (query, candidate recipe) pair assessed by two models independently. Rows where **both** models return `Not Related` are excluded; all other rows are kept with both labels recorded.

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_q{n}"` |
| `query` | str | The Category 1 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `flow_id` | int | Candidate recipe being judged |
| `version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |

### `eval_category1_detail.csv` schema

See schema under [Data outputs](#eval_category1_detailcsv) above.

### `category1_eval_dataset.md`

Detailed documentation of the Category 1 dataset: pipeline steps, labelling rules, strong/weak list construction logic, output schema, and candidate count distribution plots.

---

## Category 2 Detail

### Seed selection

Category 2 uses the same seed recipes as Category 1 (via `select_recipe_seeds()`).
For each seed recipe, both the `recipe_summary` and all step intents (from `step_df.parquet`)
are passed to the LLM to generate one action-oriented query per recipe.

**Relevance scope:** global seed pool — all seed recipes from all authors combined (same as Category 1).

**LLM settings (query gen):** `azure/gpt-5.2` | temperature 0.4 | max tokens 120
**LLM settings (relevance):** `azure/gpt-5.2` + `bedrock/claude-sonnet-4` | temperature 0.0 | max tokens 2000 | chunk size 20

### Query style

Category 2 queries are action-specific and name concrete systems, triggers, and outcomes:
- *"Which recipe creates a NetSuite vendor bill when a PO is approved in Coupa?"*
- *"Is there an automation that sends a Slack notification when an invoice is overdue?"*
- *"Find the recipe that escalates overdue approvals to a manager after 48 hours."*

Category 1 queries describe broad business processes in plain language without naming systems.
Category 2 queries describe specific automations with system/trigger/outcome detail.

### Recipe unique ID format

`{candidate_author_id}_{flow_id}_v{version_no}` — same format as Category 1.

### `eval_category2_queries.json` schema

Generated Category 2 queries. One entry per diverse seed recipe (~219 entries).

| Field | Type | Description |
|---|---|---|
| `query_id` | str | `"{author_id}_c2q{n}"` — unique query identifier |
| `author_id` | int | Author whose seed recipe generated this query |
| `source_flow_id` | int | `flow_id` of the seed recipe used to generate the query |
| `source_version_no` | int | `version_no` of the seed recipe |
| `source_connectors` | list[str] | Connectors of the seed recipe |
| `source_step_as_list` | list[str] | `as` handles of all steps in the seed recipe — cross-reference to `step_df.parquet` via `(source_flow_id, source_version_no, as)` |
| `query` | str | Generated action-oriented natural-language query |

```json
[
  {
    "query_id":             "618946_c2q1",
    "author_id":            618946,
    "source_flow_id":       51356784,
    "source_version_no":    3,
    "source_connectors":    ["salesforce", "slack", "workato_recipe_function"],
    "source_step_as_list":  ["8546a8b1", "3f2c1d9e", "a1b2c3d4"],
    "query":                "Which recipe creates a Salesforce opportunity and notifies the sales team in Slack when a deal closes?"
  }
]
```

### `eval_category2.csv` schema

One row per (query, candidate recipe) pair assessed by two models independently. Rows where **both** models return `Not Related` are excluded; all other rows are kept with both labels recorded.

| Column | Type | Description |
|---|---|---|
| `author_id` | int | Author who generated the query |
| `query_id` | str | `"{author_id}_c2q{n}"` |
| `query` | str | The Category 2 NL query |
| `source_flow_id` | int | Seed recipe that generated this query |
| `flow_id` | int | Candidate recipe being judged |
| `version_no` | int | Version of the candidate recipe |
| `candidate_author_id` | int | Author who owns the candidate recipe |
| `connectors` | str | Comma-separated connectors of the candidate |
| `relevance_gpt52` | str | Label from `azure/gpt-5.2`: `Strongly Related`, `Weakly Related`, or `Not Related` |
| `relevance_claude` | str | Label from `bedrock/claude-sonnet-4`: `Strongly Related`, `Weakly Related`, or `Not Related` |

### `eval_category2_detail.csv` schema

See schema under [Data outputs](#eval_category2_detailcsv) above.

### `category2_eval_dataset.md`

Detailed documentation of the Category 2 dataset: pipeline steps, labelling rules, strong/weak list construction logic, output schema, and candidate count distribution plots.

---

## Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| Seed selection criterion | Most distinct connectors | Broader connector coverage → richer process-level queries |
| Seeds per author | No cap | Maximises recall coverage |
| Infrastructure connector threshold | >50% frequency | Boilerplate connectors inflate similarity between unrelated recipes |
| Minimum connector count | 3 total | Recipes with 1–2 connectors are too narrow for process-level queries |
| Signal-connector overlap limit | 50% | Prevents near-duplicate seeds |
| Cat 1 relevance scope | Global seed pool (all authors) | Per-author pool is too small; global pool enables cross-author retrieval evaluation |
| Cat 2 query input | recipe_summary + step intents | Step intents give the LLM concrete actions to reference; summary provides overall context |
| Cat 2 query style | Action-specific (names systems, trigger, outcome) | Complements Cat 1 process queries; tests retrieval under more specific phrasing |
| Cat 2 relevance scope | Global seed pool (all authors) | Same as Cat 1 — enables cross-author retrieval evaluation |
| Chunk size | 20 per call | Guards against "lost in the middle" degradation |
| Temperature (query gen) | 0.4 | Slight variation to avoid identical phrasing |
| Temperature (relevance) | 0.0 | Deterministic labelling for reproducibility |
| Relevance models | `azure/gpt-5.2` + `bedrock/claude-sonnet-4` | Two independent judges surface disagreements; rows excluded only when both say Not Related |
| Not Related rows | Excluded only when both models agree | Rows where at least one model finds signal are retained for downstream reconciliation |
| Structural steps excluded | `else`, `try`, `stop`, `repeat` | Containers/terminators with no meaningful action |
