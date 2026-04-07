# PII-Masked Recipe Cleaning Process

Reference for the cleaning step that prepares `bt_prod_sample.parquet` (PII-masked production recipe versions) for semantic search ingestion.

Script: `02_cleaning/clean_pii_recipes.py`
Input: `data/bt_prod_sample.parquet`
Output: `02_cleaning/cleaned/recipe_summaries.parquet`

---

## Input Structure

**One row = one full recipe version.** `(flow_id, version_no)` is unique — 10,754 rows means 10,754 recipe versions.

`pii_removed_code` contains the **complete nested recipe JSON**, including `block` arrays. The nesting structure (foreach, if, try, repeat) is fully intact. The only differences from raw JSON are that PII values are redacted and `title`/`description` fields are removed.

---

## Output Structure

One parquet row per recipe version with five columns:

| Column | Type | Description |
|---|---|---|
| `flow_id` | int | Recipe identifier |
| `version_no` | int | Recipe version number |
| `author_id` | int | Author identifier |
| `connectors` | list[str] | Sorted distinct provider names — for Qdrant payload filtering |
| `recipe_summary_with_comment` | str | Full structural summary including user-written comments |
| `recipe_summary_without_comment` | str | Same summary with comments stripped |

---

## Step 1 — Parse `pii_removed_code`

Each row's `pii_removed_code` is a JSON string. Parse it to a dict. The root object is the trigger step; all other steps are nested under it via `block` arrays recursively.

Use `pii_removed_code` (not `code`) for all outputs.

---

## Step 2 — Build Recipe Summary

A single recursive walk over the `block` tree generates the summary. No parent stack or flat step ordering is needed — nesting depth alone conveys block context via indentation.

Each step contributes up to three lines:

| Element | When included | Format |
|---|---|---|
| Step label | always | `- {kw}: {provider} / {name}` or tag for control-flow |
| Comment | step has a `comment` field (and `include_comments=True`) | appended inline as `  # {comment text}` |
| Input fields | action steps with `input` keys | sub-line `  fields: {key1}, {key2}, ...` (capped at 8) |

`if`/`elsif`/`while_condition` show their condition operands in brackets. `foreach` shows `[loop]`. `try`/`catch` show `[error handling]`/`[error handler]`. `repeat` shows `[loop]`.

The same walk is run twice per recipe — once with comments, once without — producing both summary columns.

---

## Comments

Comment text lives inside the nested JSON at the individual step level as a `comment` field. Comments are not redacted and survive PII masking.

- `recipe_summary_with_comment`: includes `# {comment}` inline on the step line
- `recipe_summary_without_comment`: comment lines are suppressed entirely

---

## Input Fields

All input values are `"-- REDACTED --"` across 100% of the dataset. Because values carry no information, the summary shows only the field **names**:

```
  fields: sobject_name, query, field_list, limit
```

This applies to action steps only. Control-flow steps (`if`, `elsif`, `else`, `foreach`, `try`, `catch`, `repeat`, `while_condition`) do not get a fields line — their condition info is shown in the step label, and remaining input keys have no semantic value.

---

## Recipe-Level Summary Example

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

The `without_comment` variant of the same recipe omits the `# ...` annotations:

```
Connectors: workato_recipe_function, workato_variable, namely_connector, workato_list
Steps:
- trigger: workato_recipe_function / execute
  - action: workato_variable / declare_list
  - action: workato_variable / declare_variable
  - action: namely_connector / search_employee_profiles
    fields: per_page
  - action: workato_list / create_list
  - foreach [loop]
    - if [and: present]
      - action: namely_connector / search_employee_profiles
        fields: per_page, page
      - if [and: greater_than]
        - action: workato_variable / insert_to_list_batch
          fields: location, name, list_items
      - action: workato_variable / update_variables
        fields: name, page
  - action: workato_recipe_function / return_result
    fields: result
```

---

## No LLM Required

The cleaning step is fully deterministic:
- Parse each parquet row's `pii_removed_code` JSON
- Recursively walk `block` arrays to collect providers and build the indented step outline
- Run the walk twice per recipe (with and without comments)
- Emit one parquet row per recipe version

No language model is needed at this stage.

---

## File Tree After Cleaning

```
2_small sample synthesization/
├── data/
│   └── bt_prod_sample.parquet          # input
└── 02_cleaning/
    └── cleaned/
        └── recipe_summaries.parquet    # output
```
