# Recipe Sampling: bt_prod_sample.parquet

Reference for the author-scoped sample drawn from `bt_prod.parquet` for development and evaluation use.

Script: `01_sampling/sample_recipes.py`
Input:  `data/bt_prod.parquet` (10,754 rows)
        `data/gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet` (9,764 rows)
Output: `data/bt_prod_sample.parquet` (801 rows)

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

### Step 2 — Select 10 authors with 50 < recipes < 100

After the description filter, authors are ranked by recipe count. Authors with more than 50 and fewer than 100 recipes are eligible. The **top 10 by recipe count** are selected.

This range is chosen deliberately:
- **> 50**: enough recipes per author to represent their automation style and domain
- **< 100**: avoids the dataset being dominated by the largest power users (top 4 authors have 500–750 recipes each)

### Step 3 — Include all recipes from the selected authors

All recipes belonging to the 10 selected authors (after description filter) are included — no further subsampling within authors.

---

## Selected Authors

| author_id | recipes | Sample description |
|---|---|---|
| 618946 | 96 | When a deployment build is requested, automatically build the Gong connection package |
| 2973760 | 95 | When Work Genie requests the VirusTotal module definition, automatically return the full definition |
| 973497 | 90 | Every day, clean up an Iterable suppression list in batches and then kick off our duplicate check |
| 1873345 | 80 | Notify our Slack channel whenever a renewal-related Opportunity with contract limit changes |
| 3000083 | 79 | Make sure submitted request details aren't blank and the exception description isn't too long |
| 206503 | 74 | Let approvers update an approval request's parameters in Slack and then approve it |
| 3165547 | 73 | Each month, summarize our recent process activity and ticketing efficiency into a single report |
| 5770830 | 73 | Help me find Gong calls from a given time period and return a list with the call details |
| 3511776 | 71 | Create a new Google Slides deck from our standard template in Google Drive |
| 2136196 | 70 | Given a project ID, find the Slack message we started for that onboarding |

---

## Sample Statistics

| Metric | Value |
|---|---|
| Total rows | 801 |
| Unique authors | 10 |
| Unique recipes (`flow_id`) | 801 |
| All rows have description | ✅ 100% |
| `has_comment = True` | 22 (2.7%) |

Note: `has_comment` rate is 2.7% in this sample vs 10% in the full dataset — these 10 authors comment rarely.

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
| > 500 recipes | 4 | Top power users — dominate 25% of dataset |
| 100–500 recipes | 25 | Large contributors |
| **50–99 recipes** | **20** | **Eligible pool — 10 selected** |
| < 50 recipes | 170 | Long tail |
