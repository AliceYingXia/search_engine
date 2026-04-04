# Retrieval Evaluation

Benchmark results for four retrieval configurations tested against the `workato_recipes` Qdrant collection: three dense models and BGE-M3 sparse evaluated individually.

> **Scope:** All results are based on **single-vector retrieval only** — cosine similarity for dense models, learned token weights for sparse. No hybrid search (dense + sparse fusion), no filters, and no re-ranking have been applied. These results represent a baseline for pure single-vector retrieval.

---

## Retrieval Architecture

### Collection layout

One Qdrant collection (`workato_recipes`) stores all chunks as points. Each point carries four named vectors and a payload:

```
Point
├── vectors
│   ├── dense_bge     (1024 dims, cosine)  ← BGE-M3 dense
│   ├── dense_voyage  (1024 dims, cosine)  ← voyage-code-3
│   └── dense_openai  (3072 dims, cosine)  ← text-embedding-3-large
├── sparse_vectors
│   └── sparse_bge    (variable)           ← BGE-M3 sparse
└── payload
    └── { chunk_type, chunk_id, recipe_name, provider, keyword, ... }
```

All four vectors are stored together so any model can be queried at search time without re-embedding.

### Two-layer chunk types

Every point is one of two types, distinguished by `chunk_type` in the payload:

| `chunk_type` | Description | Count (current dataset) |
|---|---|---|
| `recipe` | One chunk per recipe. Text is a static structural summary: connectors + step tree. | 2 |
| `step` | One chunk per step. Text includes ancestor context (parent `if`/`foreach` conditions) + the step's own fields. | 9 |

**Both types compete freely at query time** — no layer is queried first. The model ranks all 11 chunks together by cosine similarity and returns the top K. This is called Approach 1 (no filter).

### Query flow

```
user query
    │
    ├─► embed with selected model
    │     dense: BGE-M3 / voyage-code-3 / text-embedding-3-large → float vector
    │     sparse: BGE-M3 sparse                                   → token weight map
    │
    └─► Qdrant query_points(using=<vector_name>, limit=K)
            │
            └─► ranked results (recipe chunks and step chunks mixed)
```

Each model queries only its own named vector. A query embedded with BGE-M3 dense is compared against `dense_bge`; sparse against `sparse_bge`. The models never see each other's distances.

**Dense search** returns exactly K results for every query (cosine similarity is defined for all vector pairs).

**Sparse search** returns only chunks with non-zero token overlap with the query — fewer than K results when the query vocabulary matches few chunks.

---

## Golden Evaluation Dataset

Ground truth is defined in `benchmark_golden.json`. Each entry specifies:

- `label` — matches the query label used in `search_qdrant.py`
- `query` — the exact query string sent to the model
- `golden_chunk_ids` — list of acceptable correct answers (any hit counts)
- `notes` — reasoning for the choice

### The 13 benchmark queries and their golden answers

Queries are grouped into five categories. Full definitions with reasoning are in `benchmark_golden.json`.

**Baseline (Q1–Q5)** — core retrieval patterns from the original benchmark

| # | Query | Golden chunk(s) | Key challenge |
|---|---|---|---|
| Q1 | *which recipe handles approved sales orders and updates Salesforce?* | `..._recipe` | Natural language — no technical keywords |
| Q2 | *subscribe to pub sub topic and check if opportunity ID is missing* | `..._step_1` or `..._619faf31` | Technical query; two valid step-level answers |
| Q3 | *add document to knowledge base* | `..._428a2080` | Pure semantic gap — zero token overlap |
| Q4 | *only create a record if it does not already exist* | `..._step_1` or `..._261ab71f` | Conditional logic pattern |
| Q5 | *execute custom code to slow down the workflow* | `..._2a1dae86` | Cross-recipe; correct answer in smaller recipe |

**Find by purpose (Q6–Q7)** — user knows what the recipe *does*, not what it's named

| # | Query | Golden chunk(s) | Key challenge |
|---|---|---|---|
| Q6 | *which recipe creates a new Salesforce opportunity from an approved sales order?* | `..._recipe` or `..._261ab71f` | Combines two intents: Salesforce + sales order |
| Q7 | *which recipe is designed to handle long-running API requests?* | `damien-tan-..._recipe` | General terms ("long-running", "designed to handle") don't appear verbatim in any chunk |

**Find by app (Q8–Q9)** — user queries by connector name

| # | Query | Golden chunk(s) | Key challenge |
|---|---|---|---|
| Q8 | *show me recipes that connect to Salesforce* | `..._recipe`, `..._261ab71f`, or `..._c7d19f6b` | "Connect to" is abstract; any Salesforce chunk is valid |
| Q9 | *which recipe uses the logger connector?* | `damien-tan-..._recipe` or `..._bb40a266` | Exact connector name — favours token matching |

**Find by connection chain (Q10–Q11)** — user queries by trigger or integration point

| # | Query | Golden chunk(s) | Key challenge |
|---|---|---|---|
| Q10 | *which recipe is triggered by a pub sub message?* | `..._619faf31` or `..._recipe` | Trigger-level; "pub sub" appears in chunk text |
| Q11 | *which recipe receives an HTTP request and sends back a response?* | `damien-tan-..._recipe`, `..._bd6826bc`, or `..._fb143077` | Three valid chunks across two steps + recipe |

**Ambiguous/broad (Q12–Q13)** — imprecise language, tests graceful ranking

| # | Query | Golden chunk(s) | Key challenge |
|---|---|---|---|
| Q12 | *show me steps that prevent duplicate records from being created* | `..._step_1` or `..._261ab71f` | Indirect phrasing — "prevent duplicate" must map to an `if` blank-check guard |
| Q13 | *which recipes log information during execution?* | `damien-tan-..._recipe` or `..._bb40a266` | Broad intent; "log" appears in chunk text |

---

## Metrics

All metrics are computed over the retrieved results up to K = 5.

| Metric | Formula | What it measures | Caveat for sparse |
|---|---|---|---|
| **Precision@k** | \|retrieved ∩ golden\| / k | Of the k returned chunks, how many are relevant? | k may be < 5 for sparse when few chunks have token overlap — smaller denominator inflates the score artificially |
| **Recall@5** | \|retrieved ∩ golden\| / \|golden\| | Of all correct answers, how many appear in top 5? Matters for Q2/Q4 with two valid chunks. | Reliable for both dense and sparse |
| **MRR** | mean of 1/rank\_of\_first\_hit | How high does the first correct answer rank? 1.0 = rank 1, 0.5 = rank 2, 0.333 = rank 3, 0 = not found. | Most reliable cross-model comparator — rank position is independent of k |

**Use MRR as the primary metric when comparing dense and sparse models.** Precision@k is unreliable for sparse because the denominator varies with query coverage.

---

## Benchmark Results

> All results are based on **semantic similarity only** (cosine distance for dense, learned token weights for sparse). No hybrid search, no filters, no re-ranking.

### Aggregate scores (n = 13 queries, K = 5)

| Model | Type | Dims | P@k ¹ | R@5 | MRR |
|---|---|---|---|---|---|
| BGE-M3 dense | Dense | 1024 | 0.369 | **1.000** | 0.859 |
| BGE-M3 sparse | Sparse | variable | 0.359 ⚠ | 0.923 | 0.782 |
| voyage-code-3 | Dense | 1024 | 0.354 | 0.974 | 0.859 |
| text-embedding-3-large | Dense | 3072 | 0.338 | 0.949 | **1.000** |

¹ Dense P@k uses fixed k=5. Sparse P@k uses variable k — only chunks with token overlap are returned, so a smaller denominator can inflate the value. Use MRR for cross-model comparison.
⚠ BGE-M3 sparse R@5 < 1.000: it returns zero results for Q12, meaning no chunk has any token overlap with that query.

### Per-query breakdown

| Query | BGE-M3 dense | BGE-M3 sparse | voyage-code-3 | text-embedding-3-large |
|---|---|---|---|---|
| Q1 Baseline: recipe NL | ✗ `update_sobject` (RR=0.333) | ✗ `update_sobject` (RR=0.333) | ✗ `update_sobject` (RR=0.333) | ✓ recipe chunk (RR=1.000) |
| Q2 Baseline: step technical | ✓ trigger (RR=1.000) | ✓ trigger (RR=1.000) | ✓ if step (RR=1.000) | ✓ if step (RR=1.000) |
| Q3 Baseline: semantic gap | ✓ upsert_knowledge (RR=1.000) | ✗ `update_sobject` (RR=0.333) | ✓ upsert_knowledge (RR=1.000) | ✓ upsert_knowledge (RR=1.000) |
| Q4 Baseline: conditional | ✓ create action (RR=1.000) | ✓ create action (RR=1.000) | ✓ if step (RR=1.000) | ✓ if step (RR=1.000) |
| Q5 Baseline: cross-recipe | ✓ sleep step (RR=1.000) | ✓ sleep step (RR=1.000) | ✓ sleep step (RR=1.000) | ✓ sleep step (RR=1.000) |
| Q6 Purpose: SF opportunity | ✓ create action (RR=1.000) | ✓ create action (RR=1.000) | ✓ create action (RR=1.000) | ✓ create action (RR=1.000) |
| Q7 Purpose: long API | ✗ sleep step (RR=0.333) | ✗ receive_request (RR=0.500) | ✗ return_response (RR=0.500) | ✓ recipe chunk (RR=1.000) |
| Q8 App: Salesforce | ✓ create action (RR=1.000) | ✓ update_sobject (RR=1.000) | ✗ upsert_knowledge (RR=0.333) | ✓ recipe chunk (RR=1.000) |
| Q9 App: logger | ✓ recipe chunk (RR=1.000) | ✓ log_message (RR=1.000) | ✓ recipe chunk (RR=1.000) | ✓ recipe chunk (RR=1.000) |
| Q10 Chain: pub sub trigger | ✓ trigger (RR=1.000) | ✓ trigger (RR=1.000) | ✓ trigger (RR=1.000) | ✓ trigger (RR=1.000) |
| Q11 Chain: API endpoint | ✓ receive_request (RR=1.000) | ✓ receive_request (RR=1.000) | ✓ return_response (RR=1.000) | ✓ return_response (RR=1.000) |
| Q12 Broad: prevent duplicates | ✗ trigger (RR=0.500) | ✗ no results (RR=0.000) | ✓ if step (RR=1.000) | ✓ if step (RR=1.000) |
| Q13 Broad: logging | ✓ recipe chunk (RR=1.000) | ✓ log_message (RR=1.000) | ✓ recipe chunk (RR=1.000) | ✓ log_message (RR=1.000) |

---

## Analysis

### P@k for sparse is misleading — use MRR

Sparse search only returns chunks with **non-zero token overlap**. For queries where few chunks share tokens with the query, Qdrant returns k < 5 results. This shrinks the denominator and inflates P@k. Dense models always return exactly 5 results, so their P@k is measured on a consistent denominator. When comparing dense and sparse, **MRR is the reliable metric**.

The most extreme case is Q12: sparse returns **zero results** (k=0, RR=0.000) because "prevent duplicate records from being created" shares no tokens with any chunk. This also explains why sparse R@5=0.923 — the golden chunks for Q12 are entirely invisible to sparse retrieval.

### Where each model struggles

**BGE-M3 dense** fails on two queries:
- Q1 (NL recipe query): ranks `update_sobject` step above the recipe chunk. Dense is trained on structured/code content and latches onto the Salesforce field name.
- Q7 (purpose: long-running API): ranks `invoke_custom_ruby_code` (sleep step) at rank 1. "Long-running" is semantically close to `sleep(70)` — a step-level chunk — rather than the recipe-level summary.

**BGE-M3 sparse** fails on four queries:
- Q1, Q3: same as before — natural language and semantic gap queries have poor token coverage.
- Q7: returns `receive_request` trigger at rank 2, not the recipe chunk.
- Q12: **zero results** — "prevent duplicate records" has no token overlap with any chunk in the collection.

**voyage-code-3** fails on two queries:
- Q1: same as BGE-M3 dense.
- Q8 (Find by app: Salesforce): returns `upsert_knowledge` (workato_rag step) at rank 1 instead of any Salesforce chunk. "Show me recipes that connect to Salesforce" — Voyage appears to associate "connect" semantically with integration/knowledge operations rather than the Salesforce connector specifically.

**text-embedding-3-large** fails on zero queries at rank 1 (MRR=1.000). It places the correct chunk at rank 1 for all 13 queries. However R@5=0.949 — it misses some secondary golden chunks beyond rank 1 on queries with multiple valid answers (Q8 has 3 golden chunks; Q11 has 3).

### Pattern: recipe-level vs step-level confusion

Q1 and Q7 expose a consistent weakness in all non-OpenAI models: when a query is purpose-level ("which recipe handles…", "which recipe is designed to…"), BGE-M3 dense and Voyage return step-level chunks that contain the most query-like tokens, rather than the recipe-level summary. OpenAI generalises across the recipe/step boundary correctly.

### Q12 reveals sparse's hard limit

Q12 *"show me steps that prevent duplicate records from being created"* produces zero sparse results because none of the words — "prevent", "duplicate", "records" — appear in any chunk text. The `if` step that implements this pattern uses tokens like `blank`, `sfdc_opportunity_id`, `conditions` — completely disjoint vocabulary. This is a stronger semantic gap than Q3, and it completely blocks sparse retrieval.

### New insight: voyage-code-3 on Q8

Voyage returns `upsert_knowledge` at rank 1 for "show me recipes that connect to Salesforce". This is the only case where a dense model returns a chunk from the *wrong recipe*. The golden chunks are all from the Salesforce recipe; `upsert_knowledge` is also from that recipe but is a knowledge base step. The failure is not cross-recipe — it is within the correct recipe but at the wrong step. Voyage appears to weight the word "connect" toward integration/linking operations rather than the connector name "salesforce".

---

## Limitations of This Evaluation

1. **Small dataset.** Only 11 chunks from 2 recipes. Results may not generalise — a model that ranks well here could behave differently on a larger, more diverse collection.

2. **Sparse-only, not hybrid.** BGE-M3 sparse is evaluated in isolation here. In practice it is combined with a dense vector via RRF (hybrid search). However, the benchmark results show sparse adds no value over dense on the current query set — there is no query where sparse succeeds but dense fails. The benefit of hybrid would only materialise for exact technical lookup queries (e.g. a specific connector name or field identifier) that are not represented in this benchmark.

3. **No re-ranking.** A cross-encoder re-ranker applied on top of the top-K candidates could improve MRR further, particularly for Q1 and Q7 where the correct chunk appears at rank 3 for most models.

4. **Manually defined golden answers.** The ground truth was assigned by reading chunk text, not by user studies or relevance judgements from domain experts.

5. **R@5 < 1.000 for dense models on the extended benchmark.** With larger golden sets (Q8 has 3 golden chunks, Q11 has 3), some golden chunks do not appear in the top 5 for dense models. This is partly a dataset size effect — with only 11 total chunks, the top 5 covers most of the collection, but not all golden chunks rank highly enough.

---

## Running the Benchmark

```bash
# Full output with results and score table
python3 search_qdrant.py --benchmark --model all

# Score table only (faster to read)
python3 search_qdrant.py --benchmark --model all --score-only

# Single model (dense or sparse)
python3 search_qdrant.py --benchmark --model voyage
python3 search_qdrant.py --benchmark --model sparse

# Single query (no scoring)
python3 search_qdrant.py --query "create Salesforce opportunity" --model openai
python3 search_qdrant.py --query "create Salesforce opportunity" --model sparse
```

Ground truth is stored in `benchmark_golden.json`. Add entries there to extend the benchmark with new queries.
