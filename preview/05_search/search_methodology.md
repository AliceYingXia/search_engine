# Search Methodology

End-to-end description of how the recipe search pipeline turns a user message into a ranked list of recipes.

## Architecture overview

```
   user message
        │
        ▼
┌──────────────────────┐
│  Qwen 3.5 35B agent  │   agent.py
│   (LLM, Baseten)     │   - expand shorthand
│                      │   - emit (query, dense_query, tag)
└──────────┬───────────┘
           │ tool call: search_recipe(...)
           ▼
┌──────────────────────────────────────────────────────────┐
│ search_recipes.py                                        │
│                                                          │
│  ┌─────────────────────┐                                 │
│  │ Dictionary filters  │  connectors / actions / fields  │
│  └──────────┬──────────┘                                 │
│             │                                            │
│   ┌─────────┴─────────┐                                  │
│   ▼                   ▼                                  │
│  BM25              dense kNN                             │
│  (search_text,    (combined_qwen,                        │
│   description,     FAISS HNSW,                           │
│   usage)           cosine)                               │
│   │                   │                                  │
│   └────────┬──────────┘                                  │
│            ▼                                             │
│      RRF fusion (k=60)                                   │
│            │                                             │
│            ▼                                             │
│      mget hydrate                                        │
└────────────┬─────────────────────────────────────────────┘
             ▼
       ranked list → agent → user
```

The agent never ranks; it only normalizes the query and routes it. All ranking happens inside OpenSearch.

## 1. LLM pre-processing — `agent.py`

The system prompt instructs the LLM to do three things before invoking the tool. **No intent classification** — routing is decided server-side from the dictionary filter count (see §3).

### 1.1 Expand shorthand
Connector and process abbreviations are canonicalized so they match the corpus vocabulary:

| Shorthand | Expanded |
|---|---|
| SF / SFDC | Salesforce |
| NS | NetSuite |
| HS | HubSpot |
| MS Teams / MST | Microsoft Teams |
| GS | Google Sheets |
| BQ / BigQ | BigQuery |
| Q2C / QTC | "quote to cash" + Salesforce + NetSuite |
| O2C | "order to cash" + Salesforce + NetSuite |
| P2P | "procure to pay" + NetSuite + Coupa |

### 1.2 Build `query` (for BM25)
Strip filler (`please`, `can you`, `show me`, `find`, `all`, …) but keep connector names, object/field names, action verbs (`sync`, `create`, `update`, `send`), and snake_case identifiers. Corpus boilerplate (`automation`, `workato`, `recipe`, …) does **not** need stripping — the index analyzer removes it server-side.

### 1.3 Build `dense_query` (for kNN)
**Always required.** The LLM doesn't know whether dense will actually run — that depends on the filter count computed inside the tool — so it provides `dense_query` every time and the server decides whether to use it.

Phrased as a clean noun-phrase semantic description (`"for ..."`, `"between ..."`, `"that handle ..."`). Unlike `query`, prepositions and modifiers are preserved — embeddings need surrounding context to anchor — but corpus boilerplate must be stripped manually because the embedding model doesn't pre-filter.

> **Why two queries?** They optimize different signals. `query` is lexically aggressive (precision via keywords); `dense_query` is semantically clean (recall via meaning).

## 2. Dictionary-based filters

The `query` parameter is also scanned for known connectors, actions, and field names.
Matches become hard OpenSearch filters that constrain **both** retrieval legs, guaranteeing
every candidate document carries those exact attributes.

### 2.1 The dictionaries

Three vocabularies are loaded from `01_process_data/cleaned/dictionaries_full.json`:

| Dictionary | Examples | Target field (keyword) |
|---|---|---|
| `connectors` | salesforce, netsuite, slack, hubspot, ... | `connectors` |
| `actions` | sync, create, update, send, fetch, ... | `actions` |
| `fields` | account, contact, opportunity, lead, ... | `fields` |

At load time, each entry is **Porter-stemmed** and a `stem → [originals]` map is built.
`accounts` and `account` both stem to `account`, so they share a bucket:

```
{"account": ["account", "accounts"]}
```

This lets singular/plural variants match a single query token without storing them as
separate index keys.

### 2.2 Query-side matching ([search_recipes.py:106-137](search_recipes.py#L106-L137))

For each unique stem in the user's `query`:

1. **Tokenize** the query (`[A-Za-z0-9_]+` regex, lowercase).
2. **Stem** each token (Porter).
3. **Look up** the stem against the three dictionaries with precedence
   **`connectors > actions > fields`**. A stem hits at most one bucket — the first that
   matches. This deterministically resolves ambiguous words: e.g., `lead` could be either
   an action or a field, but precedence settles it.
4. **Expand** the hit to all originals sharing that stem (singular/plural variants).
5. Tokens with no dictionary hit are dropped from filter construction (they still drive
   BM25 ranking through the `query` parameter — only filter assembly ignores them).

### 2.3 Filter assembly

Matched stems are grouped by their target field and emitted as OpenSearch filter clauses:

| Combination | Operator | Clause |
|---|---|---|
| Variants of one stem | OR | `term` (single original) or `terms` (multiple originals) |
| Distinct stems in the same field | AND | wrapped in a `bool.filter` |
| Stems across different fields | AND | separate clauses in the top-level filter list |

### 2.4 Worked example

Query: *"sync salesforce accounts and contacts"*

| Step | Result |
|---|---|
| Tokens | `[sync, salesforce, accounts, and, contacts]` |
| Stems | `{sync, salesforc, account, and, contact}` |
| `connectors` lookup | `salesforc → [salesforce]` |
| `actions` lookup | `sync → [sync, syncs, syncing]` |
| `fields` lookup | `account → [account, accounts]`, `contact → [contact, contacts]` |
| `and` | no dictionary hit, dropped |

Emitted filter clauses:

```json
[
  {"term":  {"connectors": "salesforce"}},
  {"terms": {"actions":    ["sync", "syncing", "syncs"]}},
  {"bool":  {"filter": [
    {"terms": {"fields": ["account", "accounts"]}},
    {"terms": {"fields": ["contact", "contacts"]}}
  ]}}
]
```

OpenSearch AND-s these into the top-level `bool.filter`. Every retrieved document must:
- have `connectors: salesforce`, **and**
- have `actions` matching one of `sync` / `syncing` / `syncs`, **and**
- have **both** an account-variant and a contact-variant in its `fields`.

### 2.5 How the filters are applied to retrieval

Both legs run with the same filter set. `_apply_filters` ([search_recipes.py:189-201](search_recipes.py#L189-L201))
wraps the leg's primary query in a `bool` with the filter list:

```
bool:
  must:   <BM25 multi_match | knn query>
  filter: <dictionary filters>  + optional tag filter
```

This means a document missing any required connector/action/field is excluded from both
BM25 hits *and* dense kNN hits before scoring — RRF only ever fuses pre-filtered
candidates. Mentioning `"salesforce"` in the query thus guarantees `connectors: salesforce`
on every result, regardless of which leg ranked it.

### 2.6 Why hard filters

These vocabularies are known, structured metadata extracted from each recipe during
processing. Treating them as filters (rather than learned BM25 boosts or embedding
signals) gives:

- **Precision floor** — no candidate without the required connector / action / field
  slips through, even if it scores highly on the prose fields.
- **Predictability** — the filter set is auditable directly from the query text and
  the dictionary contents; no model behavior to reason about.
- **Speed** — `term`/`terms` filters run against doc-values with no scoring overhead,
  so they're effectively free compared to BM25 or kNN.

## 3. Filter-count-driven routing

Routing is decided server-side from `len(keyword_filters)` — i.e., how many of the three dictionary **fields** (`connectors`, `actions`, `fields`) produced at least one hit on `query`. The LLM does not classify intent.

| # of field filters | Example query | BM25 fields | Dense kNN | Score floors | Embedding call |
|:---:|---|---|---|---|:---:|
| **2 or 3** | `create_record salesforce` → actions + connectors | `search_text` | *(skipped)* | — | no |
| **1** | `slack bot messages` → connectors only | `search_text` | `combined_qwen` | none | yes |
| **0** | `team notifications in chat` → no dict hit | `search_text`, `description`, `usage` | `combined_qwen` | bm25 ≥ 1.5, dense ≥ 0.80 | yes |

### Why this shape

- **2+ filters → BM25 only.** The dictionary has already narrowed the pool to a tight, schema-precise subset (e.g., `actions=create_record AND connectors=salesforce` = 5 docs). Within that set, BM25 ranks well and dense adds nothing — empirically, the dense leg either returns 0 hits above floor or returns hits that were already in the BM25 pool. Skipping dense saves an embedding round-trip.
- **1 filter → hybrid, no dense floor.** One anchor (usually a connector) defines a pool of dozens to hundreds of docs. BM25 picks up exact keyword matches; dense fills in semantically-related docs that BM25's `or` over `search_text` misses. The floor is dropped so dense can contribute its full ranked list to RRF — the filter has already done the hard precision work.
- **0 filters → multi-field BM25 + both floors.** No dict anchor means the pool is the entire 10,754-doc index. BM25 expands to `description` and `usage` for recall, and the `BM25_SCORE_FLOOR=1.5` trims the long low-score tail. Dense applies its 0.80 floor for the same reason.

### What changed from the prior design

Earlier versions required the LLM to classify each query as `technical` / `mixed` / `business_intent` and routed on that label. Two problems:

1. **LLM wobble across runs** — the same prose query was classified `business_intent` on one run and `mixed` on the next, producing very different fused result counts (the floor logic kicked in for one but not the other).
2. **Category was a proxy for filter count.** `technical` queries almost always produced 2+ dict hits; `business_intent` almost always produced 0. Routing directly on the filter count makes the proxy explicit and removes the LLM as a source of variance.

## 4. Retrieval legs

### 4.1 BM25 — `_bm25_query`, `_run_bm25`
- Tuned `k1=0.5`, `b=0.75` ([create_index.py:35](../04_ingest_opensearch/create_index.py#L35)).
- Analyzer `customize_text`: standard tokenizer → lowercase → English stop → **corpus stop** (`automation`, `workato`, `recipe`, `recipes`, `function`, `triggered`, `operations`, `when`) → English stemmer.
- Query type: `multi_match` / `cross_fields` / `or` — treats listed fields as one logical field, good when terms scatter across description/usage.
- Fields searched depend on the routing branch (§3): `search_text` only in the 1-and-2-filter branches, and the trio `search_text` + `description` + `usage` in the 0-filter branch where recall matters most.
- Score floor `BM25_SCORE_FLOOR=1.5` applies **only** in the 0-filter branch.

### 4.2 Dense kNN — `embed_query`, `_run_knn`
- Embedding: Qwen-family model on Baseten, 4096 dims, **L2-normalized client-side** so cosine = dot.
- Index: FAISS HNSW (`ef_construction=256`, `m=16`, `ef_search=100`), `space_type=cosinesimil`.
- Field: **only `combined_qwen`** is queried at search time — a single vector built at embedding time from a concatenated description + usage text. The index mapping also defines `description_qwen` and `usage_qwen` and the ingest job populates them, but no search path reads them; they exist for offline experiments only.
- Score floor `DENSE_SCORE_FLOOR=0.80` applies **only** in the 0-filter branch. In the 1-filter branch the floor is dropped so the full dense ranked list enters RRF (the field filter has already done the precision work). In the 2+-filter branch the dense leg is skipped entirely.

## 5. Tag filter with preflight validity check

Most user queries don't pass a `tag`, but when they do (e.g. *"recipes with tag salesforce"*), tag handling is resolved **once up front** — before any BM25 query or embedding call — by checking whether the tag actually exists in the index.

### 5.1 Preflight — `_tag_exists`

A cheap `count` query asks OpenSearch: *does any document in the index carry this tag?* No scoring, no vector math — just a corpus-wide existence check on the `tag` field.

```python
client.count(index, body={"query": {"match": {"tag": {"query": tag, "operator": "and"}}}})
```

This runs once at the top of `search_recipes` and produces a single boolean: `tag_valid`.

### 5.2 Branch on the result

**If the tag is valid:** the search proceeds normally. Both retrieval legs run with a strict `match` filter on the `tag` field (`operator: and`) applied alongside the dictionary filters. Every returned candidate carries the tag. `tag_matched=True`.

**If the tag is invalid:** the strict filter is dropped entirely. Instead:
1. The tag string is appended to `query` (and to `dense_query` if it was provided).
2. `keyword_filters` is re-extracted from the augmented `query` — so if the "tag" happens to be a dictionary keyword (e.g. `salesforce`), it becomes a hard `connectors: salesforce` filter on its target field.
3. The embedding call is made against the augmented `dense_query` so the vector reflects the tag too.
4. `tag_matched=False` is returned, letting the agent surface a *"no exact tag match, showing closest results"* note to the user.

### 5.3 Why preflight rather than per-leg fallback

The earlier design ran each leg with the strict filter, detected emptiness, then ran a second fallback search. Moving the decision to a single preflight gives:

- **One source of truth for `tag_matched`** — no need to OR the result across BM25 and kNN legs.
- **One embedding call**, not two — the vector is built from the right text the first time.
- **Two OpenSearch calls saved per invalid-tag query** (one for each leg's wasted strict pass).
- **Symmetric BM25 / kNN behavior** — both legs see the same query, dense_query, and filter set; neither has to know about fallback logic.

### 5.4 Worked walkthrough

User types: *"recipes with tag salesforce for syncing accounts"*

Agent's tool call (after the three preprocessing steps):

```
search_recipes(
    query       = "sync salesforce accounts",
    dense_query = "for syncing Salesforce accounts",
    tag         = "salesforce",
)
```

#### Step 1 — Preflight

`search_recipes` runs the existence check first:

```python
client.count(index="bt_recipe",
             body={"query": {"match": {"tag": {"query": "salesforce", "operator": "and"}}}})
```

A count-only request — no scoring, no vectors. OpenSearch returns `{"count": N}`; we only care whether `N > 0`. The result is a single boolean: `tag_valid`.

#### Path A — tag exists (`tag_valid = True`)

**Build dictionary filters** from the original query:
- `salesforce` → `connectors` → `{"term": {"connectors": "salesforce"}}`
- `sync` → `actions` → `{"terms": {"actions": ["sync","syncs","syncing"]}}`
- `accounts` → `fields` → `{"terms": {"fields": ["account","accounts"]}}`

This produces **3 field filters → routing branch: BM25 only** (§3). Dense is skipped; no embedding call is made.

**BM25 leg with the strict tag filter:**

```json
{
  "query": {
    "bool": {
      "must":   {"multi_match": {"query": "sync salesforce accounts", "fields": ["search_text"], "type": "cross_fields"}},
      "filter": [
        {"term":  {"connectors": "salesforce"}},
        {"terms": {"actions":    ["sync","syncs","syncing"]}},
        {"terms": {"fields":     ["account","accounts"]}},
        {"match": {"tag": {"query": "salesforce", "operator": "and"}}}
      ]
    }
  }
}
```

Every returned doc carries `tag=salesforce` and satisfies all three dict filters. No RRF needed — BM25 ranks directly.

Return: `(results, tag_matched=True)`. CSV: `requested_tag="salesforce"`, `tag_exists=True`.

#### Path B — tag missing (`tag_valid = False`, e.g. `tag="sfdc"`)

**Augment queries and drop the tag filter:**

```python
query       = "sync salesforce accounts sfdc"
dense_query = "for syncing Salesforce accounts sfdc"
tag         = None
tag_matched = False
```

**Re-extract dictionary filters** from the augmented query. For `sfdc` (not in any dict), nothing changes — still 3 field filters → still BM25 only. For a tag that happens to be a dictionary keyword (e.g. `slack`), it would add a new hard filter and could shift the branch.

**BM25 leg without the tag clause** — the `sfdc` token is just another term in `multi_match`, biasing ranking but excluding nothing.

Return: `(results, tag_matched=False)`. CSV: `requested_tag="sfdc"`, `tag_exists=False`. The LLM tool-result prefix becomes: *"Note: no recipes found with tag 'sfdc'; showing closest general results instead."*

#### Side-by-side

| Step | Path A (tag exists) | Path B (tag missing) |
|---|---|---|
| Preflight `count` | `True` | `False` |
| `query` used | as-is | `"{query} {tag}"` |
| `dense_query` used | as-is (but unused — 2+ filter branch) | as-is (but unused) |
| `keyword_filters` | from original query | re-extracted from augmented query |
| Filter-count branch (§3) | 2+ filters → BM25 only | 2+ filters → BM25 only |
| Tag filter on BM25 | strict `match` | none |
| Dense leg | skipped | skipped |
| Embedding calls | 0 | 0 |
| OpenSearch calls | 1 count + 1 BM25 = 2 | 1 count + 1 BM25 = 2 |
| `tag_matched` returned | `True` | `False` |
| Agent surfaces warning | no | yes |

> If the same user query had produced **only 1 dict filter** (e.g., `tag` not in any dict and the only matched stem were `salesforce`), Path A would run BM25 + dense + RRF instead. The dense leg would always carry the tag filter on the strict path and drop it on the fallback, mirroring BM25.

The preflight is the only step the paths share before diverging. After that, **each leg runs exactly once** — no fallback re-queries, no second embedding call, no per-leg `tag_matched` to reconcile.

## 6. Reciprocal Rank Fusion

`_rrf_fusion` ([search_recipes.py:260-271](search_recipes.py#L260-L271)) with `RRF_K=60`:

```
score(doc) = 1/(60 + rank_bm25)   if doc in BM25 results else 0
           + 1/(60 + rank_dense)  if doc in kNN  results else 0
```

Rank-only — score magnitudes from the two legs (which live on very different scales) never enter the formula. Robust and tuning-free.

## 7. Hydration

After ranking, a single `mget` ([search_recipes.py:274-281](search_recipes.py#L274-L281)) pulls source documents, excluding all three 4096-dim vector fields (`description_qwen`, `usage_qwen`, `combined_qwen`) from `_source` to keep the response light. Results are returned as a flat list of dicts with `recipe_uid`, `score`, `score_type` (`bm25` or `rrf`), and the doc metadata.

> The tool returns the **full** ranked list — no top-K cap. Callers (eval harness, agent UI) decide where to cut.

## Design choices worth flagging

- **LLM emits two queries, not one.** Keyword query and semantic query optimize different objectives and must be shaped differently.
- **Hard filters, not learned ones.** Connector/action/field matches become exact filters — fast, predictable, recall-friendly, and easy to debug.
- **Server-side stopword removal mirrors LLM instructions.** Both the BM25 analyzer and the prompt strip the same corpus boilerplate; the embedding leg doesn't, so the LLM must strip it manually from `dense_query`.
- **Floors over thresholds.** Per-leg score floors (BM25 ≥ 1.5 for prose, dense ≥ 0.80) are cheaper than calibrated thresholds and behave well under RRF.
- **No top-K cap inside the tool.** Lets the eval pipeline compute recall@K for any K without re-running search.

## File map

| Stage | File |
|---|---|
| LLM agent + tool wiring | [agent.py](agent.py) |
| Hybrid search implementation | [search_recipes.py](search_recipes.py) |
| Dictionaries (connectors/actions/fields) | [../01_process_data/cleaned/dictionaries_full.json](../01_process_data/cleaned/dictionaries_full.json) |
| Index mapping + analyzers | [../04_ingest_opensearch/create_index.py](../04_ingest_opensearch/create_index.py) |
| Document + vector ingestion | [../04_ingest_opensearch/ingest.py](../04_ingest_opensearch/ingest.py) |
| Embedding generation | [../03_embed/embed_descriptions.py](../03_embed/embed_descriptions.py) |
