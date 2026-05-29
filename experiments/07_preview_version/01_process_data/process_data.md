# Data Preparation: Sampling & Recipe Summaries

Reference for `process_data.py`, which prepares `bt_prod_sample.parquet` and
`recipe_summaries.parquet` for semantic search ingestion.

Script: `pipeline/01_process_data/process_data.py`

| | Path |
|---|---|
| Input | `data/bt_prod.parquet` |
| Input | `data/gpt-5.2-2025-12-11_bt_prod_descriptions_recipe.parquet` |
| Output (Step 1) | `data/bt_prod_sample.parquet` |
| Output (Step 2) | `01_process_data/cleaned/recipe_summaries.parquet` |

---

## Step 1 — Sample Recipes

### Why sample?

Working with all 10,754 recipes during development is slow. The sample is used for
manual inspection, pipeline development, and evaluating semantic search quality
before scaling up.

### Sampling strategy

**Filter to described recipes only.**
Rows without a GPT-generated description are dropped via an inner join on `flow_id`.
This reduces the dataset from 10,754 to **9,764 rows** across 219 authors.
Recipes without descriptions are excluded because `short_user_intent` and
`verbose_user_intent` are required for evaluation.

**Select the top 30 authors by recipe count.**
After the description filter, authors are ranked by recipe count and the top 30 are
selected. This spans the highest-volume power users down through large contributors:

| Group | Authors | Notes |
|---|---|---|
| > 500 recipes | 4 | Top power users — all 4 selected |
| 100–500 recipes | 25 | Large contributors — all 25 selected |
| 50–99 recipes | 20 | Mid-tier — top 1 selected |
| < 50 recipes | 170 | Long tail — not selected |

**Include all recipes from the 30 selected authors.** No further subsampling.

### Output schema

The output parquet includes all columns from `bt_prod.parquet` plus three
description columns joined from the descriptions parquet:

| Column | Type | Source | Description |
|---|---|---|---|
| `flow_id` | int | bt_prod | Recipe identifier |
| `version_no` | int | bt_prod | Recipe version |
| `author_id` | int | bt_prod | Author identifier |
| `created_at` | datetime | bt_prod | Version creation time |
| `updated_at` | datetime | bt_prod | Version last updated |
| `pii_removed_code` | string | bt_prod | Full nested recipe JSON (PII-masked) |
| `has_comment` | bool | bt_prod | True if any step has a comment |
| `code_length` | int | bt_prod | Character length of raw code field |
| `description` | string | descriptions | GPT-generated long-form recipe description |
| `short_user_intent` | string | descriptions | One-sentence user intent summary |
| `verbose_user_intent` | string | descriptions | Detailed user intent paragraph |

Columns dropped (redundant or always null): `.1`-suffix duplicates, `data_mapper_snapshot`,
`mask_statistics`, `code` (unredacted; not used in the PII-masked pipeline).

---

## Step 2 — Build Recipe Summaries

### Input structure

**One row = one full recipe version.** `(flow_id, version_no)` is unique.

`pii_removed_code` contains the complete nested recipe JSON, including `block` arrays.
The nesting structure (foreach, if, try, repeat) is fully intact. PII values are
redacted and `title`/`description` fields are removed.

### Summary generation

A single recursive walk over the `block` tree generates the summary. Nesting depth
conveys block context via indentation — no parent stack needed.

Each step contributes up to two lines:

| Element | When included | Format |
|---|---|---|
| Step label | always | `- {kw}: {provider} / {name}` or tag for control-flow |
| Comment | step has a `comment` field and `include_comments=True` | appended inline as `  # {comment}` |
| Input fields | action steps with `input` keys | sub-line `  fields: {key1}, {key2}, ...` (capped at 8) |

Control-flow formatting:
- `if` / `elsif` / `while_condition` — shows condition operands: `if [and: present]`
- `foreach` → `foreach [loop]`
- `try` → `try [error handling]`,  `catch` → `catch [error handler]`
- `repeat` → `repeat [loop]`

The walk runs twice per recipe — once with comments, once without — producing both
output columns. Input values are all `"-- REDACTED --"` across the dataset, so only
field **names** are shown.

### Step counting

`step_count` is the total number of nodes in the recipe tree, counted by a single recursive walk over the `block` structure. Every node increments the count by 1 — regardless of keyword. This means:

- The trigger is step 1.
- Every `action`, `if`, `elsif`, `else`, `foreach`, `repeat`, `try`, `catch`, and `while_condition` each count as one step.
- Nesting does not reduce the count — an `if` containing 3 actions counts as 4.

### Output schema

One parquet row per recipe version:

| Column | Type | Description |
|---|---|---|
| `flow_id` | int | Recipe identifier |
| `version_no` | int | Recipe version number |
| `author_id` | int | Author identifier |
| `connectors` | list[str] | Sorted distinct provider names — for payload filtering |
| `step_count` | int | Total steps in the recipe tree (all nodes, including trigger and control-flow) |
| `recipe_summary_with_comment` | str | Full structural summary including user comments |
| `recipe_summary_without_comment` | str | Same summary with comments stripped |

### Example output

```
Connectors: workato_recipe_function, workato_variable, namely_connector, workato_list
Steps:
- trigger: workato_recipe_function / execute
  - action: workato_variable / declare_list
  - action: workato_variable / declare_variable
  - action: namely_connector / search_employee_profiles  # Get Total Count of profiles
    fields: per_page
  - action: workato_list / create_list
  - foreach [loop]
    - if [and: present]
      - action: namely_connector / search_employee_profiles
        fields: per_page, page
      - if [and: greater_than]
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - action: workato_variable / update_variables  # Set new page number
        fields: name, page
  - action: workato_recipe_function / return_result
    fields: result
```

---

## File Tree

```
pipeline/
└── 01_process_data/
    ├── process_data.py                  ← this script
    ├── process_data.md                  ← this document
    ├── source_recipe_schema.md          ← bt_prod.parquet field reference
    └── cleaned/
        └── recipe_summaries.parquet     ← Step 2 output (gitignored)

data/
├── bt_prod.parquet                      ← Step 1 input  (gitignored)
├── gpt-5.2-..._descriptions_recipe.parquet  ← Step 1 input  (gitignored)
└── bt_prod_sample.parquet               ← Step 1 output (gitignored)
```
