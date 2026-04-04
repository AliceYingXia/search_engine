# PII-Masked Recipe Cleaning Process

Reference for the cleaning step that prepares `bt_prod.parquet` (PII-masked production recipe versions) for semantic search ingestion.

Script: `02_cleaning/clean_pii_recipes.py`
Input: `data/bt_prod_sample.parquet`
Output: `02_cleaning/cleaned/<flow_id>_<version_no>_semantic.json` and `02_cleaning/cleaned/<flow_id>_<version_no>_tracking.json`

---

## Input Structure

**One row = one full recipe version.** `(flow_id, version_no)` is unique — 10,754 rows means 10,754 recipe versions.

`pii_removed_code` contains the **complete nested recipe JSON**, including `block` arrays. The nesting structure (foreach, if, try, repeat) is fully intact — identical in shape to the raw recipe JSON files. The only differences are that PII values are redacted and `title`/`description` fields are removed.

---

## Key Difference from Raw JSON Cleaning

| Dimension | Raw JSON (`example/*.json`) | PII parquet (`bt_prod.parquet`) |
|---|---|---|
| Unit of input | One file = one recipe (nested) | One row = one recipe version (nested) |
| Nesting structure | Present via `block` arrays | ✅ Present via `block` arrays — fully intact |
| Step traversal | Recursive walk of `block` | Same recursive walk — identical approach |
| Recipe grouping | One file per recipe | One parquet row per recipe version |
| Data pill values | Raw — resolved during cleaning | Already redacted to `"-- REDACTED --"` — no resolution needed |
| `title` / `description` | Present (description excluded, title kept) | **Both absent** — removed by PII masking |
| `if`/`foreach`/`try` nesting | ✅ Recoverable from `block` | ✅ Recoverable from `block` — same as raw |

---

## Why Two Output Files?

Same rationale as the raw pipeline. Each recipe version produces two files:

| File | Purpose | Becomes in Qdrant |
|---|---|---|
| `*_semantic.json` | Text content to embed | → vector |
| `*_tracking.json` | Structured metadata | → payload |

---

## Step 1 — Parse `pii_removed_code`

Each row's `pii_removed_code` is a JSON string. Parse it to a dict. The root object is the trigger step; all other steps are nested under it via `block` arrays recursively.

Use `pii_removed_code` (not `code`) for all outputs.

---

## Step 2 — Walk Steps Recursively

Same recursive `walk_codelines` approach as the raw pipeline. While walking, maintain:

- A **parent stack** to derive `parent_as`, `parent_keyword`, and `depth` for each step
- A **flat ordered list** of steps (by `number`) to derive `prev_step` and `next_step`

---

## What Is Kept vs. Stripped

### Per step — Semantic file

| Field | Source | Kept | Notes |
|---|---|---|---|
| `as` | `pii_removed_code` | ✅ | Join key — must keep |
| `keyword` | `pii_removed_code` | ✅ | Step type |
| `provider` | `pii_removed_code` | ✅ | Which connector |
| `name` | `pii_removed_code` | ✅ | Operation name |
| `title` | `pii_removed_code` | ❌ | **Absent** — removed by PII masking |
| `description` | `pii_removed_code` | ❌ | **Absent** — removed by PII masking |
| `comment` | `pii_removed_code` | ✅ if present | User-written annotation — preserved through PII masking |
| `input_fields` | `pii_removed_code` | ✅ action steps only | List of input key names — values are dropped (100% redacted across dataset). Omitted for control-flow steps (`if`, `foreach`, `try`, `catch`, `repeat`, `else`, `elsif`, `while_condition`) |
| `own_conditions` | `pii_removed_code` | ✅ `if`/`elsif`/`while_condition` only | The step's own condition structure: `logic` (`and`/`or`), `count`, `operands` (list of check types). Distinct from `block_context.conditions`, which holds the **parent's** conditions. Present in 100% of `if`, `elsif`, `while_condition` steps. |
| `block_context` | derived | ✅ | See [Block Context](#block-context-ifforeachtry) |
| `prev_step` | derived | ✅ | See [Neighbour Steps](#neighbour-steps) |
| `next_step` | derived | ✅ | See [Neighbour Steps](#neighbour-steps) |
| `skip` | `pii_removed_code` | ❌ | Runtime flag |
| `uuid` | `pii_removed_code` | ❌ | Opaque identifier |
| `number` | `pii_removed_code` | ❌ | Ordering — tracking concern |
| `extended_input_schema` | `pii_removed_code` | ❌ | Verbose schema cache — empty on control-flow steps |
| `extended_output_schema` | `pii_removed_code` | ❌ | Verbose schema cache |

### Per step — Tracking file

| Field | Source | Kept | Notes |
|---|---|---|---|
| `as` | `pii_removed_code` | ✅ | Join key |
| `uuid` | `pii_removed_code` | ✅ | Stable step identifier |
| `number` | `pii_removed_code` | ✅ | Step ordering |
| `keyword` | `pii_removed_code` | ✅ | Step type |
| `provider` | `pii_removed_code` | ✅ | Connector — useful for Qdrant filtering |
| `name` | `pii_removed_code` | ✅ | Operation name |
| `parent_as` | derived | ✅ | `as` of the enclosing block step |
| `parent_keyword` | derived | ✅ | Keyword of the enclosing block |
| `depth` | derived | ✅ | Nesting depth (0 = trigger) |
| `has_comment` | parquet column | ✅ | `True` if any step in the recipe has a comment |
| `flow_id` | parquet column | ✅ | Recipe identifier — for Qdrant filtering |
| `version_no` | parquet column | ✅ | Recipe version |
| `author_id` | parquet column | ✅ | Author identifier |

### Recipe level — Tracking file

Include `flow_id`, `version_no`, and the list of distinct `provider` values across all steps (equivalent to `flow.config` in the raw pipeline).

---

## Block Context: `if`/`foreach`/`try`/`repeat`

For each step, derive a `block_context` object describing the enclosing control-flow block. This is added to the semantic file.

### All block keyword types in the dataset

| Keyword | Role | Has children | Condition info available |
|---|---|---|---|
| `trigger` | Recipe entry point | ✅ (all root steps) | — |
| `if` | Conditional branch — true path | ✅ | `and`/`or`, number of conditions, operand types |
| `elsif` | Additional condition branch | ✅ | same as `if` |
| `else` | Fallback branch (no condition) | ✅ | none |
| `foreach` | Loop over a list | ✅ | source is REDACTED |
| `try` | Steps to attempt (error handling) | ✅ | none |
| `catch` | Error recovery steps | ✅ | retry config is REDACTED |
| `repeat` | Loop with termination condition | ✅ | — |
| `while_condition` | Termination condition for `repeat` | ❌ (leaf) | `and`/`or`, operand types |
| `stop` | Terminates the recipe | ❌ (leaf) | — |
| `action` | Regular step | ❌ (usually) | — |

### What is recoverable from `if`/`elsif`/`while_condition`

`lhs` and `rhs` (the values being compared) are both `"-- REDACTED --"`. The following structural info survives:

| Info | Available | Example values |
|---|---|---|
| Compound logic | ✅ | `and` / `or` |
| Number of conditions | ✅ | 1, 2, 3 ... |
| Check type per condition (`operand`) | ✅ | `equals_to`, `present`, `not_equals_to`, `greater_than`, `less_than`, `contains`, `not_contains`, `blank`, `is_true`, `is_not_true`, `starts_with`, `ends_with`, ... |

**Operand meanings:**

| Operand | Meaning |
|---|---|
| `present` | field has a value (not null, not empty) |
| `blank` | field has no value |
| `equals_to` / `not_equals_to` | equality check |
| `greater_than` / `less_than` | numeric or date comparison |
| `contains` / `not_contains` | substring check |
| `starts_with` / `ends_with` | prefix / suffix check |
| `is_true` / `is_not_true` | boolean check |

### `block_context` object structure

Derived during the recursive walk. Added to the semantic file for each step:

```json
"block_context": {
  "parent_keyword": "if",
  "branch": "if_true",
  "conditions": {
    "logic": "and",
    "count": 2,
    "operands": ["equals_to", "present"]
  },
  "grandparent_keyword": "foreach"
}
```

| Field | When present | Notes |
|---|---|---|
| `parent_keyword` | always | keyword of the direct enclosing block |
| `branch` | step is inside `if`/`elsif`/`else` | `"if_true"`, `"elsif"`, or `"else"` |
| `conditions` | parent is `if`, `elsif`, or `while_condition` | logic (`and`/`or`), count, operand types |
| `grandparent_keyword` | parent has a parent | keyword one level further up |

Steps at root level (direct children of `trigger`) have `block_context: null`.

### Examples

Step inside a simple `if` (one condition, present check):
```json
"block_context": {
  "parent_keyword": "if",
  "branch": "if_true",
  "conditions": { "logic": "and", "count": 1, "operands": ["present"] },
  "grandparent_keyword": "trigger"
}
```

Step inside `elsif` with two conditions:
```json
"block_context": {
  "parent_keyword": "elsif",
  "branch": "elsif",
  "conditions": { "logic": "or", "count": 2, "operands": ["equals_to", "is_true"] },
  "grandparent_keyword": "if"
}
```

Step inside `else`:
```json
"block_context": {
  "parent_keyword": "else",
  "branch": "else",
  "conditions": null,
  "grandparent_keyword": "if"
}
```

Step inside `foreach` (which is itself inside `try`):
```json
"block_context": {
  "parent_keyword": "foreach",
  "branch": null,
  "conditions": null,
  "grandparent_keyword": "try"
}
```

Step inside `catch`:
```json
"block_context": {
  "parent_keyword": "catch",
  "branch": null,
  "conditions": null,
  "grandparent_keyword": "try"
}
```

Step inside `repeat` loop:
```json
"block_context": {
  "parent_keyword": "repeat",
  "branch": null,
  "conditions": null,
  "grandparent_keyword": "trigger"
}
```

---

## Neighbour Steps

For each step, add `prev_step` and `next_step` to the semantic file. These are the immediately adjacent steps in recipe order (by `number`), regardless of nesting depth.

```json
"prev_step": { "keyword": "action", "provider": "salesforce", "name": "search_records" },
"next_step": { "keyword": "action", "provider": "slack_bot", "name": "post_message" }
```

Only `keyword`, `provider`, and `name` are included — enough to describe what the step does without adding noise.

- First step in the recipe: `prev_step: null`
- Last step in the recipe: `next_step: null`
- `if`/`foreach`/`try`/`repeat` control-flow steps are included as neighbours (they appear in the flat ordered list)

---

## `has_comment` and Comments

`has_comment` (parquet column) is `True` if **any step** in the recipe has a comment. The comment text lives inside the nested JSON at the individual step level as a `comment` field.

When a step has a `comment` field in `pii_removed_code`:
- Include it in the semantic file — it is a human-authored intent label for the step
- Comment text is not redacted and survives PII masking

---

## Input Fields

All input values are `"-- REDACTED --"` across 100% of the dataset — verified by scanning all 277,286 input values in `bt_prod.parquet`. No exceptions.

Because values carry no information, the semantic file stores only the field **names** as a flat list:

```json
"input_fields": ["sobject_name", "query", "field_list", "limit"]
```

rather than the original dict:

```json
"input": {
  "sobject_name": "-- REDACTED --",
  "query": "-- REDACTED --",
  "field_list": "-- REDACTED --",
  "limit": "-- REDACTED --"
}
```

The field names indicate *what* the step is mapping to — semantically meaningful without the values.

**Control-flow steps** (`if`, `elsif`, `else`, `foreach`, `try`, `catch`, `repeat`, `while_condition`) do not get `input_fields`. Their condition info is captured in `block_context`, and their remaining input keys (`source`, `max_retry_count`, `retry_interval`) are fully redacted with no semantic value.

---

## Recipe-Level Summary

Generated by Python from structural fields. The summary is designed to capture as much information as the combination of all individual step texts, so that embedding the summary alone is sufficient for recipe-level retrieval.

Each step contributes up to three elements:

| Element | When included | Format |
|---|---|---|
| Step label | always | `- {kw}: {provider} / {name}` or tag for control-flow |
| Comment | step has a `comment` field | appended inline as `  # {comment text}` |
| Input fields | action steps with `input` keys | sub-line `  fields: {key1}, {key2}, ...` (capped at 8) |

Nesting depth conveys block context (foreach, if, try, etc.) — the same information carried by `block_context` in step texts — so no separate context line is needed.

`if`/`elsif`/`while_condition` show their condition operands in brackets. `foreach` shows `[loop]`. `try`/`catch` show `[error handling]`/`[error handler]`. `repeat` shows `[loop]`.

Example:

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

## `as` Alias — Same Rules Apply

The `as` field inside `pii_removed_code` is the join key between semantic and tracking files. It must be present in both outputs.

Control-flow steps (`if`, `elsif`, `else`, `try`, `while_condition`) frequently have no `as`. Generate a synthetic key `_step_{number}` in these cases.

---

## Full Examples — Semantic File

### Recipe 1 — `flow_id=17980527 v38`

Recipe-level summary:
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

Step 3 — root-level action with comment:
```json
{
  "as": "90a1e652",
  "keyword": "action",
  "provider": "namely_connector",
  "name": "search_employee_profiles",
  "comment": "Get Total Count of profiles",
  "input_fields": ["per_page"],
  "block_context": null,
  "prev_step": { "keyword": "action", "provider": "workato_variable", "name": "declare_variable" },
  "next_step": { "keyword": "action", "provider": "workato_list", "name": "create_list" }
}
```

Step 6 — `if` step with own conditions (inside `foreach`):
```json
{
  "as": "_step_6",
  "keyword": "if",
  "provider": null,
  "name": null,
  "own_conditions": { "logic": "and", "count": 1, "operands": ["present"] },
  "block_context": {
    "parent_keyword": "foreach",
    "branch": null,
    "conditions": null,
    "grandparent_keyword": "trigger"
  },
  "prev_step": { "keyword": "action", "provider": "workato_list", "name": "create_list" },
  "next_step": { "keyword": "action", "provider": "namely_connector", "name": "search_employee_profiles" }
}
```

Step 7 — action inside `foreach > if`:
```json
{
  "as": "00b9420f",
  "keyword": "action",
  "provider": "namely_connector",
  "name": "search_employee_profiles",
  "input_fields": ["per_page", "page"],
  "block_context": {
    "parent_keyword": "if",
    "branch": "if_true",
    "conditions": { "logic": "and", "count": 1, "operands": ["present"] },
    "grandparent_keyword": "foreach"
  },
  "prev_step": { "keyword": "if", "provider": null, "name": null },
  "next_step": { "keyword": "if", "provider": null, "name": null }
}
```

Step 10 — action with comment inside `foreach > if`:
```json
{
  "as": "ffe0fa97",
  "keyword": "action",
  "provider": "workato_variable",
  "name": "update_variables",
  "comment": "Set new page number",
  "input_fields": ["name", "page"],
  "block_context": {
    "parent_keyword": "if",
    "branch": "if_true",
    "conditions": { "logic": "and", "count": 1, "operands": ["present"] },
    "grandparent_keyword": "foreach"
  },
  "prev_step": { "keyword": "action", "provider": "workato_variable", "name": "insert_to_list_batch" },
  "next_step": { "keyword": "action", "provider": "workato_recipe_function", "name": "return_result" }
}
```

---

### Recipe 2 — `flow_id=51599036 v1`

Recipe-level summary:
```
Connectors: workato_recipe_function, workato_variable, salesforce
Steps:
- trigger: workato_recipe_function / execute
  - try [error handling]
    - action: workato_variable / declare_list
    - action: salesforce / search_sobjects_soql
    - if [and: greater_than]
      - action: workato_variable / insert_to_list_batch
    - foreach [loop]
      - action: salesforce / search_sobjects_soql
      - if [and: greater_than]
        - action: workato_variable / insert_to_list_batch
    - action: workato_variable / declare_variable
    - if [and: contains]
      - action: workato_recipe_function / return_result
    - catch [error handler]
      - action: workato_recipe_function / return_result
```

Step 7 — salesforce action inside `try > foreach`:
```json
{
  "as": "db36c8ab",
  "keyword": "action",
  "provider": "salesforce",
  "name": "search_sobjects_soql",
  "input_fields": ["limit", "sobject_name", "query", "field_list"],
  "block_context": {
    "parent_keyword": "foreach",
    "branch": null,
    "conditions": null,
    "grandparent_keyword": "try"
  },
  "prev_step": { "keyword": "foreach", "provider": null, "name": null },
  "next_step": { "keyword": "if", "provider": null, "name": null }
}
```

Step 8 — `if` step with own conditions (inside `try > foreach`):
```json
{
  "as": "_step_8",
  "keyword": "if",
  "provider": null,
  "name": null,
  "own_conditions": { "logic": "and", "count": 1, "operands": ["greater_than"] },
  "block_context": {
    "parent_keyword": "foreach",
    "branch": null,
    "conditions": null,
    "grandparent_keyword": "try"
  },
  "prev_step": { "keyword": "action", "provider": "salesforce", "name": "search_sobjects_soql" },
  "next_step": { "keyword": "action", "provider": "workato_variable", "name": "insert_to_list_batch" }
}
```

Step 9 — action inside `try > foreach > if`:
```json
{
  "as": "bbb7c9f9",
  "keyword": "action",
  "provider": "workato_variable",
  "name": "insert_to_list_batch",
  "input_fields": ["location", "name", "list_items"],
  "block_context": {
    "parent_keyword": "if",
    "branch": "if_true",
    "conditions": { "logic": "and", "count": 1, "operands": ["greater_than"] },
    "grandparent_keyword": "foreach"
  },
  "prev_step": { "keyword": "if", "provider": null, "name": null },
  "next_step": { "keyword": "action", "provider": "workato_variable", "name": "declare_variable" }
}
```

Step 14 — action inside `catch`:
```json
{
  "as": "51ddd320",
  "keyword": "action",
  "provider": "workato_recipe_function",
  "name": "return_result",
  "input_fields": ["result"],
  "block_context": {
    "parent_keyword": "catch",
    "branch": null,
    "conditions": null,
    "grandparent_keyword": "try"
  },
  "prev_step": { "keyword": "catch", "provider": null, "name": null },
  "next_step": null
}
```

---

## No LLM Required

The cleaning step is fully deterministic:
- Parse each parquet row's `pii_removed_code` JSON
- Recursively walk `block` arrays, tracking parent stack and flat step order
- Derive `block_context`, `own_conditions`, `prev_step`, `next_step`, `parent_as`, `depth` for each step
- Extract fields per the keep/strip tables above
- Generate recipe-level summary from structural fields
- Emit `_semantic.json` and `_tracking.json` per recipe version

No language model is needed at this stage.

---

## File Tree After Cleaning

```
description_intent/
├── data/
│   └── bt_prod_sample.parquet                  # input
└── 02_cleaning/
    └── cleaned/
        ├── 50301408_4_semantic.json
        ├── 50301408_4_tracking.json
        ├── 17980527_38_semantic.json
        └── 17980527_38_tracking.json
```

---

## Differences Summary: Raw JSON vs. PII Parquet

| Concern | Raw JSON pipeline | PII parquet pipeline |
|---|---|---|
| `title` in semantic file | ✅ kept | ❌ absent |
| Data pill resolution | ✅ resolved to human labels | ❌ values redacted — skip |
| Nesting (`block`) | ✅ recursive walk | ✅ same recursive walk |
| `depth` / `parent_as` | ✅ derived during walk | ✅ derived during walk — same approach |
| `if`/`foreach`/`try` context | not added | ✅ `block_context` added per step |
| Neighbour steps | not added | ✅ `prev_step` / `next_step` added per step |
| `has_comment` signal | not available | ✅ parquet column (recipe-level flag) |
| Comment text | ✅ if present | ✅ preserved through PII masking |
| Input field keys | ✅ with real values | ✅ keys only as `input_fields` list — all values redacted |
| Recipe grouping | one file per recipe | one parquet row per recipe version |

---

## Step Text Construction (for Embedding)

Script: `03_step_text/build_step_text.py`
Input:  `02_cleaning/cleaned/<flow_id>_<version_no>_semantic.json`
Output: `03_step_text/step_texts/<flow_id>_<version_no>_step_texts.json`

Each output file is a list of objects:
```json
{
    "as":         "<step alias>",
    "flow_id":    50301408,
    "version_no": 4,
    "text":       "<embed text string>"
}
```

### Design Goals

- Dense and search-friendly: what the step does, where it sits, what surrounds it
- No PII: values are redacted — only field names, operand types, and connector operations are retained
- Consistent structure across step types so embeddings are comparable

### Skipped Steps (not embedded)

`else` and `try` are **structural containers** with no semantic content of their own. They are kept in the tracking file (for structure) but skipped in step_texts:

| Keyword | Reason |
|---|---|
| `else` | No condition — purely "not-if"; children already say `inside else branch` via `block_context` |
| `try` | Just a container; children already say `inside try block` via `block_context` |

All other keywords (`action`, `if`, `elsif`, `foreach`, `catch`, `repeat`, `while_condition`, `stop`, `trigger`) produce an embed entry.

### Text Format per Step Type

#### Action steps

Lines (in order, each on its own line; omit if absent):

| # | Line | When included |
|---|---|---|
| 1 | `{comment text}` | step has a comment |
| 2 | `action {provider} / {name}` | always |
| 3 | `fields: {field1}, {field2}, ...` | step has `input_fields` (capped at 8; appends `(+N more)` if longer) |
| 4 | `context: {block_context string}` | step is inside a control-flow block |
| 5 | `flow: {prev} → {nxt}` | at least one neighbour exists |

Example:
```
Get Total Count of profiles
action namely_connector / search_employee_profiles
fields: per_page
flow: workato_variable/declare_variable → workato_list/create_list
```

#### Condition steps (`if` / `elsif` / `while_condition`)

| # | Line | When included |
|---|---|---|
| 1 | `{kw} [{logic}: {operand1}, {operand2}]` | always (`own_conditions` used; falls back to bare keyword if absent) |
| 2 | `context: {block_context string}` | step is nested inside another control-flow block |
| 3 | `flow: {prev} → {nxt}` | at least one neighbour |

Example:
```
if [and: present]
context: inside foreach loop
flow: workato_list/create_list → namely_connector/search_employee_profiles
```

#### Control-flow steps (`foreach` / `try` / `catch` / `else` / `repeat` / `stop`)

| # | Line | When included |
|---|---|---|
| 1 | `{tag label}` (see table below) | always |
| 2 | `context: {block_context string}` | step is nested inside another control-flow block |
| 3 | `flow: {prev} → {nxt}` | at least one neighbour |

#### Trigger step

| # | Line | When included |
|---|---|---|
| 1 | `trigger: {provider} / {name}` | always (falls back to `trigger` if no provider/name) |
| 2 | `flow: → {nxt}` | next step exists (trigger never has prev) |

### Control-flow Label Table

| Keyword | Rendered label |
|---|---|
| `trigger` | `trigger: {provider} / {name}` |
| `foreach` | `foreach [loop]` |
| `try` | `try [error handling]` |
| `catch` | `catch [error handler]` |
| `else` | `else` |
| `repeat` | `repeat [loop]` |
| `while_condition` | `while_condition` |
| `stop` | `stop` |

### Block Context Rendering Rules

`block_context` is rendered as a single `context: inside ...` line. Root-level steps (direct children of `trigger`) emit no context line.

| Parent keyword | Rendered string |
|---|---|
| `foreach` | `inside foreach loop` |
| `try` | `inside try block` |
| `catch` | `inside catch block` |
| `repeat` | `inside repeat loop` |
| `else` | `inside else branch` |
| `if` (true branch) | `inside if [true branch, {logic}: {operands}]` |
| `if` (no conditions) | `inside if [true branch]` |
| `elsif` | `inside elsif [elsif branch, {logic}: {operands}]` |

When the grandparent is also a meaningful control-flow block, it is appended with ` > `:
```
inside catch block > try block
inside if [true branch, and: present] > foreach loop
inside foreach loop > try block
```

Grandparent labels:

| Grandparent keyword | Appended label |
|---|---|
| `foreach` | `foreach loop` |
| `try` | `try block` |
| `if` | `if block` |
| `repeat` | `repeat loop` |
| anything else | the keyword itself |

### Neighbour Rendering

`prev_step` and `next_step` are rendered as:
- `{provider}/{name}` if both are present
- `{keyword}` otherwise (e.g. `if`, `foreach`, `catch`)

Flow line formats:
- Both neighbours: `flow: {prev} → {nxt}`
- Only prev: `flow: {prev} →`
- Only next: `flow: → {nxt}`
- No neighbours: line omitted

### Full Examples

**Trigger step:**
```
trigger: workato_recipe_function / execute
flow: → workato_variable/declare_list
```

**Root-level action with comment:**
```
Get Total Count of profiles
action namely_connector / search_employee_profiles
fields: per_page
flow: workato_variable/declare_variable → workato_list/create_list
```

**Root-level action, no comment:**
```
action salesforce / search_records
fields: sobject_name, query, field_list, limit
flow: workato_variable/declare_list → if
```

**Action with many fields (capped at 8):**
```
action open_ai / __adhoc_http_action
fields: mnemonic, request_type, response_type, verb, path, input, output, response_headers, (+1 more)
context: inside try block > foreach loop
flow: workato_template/create_document → workato_variable/insert_to_list
```

**`if` step inside `foreach`:**
```
if [and: present]
context: inside foreach loop
flow: workato_list/create_list → namely_connector/search_employee_profiles
```

**Action inside `foreach > if` (true branch):**
```
action namely_connector / search_employee_profiles
fields: per_page, page
context: inside if [true branch, and: present] > foreach loop
flow: if → if
```

**`foreach` step:**
```
foreach [loop]
flow: salesforce/search_records → salesforce/search_records
```

**`try` step:**
```
try [error handling]
flow: workato_recipe_function/execute → workato_variable/declare_list
```

**Action inside `catch` (error handler inside `try`):**
```
action workato_recipe_function / return_result
fields: result
context: inside catch block > try block
flow: catch →
```

**`if` step with multiple conditions:**
```
if [or: equals_to, is_true]
context: inside foreach loop
flow: salesforce/search_records → workato_variable/insert_to_list_batch
```
