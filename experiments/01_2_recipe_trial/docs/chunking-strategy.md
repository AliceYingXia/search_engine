# Chunking Strategy

Reference for the chunking step that converts cleaned recipe files into Qdrant-ready points.

Script: `chunk_recipes.py`
Input: `example/cleaned/<name>_semantic.json` + `example/cleaned/<name>_tracking.json`
Output: `example/chunks/<name>_chunks.json`

---

## Strategy: Option D — Multi-Level (Recipe + Step)

Each recipe produces two types of chunks:

| Type | Count | Embed text | Purpose |
|---|---|---|---|
| **Type 1 — Recipe** | 1 per recipe | `recipe_summary` | Answers "find recipes that do X" |
| **Type 2 — Step** | 1 per step | Ancestor context + step content | Answers "find the step that does X" |

---

## Type 1 — Recipe Chunk

### Payload

```json
{
  "chunk_type": "recipe",
  "chunk_id": "damien-tan-long-api-request_recipe",
  "source_file": "damien-tan-long-api-request.json",
  "recipe_name": "long api request",
  "connectors": ["workato_api_platform", "workato_custom_code", "logger"],
  "total_steps": 4,
  "keywords_used": ["trigger", "action"]
}
```

| Field | Purpose |
|---|---|
| `chunk_id` | Unique Qdrant point identifier |
| `source_file` | Traces back to the original JSON |
| `connectors` | Filter recipes by connector |
| `total_steps` | Filter by recipe complexity |
| `keywords_used` | Filter by logic types present (e.g. has `foreach`, has `try`) |

No `uuid` — this chunk represents the whole recipe, not a single codeline.

### Embed text

The `recipe_summary` from the semantic file — statically generated from `provider` + `name` + `keyword`. Not from `description`, which can be stale. Example:

```
Recipe: 2.2 Approved Sales Order updates SFDC and adds to KB
Connectors: workato_pub_sub, salesforce, workato_rag
Steps:
- trigger: workato_pub_sub / subscribe_to_topic
  - if
    - action: salesforce / create_custom_object
  - action: salesforce / update_sobject
  - action: workato_rag / upsert_knowledge
```

---

## Type 2 — Step Chunk

### Payload

```json
{
  "chunk_type": "step",
  "chunk_id": "idea-s-hq-2-2-..._261ab71f",
  "source_file": "idea-s-hq-2-2-....json",
  "recipe_name": "2.2 Approved Sales Order updates SFDC and adds to KB",
  "as": "261ab71f",
  "uuid": "...",
  "number": 2,
  "keyword": "action",
  "provider": "salesforce",
  "name": "create_custom_object",
  "depth": 2,
  "parent_as": "_step_1"
}
```

`chunk_id` is `{basename}_{as}`, falling back to `{basename}_step_{number}` when `as` is a synthetic key.

### Embed text

Each step chunk prepends the full ancestor context so the chunk is self-contained:

```
Recipe: 2.2 Approved Sales Order updates SFDC and adds to KB
Context: [trigger: workato_pub_sub / subscribe_to_topic] > [if: [workato_pub_sub > message > sfdc_opportunity_id] blank]
Step: action — salesforce / create_custom_object
Title: Create Opportunity
Input:
  sobject_name: Opportunity
  CloseDate: [job_context > job_created_at]
  Name: [workato_pub_sub > message > order_number]
  StageName: Closed Won
  Description: [workato_pub_sub > message > contact_email]
```

Ancestor context is built by walking the `parent_as` chain upward in the tracking file. For `if` steps, the condition is summarised from the step's `input`.

---

## Ancestor Context

The context line shows every parent block from root down to the immediate parent:

```
Context: [foreach: salesforce / get_records] > [if: status equals approved]
```

Rules:
- `if` steps: condition is extracted from `input.conditions` and rendered as `[if: {lhs} {operand} {rhs}]`
- All other keywords: rendered as `[{keyword}: {provider} / {name}]`
- Root-level steps (direct children of the trigger): show the trigger as context
- The trigger itself has no context line

---

## Synthetic `as` Keys

Steps missing an `as` field (a schema violation in the source data) are assigned a synthetic key `_step_{number}`. This ensures children can still trace ancestry through the step. Synthetic keys are prefixed with `_` and stored in both semantic and tracking files.

---

## `input` Flattening

Nested `input` objects are flattened to `key.subkey` paths for readable embed text:

```
conditions[0].lhs: [workato_pub_sub > message > sfdc_opportunity_id]
conditions[0].operand: blank
```

Condition-level `uuid` fields are skipped during flattening (noise).

---

## File Tree After Chunking

```
example/
├── *.json                          # raw
├── cleaned/
│   ├── *_semantic.json
│   └── *_tracking.json
└── chunks/
    └── *_chunks.json               # flat list of Qdrant-ready points
```
