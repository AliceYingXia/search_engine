# Recipe Sampling: bt_prod_sample.parquet

Reference for the author-scoped sample drawn from `bt_prod.parquet` for development and evaluation use.

Script: `01_sampling/sample_recipes.py`
Input:  `data/bt_prod.parquet` (10,754 rows)
        `data/gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet` (9,764 rows)
Output: `data/bt_prod_sample.parquet` (TBD rows — update after running)

---

## Why Sample?

Working with all 10,754 recipes during development is slow. The sample is used for:
- Developing and testing `clean_pii_recipes.py`
- Manual inspection and example generation
- Evaluating semantic search quality before scaling up

---

## Sampling Strategy: Author-Scoped with Description Filter

### Step 1 — Filter to described recipes only

Rows without a GPT-generated description are dropped via an inner join with the descriptions parquet on `flow_id`. This reduces the dataset from 10,754 to **9,764 rows** across 219 authors.

Recipes without descriptions are excluded because the description (`short_user_intent`, `verbose_user_intent`) is needed for evaluation and retrieval quality assessment.

### Step 2 — Select top 30 authors by recipe count

After the description filter, authors are ranked by recipe count and the **top 30** are selected with no range restriction. This spans the highest-volume power users down through large contributors.

### Step 3 — Include all recipes from the selected authors

All recipes belonging to the 30 selected authors (after description filter) are included — no further subsampling within authors.

---

## Selected Authors

| author_id | recipes | Sample description |
|---|---|---|
| (update after running) | — | — |

---

## Sample Statistics

| Metric | Value |
|---|---|
| Total rows | TBD — update after running |
| Unique authors | 30 |
| Unique recipes (`flow_id`) | TBD |
| All rows have description | ✅ 100% |
| `has_comment = True` | TBD |

---

## Output Schema

The output parquet includes the original columns from `bt_prod.parquet` plus the three description columns joined from the descriptions parquet:

| Column | Type | Source | Description |
|---|---|---|---|
| `flow_id` | int | bt_prod | Recipe identifier |
| `version_no` | int | bt_prod | Recipe version |
| `author_id` | int | bt_prod | Author identifier |
| `created_at` | datetime | bt_prod | Version creation time |
| `updated_at` | datetime | bt_prod | Version last updated |
| `pii_removed_code` | string | bt_prod | Full nested recipe JSON (PII-masked) |
| `has_comment` | bool | bt_prod | True if any step in the recipe has a comment |
| `code_length` | int | bt_prod | Character length of the raw code field |
| `description` | string | descriptions | GPT-generated long-form recipe description |
| `short_user_intent` | string | descriptions | One-sentence user intent summary |
| `verbose_user_intent` | string | descriptions | Detailed user intent paragraph |

Columns dropped from the output (redundant or empty):
- `.1`-suffix duplicate columns (`id.1`, `flow_id.1`, etc.) — artefacts of the original join
- `data_mapper_snapshot`, `data_mapper_snapshot.1`, `mask_statistics` — always null
- `code` — unredacted; not used in the PII-masked pipeline

---

## Full Dataset Author Distribution (reference)

For context, the full `bt_prod.parquet` (after description filter) has 219 authors:

| Group | Authors | Notes |
|---|---|---|
| > 500 recipes | 4 | Top power users — **all 4 selected** |
| 100–500 recipes | 25 | Large contributors — **all 25 selected** |
| 50–99 recipes | 20 | Mid-tier — **top 1 selected** |
| < 50 recipes | 170 | Long tail — not selected |
