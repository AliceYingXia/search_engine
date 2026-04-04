# Category 1 Evaluation Dataset

## Overview

`category1_eval_dataset.csv` is the final evaluation dataset for Category 1 queries. It contains one row per query, with the strong and weak candidate lists determined by two independent LLM judges.

---

## How Queries Are Generated

Queries are generated in two earlier pipeline steps before this file is produced.

**Step 1 — Seed recipe selection** (`build_eval_category1_queries.py`)

For each author, a set of diverse seed recipes is selected using a greedy algorithm:
- Recipes are ranked by number of distinct connectors and step count (descending).
- Infrastructure connectors — those present in more than 50% of an author's recipes (e.g. `workato_recipe_function`, `workato_variable`) — are excluded from the diversity check to avoid inflating similarity between otherwise unrelated recipes.
- A recipe is selected only if its signal connector set overlaps ≤ 50% with every already-selected seed.
- Recipes with fewer than 3 distinct connectors are skipped.

**Step 2 — Query generation via LLM**

For each seed recipe, `azure/gpt-5.2` (via LiteLLM proxy) is prompted with the recipe summary to produce one **Category 1** natural-language query. Category 1 queries describe a broad business process rather than a specific action — for example:

> "Which recipes automate creating or updating user accounts based on an email request?"

The query is grounded only in what the recipe summary shows. The unique identifier of each query is `query_id`, formatted as `{author_id}_q{n}` (e.g. `206503_q1`).

---

## How Strong and Weak Candidates Are Determined

**Step 3 — Relevance labelling** (`build_eval_category1_relevance.py`)

Every query is evaluated against a global candidate pool — all seed recipes across all authors (not just the query author's own recipes). Each candidate is sent to two models independently:

- `azure/gpt-5.2`
- `bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0`

Each model assigns one of three labels per candidate:

| Label | Meaning |
|---|---|
| Strongly Related | The recipe is a primary component of the business process described by the query |
| Weakly Related | The recipe plays a supporting or peripheral role in that process |
| Not Related | No meaningful connection — excluded from output |

A candidate row is written to `eval_category1.csv` only if at least one model returns a positive label (Strongly or Weakly Related).

**Step 4 — Ground truth filter** (`category_1_eval_dataset.py`)

A query is **kept** only if its source recipe — the recipe that was used to generate the query — is rated **Strongly Related by both models**. Queries that fail this check are dropped, as they indicate the query does not clearly describe its own source recipe.

**Step 5 — Strong and weak list construction**

For each kept query:

- **Strong list**: candidates where **both** `relevance_gpt52 == Strongly Related` and `relevance_claude == Strongly Related`. Both models agree the recipe is a primary match.

- **Weak list**: candidates where both models gave a positive label but did **not** both agree on Strongly Related. This covers two cases:
  - **Case 1** — one model says Strong, the other says Weak (S/W or W/S)
  - **Case 2** — both models say Weak (W/W)

  Candidates where either model says Not Related are excluded entirely.

A sanity check verifies that no recipe UID appears in both lists for the same query. If an overlap is found, the script raises an error.

---

## Unique Identifiers

| Identifier | Format | Description |
|---|---|---|
| `query_id` | `{source_author_id}_q{n}` | Unique identifier for each query; `n` is 1-indexed per author |
| `source_flow_id` | integer | The recipe used to generate the query |
| `recipe_uid` | `{candidate_author_id}_{candidate_flow_id}_v{candidate_version_no}` | Unique identifier for each candidate recipe; combines author, flow, and version to avoid collisions across authors |

---

## Output Schema (`category1_eval_dataset.csv`)

| Column | Type | Description |
|---|---|---|
| `source_author_id` | int | Author who owns the source recipe and generated the query |
| `query_id` | str | Unique query identifier |
| `query` | str | The natural-language search query |
| `source_flow_id` | int | The recipe used to generate the query |
| `strong_list` | str | Comma-separated `recipe_uid`s agreed as Strongly Related by both models |
| `strong_count` | int | Number of candidates in the strong list |
| `weak_list` | str | Comma-separated `recipe_uid`s that both models rated positively but did not both rate as Strong |
| `weak_count` | int | Number of candidates in the weak list |

---

## Candidate Count Distributions

The plots below show how many strong and weak candidates each query has. They are saved alongside this file and regenerated each time `category_1_eval_dataset.py` is run.

### Strong list counts per query

![Distribution of Strong List Counts per Query](category1_eval_strong_count.png)

### Weak list counts per query

![Distribution of Weak List Counts per Query](category1_eval_weak_count.png)

---

## Example Folder (`category1_examples/`)

The `category1_examples/` folder contains inspection materials generated from the same run.

### `all_queries.txt`

A plain-text list of all kept queries, grouped by author. Each line shows the `query_id` and the full query text. Use this for a quick human review of query quality before using the dataset.

### `category1_example_1.xlsx` … `category1_example_5.xlsx`

Five randomly sampled queries (fixed seed for reproducibility). Each Excel file has three sheets:

| Sheet | Contents |
|---|---|
| **Query & Candidates** | One row per strong or weak candidate — query metadata, `list_membership` (strong/weak), candidate identifiers, connectors, and both relevance labels |
| **Source Summary** | The `recipe_summary` of the source recipe that generated the query |
| **Candidate Summaries** | `recipe_uid`, `list_membership`, both relevance labels, and `recipe_summary` for every strong and weak candidate |

These files are intended for manual spot-checking: you can compare the source recipe summary against the query and verify that the strong and weak candidates are plausible matches.
