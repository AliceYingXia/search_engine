# Workato Recipe JSON Schema

Reference for validating Workato recipe JSON exports. Derived from `example/recipe-json-walkthrough.html`.

---

## Top-Level Structure

```json
{
  "flow": {
    "name": "string",
    "description": "string | null",
    "code": { ... },
    "config": [ ... ]
  }
}
```

| Field | Type | Required | Source |
|---|---|---|---|
| `flow.name` | string | Yes | DB column |
| `flow.description` | string \| null | Yes | DB column |
| `flow.code` | object | Yes | DB column (JSON) |
| `flow.config` | array | Yes | Derived from adapter configs |

---

## flow.code — Codeline (Recursive)

The root codeline is always the **trigger** (`number: 0`). It contains a `block` array of child steps, which can themselves have `block` arrays.

### Required Fields

| Field | Type | Rule |
|---|---|---|
| `number` | integer | Root must be `0`; auto-increments in tree order |
| `provider` | string | Must match a `provider` entry in `flow.config` |
| `name` | string | Operation name within the connector |
| `as` | string | Unique alias; used as reference target in data pills |
| `keyword` | string | Must be one of the valid keywords below |
| `uuid` | string | UUID v4 format |

### Optional Fields

| Field | Type | Notes |
|---|---|---|
| `title` | string \| null | Custom display name; `null` when not set |
| `description` | string \| null | Auto-generated HTML; excluded from logic checks |
| `comment` | string | Documentation only; not compiled or executed |
| `input` | object | User-mapped field values (see Input section) |
| `block` | array | Child codelines; only valid on certain keywords |
| `mask_data` | boolean | Hides values in job logs |
| `extended_input_schema` | array | Cached field definitions for inputs (API-fetched) |
| `extended_output_schema` | array | Cached field definitions for outputs (API-fetched) |
| `dynamicPickListSelection` | object | UI cache of human-readable picklist labels |
| `toggleCfg` | object | UI state: which fields were toggled to free-text |
| `visible_config_fields` | array | UI state: which optional fields the user added |

---

## keyword Values

Controls compilation and execution path.

| `keyword` | Role | `block` allowed? |
|---|---|---|
| `trigger` | Entry point; always `number: 0` | Yes — contains all recipe steps |
| `action` | Calls a connector operation | No |
| `if` | Conditional branch | Yes |
| `foreach` | Iterates over a list | Yes |
| `try` | Error-handling wrapper | Yes |
| `catch` | Catches errors from a `try` block | Yes |
| `stop` | Halts the recipe (error or success) | No |
| `filter` | Filters trigger events | No |
| `skip_loop` | Skips current loop iteration | No |

**Rules:**
- The root codeline (`number: 0`) must have `keyword: "trigger"`
- `block` must be absent or empty on keywords that don't allow it

---

## input — Field Value Types

The `input` object maps field names to values. Three value types are valid:

### 1. Static string
```json
"sobject_name": "Opportunity"
```

### 2. V2 Data pill (`_dp`)
```json
"Name": "#{_dp('{\"pill_type\":\"output\",\"provider\":\"workato_pub_sub\",\"line\":\"619faf31\",\"path\":[\"message\",\"order_number\"]}')}"`
```

The JSON payload inside `_dp(...)` must contain:

| Field | Type | Rule |
|---|---|---|
| `pill_type` | string | Must be `"output"` |
| `provider` | string | Required |
| `line` | string | Must match the `as` alias of an existing codeline |
| `path` | array | Array of strings (field navigation path) |

### 3. Formula
```json
"date": "=now + 30.days"
```
Starts with `=`. Compiled as a Ruby/Workato expression.

---

## flow.config — Connector Connections

An array of connector entries. Every `provider` value used in any codeline must have a corresponding entry here.

```json
[
  {
    "keyword": "application",
    "provider": "salesforce",
    "name": "salesforce",
    "skip_validation": false
  }
]
```

| Field | Type | Rule |
|---|---|---|
| `keyword` | string | Must always be `"application"` |
| `provider` | string | Required; must match codeline providers |
| `name` | string | Required |
| `skip_validation` | boolean | Required |

> **Note:** `account_id` is stripped on export for portability. It exists in the DB but must not appear in exported files.

---

## Validation Checklist

When validating a recipe JSON file, check:

- [ ] Top-level `flow` key exists with `name`, `description`, `code`, `config`
- [ ] `flow.code` root has `number: 0` and `keyword: "trigger"`
- [ ] Every codeline has `number`, `provider`, `name`, `as`, `keyword`, `uuid`
- [ ] `keyword` is one of the 9 valid values
- [ ] `block` only appears on: `trigger`, `if`, `foreach`, `try`, `catch`
- [ ] Every `provider` in codelines appears in `flow.config`
- [ ] Every `flow.config` entry has `keyword: "application"` and `skip_validation` (boolean)
- [ ] All `_dp(...)` pills contain valid JSON with `pill_type: "output"`, `provider`, `line`, `path`
- [ ] `line` values in pills reference an `as` alias that exists in the recipe
