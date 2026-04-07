# bt_prod.parquet — Schema Documentation

## Overview

| Property | Value |
|---|---|
| File | `description_intent/bt_prod.parquet` |
| Rows | 10,754 |
| Columns | 21 |
| Description | Production Workato recipe versions with PII-scrubbed step code. Appears to be the result of a join between two sources — one set of columns uses native types (e.g. `Int32`, `datetime64`) and a duplicate set with `.1` suffix uses looser types (e.g. `int64`, `str`). |

---

## Columns

### Identity & Versioning

| Column | Type | Nulls | Description |
|---|---|---|---|
| `id` | Int32 | 0 | Primary key — unique ID for this recipe version record |
| `flow_id` | Int32 | 0 | ID of the parent recipe (flow) |
| `version_no` | Int32 | 0 | Version number of the recipe |
| `author_id` | Int64 | 0 | ID of the user who authored this version |

### Timestamps

| Column | Type | Nulls | Description |
|---|---|---|---|
| `created_at` | datetime64[us, UTC] | 0 | When this version was created |
| `updated_at` | datetime64[us, UTC] | 0 | When this version was last updated |

### Content

| Column | Type | Nulls | Description |
|---|---|---|---|
| `pii_removed_code` | string | 0 | JSON string of the recipe step definition with PII values redacted as `"-- REDACTED --"`. Contains fields like `as`, `number`, `keyword`, `input`, `provider`, `name`, `skip`, `uuid`, `extended_input_schema`, `extended_output_schema`. |
| `code` | string | 0 | JSON string of the raw recipe step definition (unredacted). Same structure as `pii_removed_code`. |
| `code_length` | Int32 | 0 | Character length of the code field |
| `has_comment` | boolean | 0 | Whether the recipe step has a comment attached |

### Entirely Null Columns

| Column | Type | Nulls | Description |
|---|---|---|---|
| `data_mapper_snapshot` | string | 10,754 (all) | Always null — no data present |
| `mask_statistics` | object | 10,754 (all) | Always null — no data present |

### Duplicate Columns (from join, `.1` suffix)

These columns appear to be duplicates introduced by a DataFrame merge. They carry the same values as their counterparts above but with looser types.

| Column | Original | Type | Nulls |
|---|---|---|---|
| `id.1` | `id` | int64 | 0 |
| `flow_id.1` | `flow_id` | int64 | 0 |
| `version_no.1` | `version_no` | int64 | 0 |
| `created_at.1` | `created_at` | str | 0 |
| `updated_at.1` | `updated_at` | str | 0 |
| `author_id.1` | `author_id` | int64 | 0 |
| `data_mapper_snapshot.1` | `data_mapper_snapshot` | object | 10,754 (all) |
| `has_comment.1` | `has_comment` | bool | 0 |
| `code_length.1` | `code_length` | int64 | 0 |

---

## Key Content Field: `pii_removed_code` / `code`

Both fields are JSON strings representing a single Workato recipe step. Key fields within the JSON:

| JSON Field | Description |
|---|---|
| `as` | Step alias (anonymized hash) |
| `number` | Step number within the recipe |
| `keyword` | Step type (e.g. `trigger`, `action`, `if`) |
| `provider` | Connector/app name (e.g. `workato_recipe_function`) |
| `name` | Action name within the provider |
| `skip` | Whether the step is skipped |
| `uuid` | Unique identifier for the step |
| `input` | Input parameters for the step (PII redacted in `pii_removed_code`) |
| `extended_input_schema` | Schema definition for inputs |
| `extended_output_schema` | Schema definition for outputs |

---

## PII Redaction: `code` vs `pii_removed_code`

Every row differs between the two columns. Redaction applies two strategies:

### Strategy 1 — Value replaced with `"-- REDACTED --"` (key retained)

These fields exist in both versions but their values are blanked out in `pii_removed_code`:

| Field | What it contains | Example (raw) |
|---|---|---|
| `lhs` / `rhs` | Condition operands (data pills or literal values) | `#{_dp('{"pill_type":"output","provider":"foreach",...}')}` |
| `name` | Step/field names | `assets`, `#{_dp(...)}` |
| `value` / `value_default` | Configured values and defaults | Data pill expressions |
| `email` | Email addresses | `kevin.deng@workato.com` |
| `body` | HTTP request bodies | JSON/text with embedded data pills |
| `sql` | SQL query strings | Raw SQL with data pills injected |
| `path` | API endpoint paths | `/JSSResource/computers/match/#{_dp(...)}` |
| `text` / `section_text` / `label_text` | User-visible text content | `Please wait while I update Salesforce...` |
| `title` (input-level) | Step titles that contain data pill expressions | Data pill expressions |
| `stop_reason` | Error/stop messages | `Unauthorized` |
| `schema` / `parameters_schema_json` / `result_schema_json` / `list_item_schema_json` | Inline schema definitions | Large JSON schema strings |
| `flow_id` (inside input) | Referenced recipe IDs | `50375798` |
| `table_id` / `field_id` / `function_id` / `block_id` | Internal resource IDs (UUIDs or integers) | `11fbe9a6-a16d-4d7e-86ea-afe42ec03005` |
| `____source` | Source list for foreach loops | Data pill expressions |
| `http_status_code` | HTTP status codes | `200` |
| `limit` / `max_retry_count` / `retry_interval` | Numeric configs | `100`, `0`, `2` |
| `content_type` / `col_sep` / `op_integer` / `order_direction` | Format/operator settings | `json`, `comma`, `eq`, `asc` |
| `block_type` / `button_type` / `function_type_id` / `module_id` | UI/structural type identifiers | `section_with_text`, `continue_flow` |
| UUID-format keys (dynamic fields) | Dynamically-named input fields keyed by UUID | Field mapping values |

### Strategy 2 — Field removed entirely from `pii_removed_code`

These fields are present in `code` but completely absent in `pii_removed_code`:

| Field | What it contains | Example (raw) |
|---|---|---|
| `title` (block-level) | Human-readable step titles | `Create assets list` |
| `description` (block-level) | HTML step descriptions | `Create <span class="provider">assets</span> list` |

### What is NOT redacted (preserved in both versions)

The structural skeleton of the recipe is kept intact:

- `keyword` — step type (`trigger`, `action`, `if`, `foreach`, etc.)
- `provider` — connector name (`salesforce`, `slack_bot`, `workato_recipe_function`, etc.)
- `skip` — whether the step is skipped
- `uuid` / `as` — step identifiers
- `number` — step order
- `extended_input_schema` / `extended_output_schema` — schema shape (but not inline `schema` values)
- Nesting structure (`block`, `block[*].block`, etc.)

### Summary

The redaction is intentionally broad — it targets **any user-configured value**, not just traditional PII (names, emails). This is because recipe input values often contain customer data references, API keys, SQL queries, or data pill expressions that could reveal customer data structures. The preserved information is purely structural: what connectors are used, how steps are ordered, and how the flow branches.

---

## Comments: `has_comment` Field

The `has_comment` boolean column indicates whether a step in the recipe has a user-written comment attached. Comments are free-text annotations added by recipe authors to explain the purpose of a step.

### Where comments appear in the JSON

Comments appear as a `comment` key inside the step object in `code` / `pii_removed_code`. They are preserved in both versions (i.e., **not redacted**).

### Example — step without a comment (`has_comment = false`)

```json
{
  "as": "a1b2c3d4",
  "number": 1,
  "keyword": "action",
  "provider": "salesforce",
  "name": "search_records",
  "skip": false,
  "uuid": "11fbe9a6-a16d-4d7e-86ea-afe42ec03005",
  "input": { "object": "Contact", "query": "-- REDACTED --" }
}
```

### Example — step with a comment (`has_comment = true`)

```json
{
  "as": "e5f6g7h8",
  "number": 2,
  "keyword": "action",
  "provider": "slack_bot",
  "name": "post_message",
  "skip": false,
  "uuid": "22ace0b7-b27e-4e8f-97fb-bfe53fd14116",
  "comment": "Notify the #ops channel whenever a new Salesforce contact is created.",
  "input": { "channel": "-- REDACTED --", "text": "-- REDACTED --" }
}
```

### Example — trigger step with a comment

```json
{
  "as": "i9j0k1l2",
  "number": 0,
  "keyword": "trigger",
  "provider": "workato_recipe_function",
  "name": "callable_recipe_trigger",
  "skip": false,
  "uuid": "33bdf1c8-c38f-4f90-a8gc-cfe64ge25227",
  "comment": "Entry point called by the parent orchestration recipe. Expects order_id and customer_email as inputs.",
  "input": {}
}
```

### Notes on comments

- Comments are short, free-text strings authored by the recipe developer — typically 1–3 sentences.
- They are preserved verbatim in `pii_removed_code` (not redacted), because they describe step intent rather than contain data values.
- Only a minority of steps have comments; most recipes are sparsely annotated.
- `has_comment = true` rows are especially valuable for intent understanding, since they provide a human label for what a step is doing.

---

## Notes

- `data_mapper_snapshot`, `data_mapper_snapshot.1`, and `mask_statistics` are fully null and can be dropped safely.
- The `.1`-suffixed columns are redundant duplicates from a join — only the original columns are needed.
- `pii_removed_code` is the safe column to use for any model training or sharing; `code` contains raw unredacted values.
