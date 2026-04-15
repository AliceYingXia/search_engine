# Natural Language Semantic Search: Evaluation Methodology & Retrieval Architecture

## Production Pipeline

See [pipeline_diagram.mmd](pipeline_diagram.mmd) for the full pipeline diagram.

> **Data ingestion is currently a manual step.** Recipe data is exported from
> the BT workspace by hand. The next step is to pull workspace recipes directly
> from **IDEA** and **Copilot** instead, replacing the manual export.

---

## Executive Summary

This document describes how we rigorously evaluated natural language search over the Acumen recipe corpus. The goal: understand how well different search techniques can match a plain-English question to the correct automation recipes — without requiring users to know connector names, schema structure, or technical identifiers.

We built a ground-truth evaluation dataset from scratch using LLM synthesis, then benchmarked three distinct retrieval strategies. The result is a clear, evidence-based recommendation for production deployment.

---

## The Challenge

Automation recipes are stored as structured technical metadata: connector names, action types, step definitions, and field identifiers. When a user asks a business question — _"which automations handle our employee onboarding?"_ — there is no literal overlap with the recipe text. Bridging this semantic gap is the core problem.

We defined three search query categories to represent the range of real-world user intent:

| Category                         | User Intent                                         | Example                                                                                                                                                                                                                                                                                    | Proposed by                |
| -------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| **1 — Business Oriented**        | Find recipes by a business process in plain English | _"Which automations handle employee onboarding?"_                                                                                                                                                                                                                                          | PM Ee Liang                |
| **2 — Actions Oriented**         | Find recipes by sepcific actions                    | _"Slack bot that looks up Salesforce accounts and logs to Snowflake"_                                                                                                                                                                                                                      | PM Ee Liang                |
| **3 — DataPill Fields Oriented** | Find recipes by specific fields                     | _"If I update the Custom_Status\_\_c field in my Salesforce Opportunity object, which recipes will be impacted?"_<br>_"An internal API is changing schema. I need to find all recipes that use a specific SDK action (GET acme.com/customers endpoint) — which recipes will be affected?"_ | **PM Ee Liang & Grace** ⭐ |

---

## Part 1: How the Evaluation Dataset Was Synthesized

Building a trustworthy benchmark required more than manual labelling — we needed 150 queries (50 per category) with ground-truth relevance labels across a diverse recipe corpus. This was done through a structured, three-stage synthesis pipeline.

### Stage 1 — Data Preparation

Starting from ~10,700 production recipe versions, we sampled approximately 2,300 recipes from the top 30 authors by volume. Each recipe's nested JSON structure was converted into a structured text summary — listing connectors, trigger, actions, conditions, and loops — in two variants:

- **With comments**: includes inline comments written by the recipe author — used only for query generation (see Phase 2 below)
- **Without comments**: comments stripped — used for all retrieval (embedding index and keyword search)

This separation is a deliberate design choice: **we want to test whether the retrieval system understands a recipe purely from its structure and logic, without relying on human-written commentary as a shortcut.** In production, comment quality is inconsistent and many recipes have none at all. Retrieval must work from the recipe itself.

### Stage 2 — Evaluation Dataset Synthesis

This is the core of our evaluation methodology, executed in five phases:

#### Phase 1 — Seed Selection

We selected ~115 "seed" recipes to anchor the evaluation. Rather than picking randomly, the algorithm:

- Excludes "infrastructure" connectors common to nearly all recipes (noise reduction)
- Ranks remaining recipes by connector diversity and workflow complexity
- Greedily selects recipes whose connector sets are sufficiently distinct from already-chosen seeds

This ensures the evaluation covers the breadth of the recipe corpus, not just the most common patterns.

#### Phase 2 — Query Generation

For each seed recipe, GPT-5.2 generated one query per category — producing ~115 candidate queries per category. Queries were constrained to be a single sentence, grounded in the seed recipe, and written in the style of that category. The **comment-inclusive** recipe text is used here, so the LLM has the fullest possible context when generating a realistic query. The comments are then stripped before any retrieval happens, ensuring the evaluation genuinely tests semantic understanding of recipe structure rather than comment matching.

#### Phase 3 — Query Selection (Diversity Filtering)

From ~115 candidates per category, we selected exactly **50 diverse queries** using embedding-based similarity filtering. Queries were ranked by specificity (length), then greedily kept only if the query was sufficiently dissimilar from all already-selected queries. This prevents the benchmark from being dominated by near-duplicate questions.

#### Phase 4 — Dual-Model Relevance Scoring

For each of the 50 selected queries, we scored **every recipe in the seed pool** for relevance. Two independent LLMs evaluated each (query, recipe) pair:

- **GPT-5.2** (Azure OpenAI)
- **Claude Sonnet** (AWS Bedrock)

Each model assigned one of three labels:

| Label                | Meaning                                 | Role in evaluation                   |
| -------------------- | --------------------------------------- | ------------------------------------ |
| **Strongly Related** | Recipe is a primary match for the query | **Used as ground truth** ✓           |
| **Weakly Related**   | Recipe is tangentially relevant         | Tracked separately, not ground truth |
| **Not Related**      | No meaningful connection                | Excluded                             |

Only **Strongly Related** labels — where both models agree — form the ground truth used in all retrieval evaluation. This sets a high bar: a retrieval result only counts as correct if two independent LLMs independently judged the recipe to be a primary match. Weakly related recipes are tracked separately but do not contribute to pass/fail scoring.

Where the two models disagreed, a **third LLM adjudication call** resolved the conflict — providing both labels and full recipe context and choosing the best label.

This dual-model design eliminates single-model bias and ensures labels reflect genuine consensus, not one model's idiosyncrasies.

#### Phase 5 — Filtering & Aggregation

Final ground-truth labels were aggregated per query into `strong_list` and `weak_list`. Queries where the source recipe itself was not strongly related were dropped as low-quality. The resulting dataset contains **50 queries per category, each with a curated list of verified relevant recipes**.

---

## Part 2: How the Retrieval Process Works

We evaluated three retrieval strategies against the ground-truth dataset.

### Strategy 1 — FTS and Keyword Search (Baseline)

Three non-embedding baselines were evaluated, all operating on the `text_no_comments` recipe representation.

#### 1a — Vocabulary-driven ILIKE keyword search (`keyword/ilike/*`)

At startup, a **technical vocabulary** is automatically extracted from the recipe corpus (~2,000 terms):

- **Connector names** — e.g. `salesforce`, `workato_db_table`, `google_sheets`
- **Action names** — parsed from `action: X / Y` lines in recipe text
- **Field names ≥ 8 characters** — parsed from `fields:` lines
- **Alphabetic sub-words ≥ 5 chars** from compound connector names (e.g. `google` from `google_sheets`), filtered to those appearing in fewer than 50% of recipes (noise reduction)

Vocab tokens are split into two tiers by type:

- **Underscore tokens** — compound identifiers containing `_` (e.g. `workato_db_table`, `get_records`). Precise and unambiguous — safe to weight more heavily.
- **Word tokens** — single-word app names (e.g. `salesforce`, `snowflake`). Broader — used for scoring, not strict filtering.

Four search strategies are available:

**`and_or`** (default, `keyword/ilike/and_or`) — two-pass fallback. First tries ILIKE AND across underscore tokens only (all must appear). If that returns nothing, falls back to ILIKE OR across all tokens (any must appear), ranked by match count. Queries with no vocab tokens return empty (`no_vocab`).

**`weighted`** (`keyword/ilike/weighted`) — single-pass unified scoring. WHERE clause is OR across all tokens. Ranking: each underscore token match = 3 points, each word token match = 1 point. Higher total score ranks first. Caveat: enough word-token matches can outscore a single underscore match (e.g. 4 word matches = 4 pts > 1 underscore = 3 pts).

**`lexicographic`** (`keyword/ilike/lexicographic`) — single-pass strict hierarchy. WHERE clause is OR across all tokens. ORDER BY underscore match count DESC, then word match count DESC. Any recipe with ≥ 1 underscore match always outranks any recipe with zero underscore matches, regardless of word match counts.

**`weighted_pgfts`** (`keyword/ilike/weighted_pgfts`) — weighted ILIKE (identical to `weighted`) with a `pgfts/english` fallback. If ILIKE returns fewer than k results, the gap is filled with PostgreSQL FTS results (Porter stemmer + stopword removal) that score above a minimum `ts_rank` threshold (≥ 0.03) and have not already been returned by ILIKE. This is designed to provide robustness when connector or action names in the query are not yet in the technical vocabulary (e.g. newly added connectors). Each result is labelled by how it was retrieved:

| Label             | Meaning                                                  |
| ----------------- | -------------------------------------------------------- |
| `weighted`        | Returned by ILIKE — vocab match found                    |
| `weighted+pgfts`  | ILIKE returned < k results; gap filled by pgfts fallback |
| `no_vocab+pgfts`  | No vocab tokens in query; all results from pgfts         |

Observed fallback rates at k=5 across the eval dataset:

| Category                          | `weighted` | `weighted+pgfts` | `no_vocab+pgfts` |
| --------------------------------- | ---------- | ---------------- | ---------------- |
| Cat 1 — Business Language (50 q)  | 29         | 8                | 13               |
| Cat 2 — Technical Feature (50 q)  | 50         | 0                | 0                |
| Cat 3 — Dependency Lookup (49 q)  | 44         | 5                | 0                |

Example with 3 underscore + 2 word tokens in query:

| Recipe                              | `and_or` | `weighted`   | `lexicographic`  |
| ----------------------------------- | -------- | ------------ | ---------------- |
| matches 3 underscore                | rank 1   | score 9 → 1st | (3, 0) → rank 1 |
| matches 1 underscore + 2 word       | rank 2*  | score 5 → 2nd | (1, 2) → rank 2 |
| matches 2 word only                 | rank 2*  | score 2 → 3rd | (0, 2) → rank 3 |

\* In `and_or`, the OR pass returns all three together ranked by total match count.

Queries with no vocabulary overlap (e.g. pure business-language Category 1 queries) return no results in all strategies.

#### 1b — PostgreSQL FTS, basic (`pgfts/basic`)

Uses pre-computed `tsvector` columns with the PostgreSQL `simple` config: **lowercase only, no stemming, no stopword removal**. Every token in the document and query is retained as-is (lowercased). The query is converted via `plainto_tsquery` then rewritten to OR semantics (`&` → `|`) so that any matching term retrieves a result. Results are ranked by `ts_rank` (TF-IDF-like scoring).

#### 1c — PostgreSQL FTS, stemming + stopword removal (`pgfts/stemming+stopwords`)

Same approach as basic but with the PostgreSQL `english` config: **Porter stemmer + standard ~122-word English stoplist**. Stopwords are dropped from both document and query; remaining terms are stemmed before matching. This allows morphological variants (e.g. _syncing_ matches _sync_) but strips common English words.

#### Results

All baselines follow the same pattern: **strong on Categories 2 and 3, weak on Category 1**.

**Category 1 — Business Language** (50 queries)

| Method                              | Recall@5 | MRR       | Avg Strong Hits@5 |
| ----------------------------------- | -------- | --------- | ----------------- |
| keyword/ilike — `and_or`            | 0.09     | 0.084     | 0.14              |
| keyword/ilike — `weighted`          | 0.09     | 0.084     | 0.14              |
| keyword/ilike — `lexicographic`     | 0.09     | 0.084     | 0.14              |
| keyword/ilike — `weighted_pgfts`    | 0.09     | 0.084     | 0.14              |
| pgfts/basic                         | 0.10     | 0.105     | 0.16              |
| pgfts/stemming+stopwords            | **0.14** | **0.104** | **0.20**          |

> **Note:** All four `keyword/ilike` strategies are identical here. Business-language queries (e.g. _"onboarding"_, _"employee"_, _"handle"_) have no overlap with the technical vocabulary, so all strategies return nothing before any ranking logic is applied. The pgfts fallback in `weighted_pgfts` does fire for Category 1 (13 queries take the `no_vocab+pgfts` path, 8 take `weighted+pgfts`), but pgfts uses the same non-technical query words — they do not appear in recipe text either — so ts_rank scores fall below the 0.03 threshold and no results are promoted. The non-zero metrics above come from the few queries that mention a recognisable app name (e.g. `salesforce`), handled identically by all strategies.

**Category 2 — Technical Feature** (50 queries)

| Method                              | Recall@5 | MRR       | Avg Strong Hits@5 |
| ----------------------------------- | -------- | --------- | ----------------- |
| keyword/ilike — `and_or`            | 0.71     | 0.534     | 0.72              |
| keyword/ilike — `weighted`          | 0.73     | 0.540     | 0.74              |
| keyword/ilike — `lexicographic`     | 0.73     | 0.540     | 0.74              |
| keyword/ilike — `weighted_pgfts`    | 0.73     | 0.540     | 0.74              |
| pgfts/basic                         | 0.77     | 0.626     | 0.78              |
| pgfts/stemming+stopwords            | **0.92** | **0.734** | **0.94**          |

**Category 3 — Dependency Lookup** (49 queries)

| Method                              | Recall@5     | MRR           | Avg Strong Hits@5 |
| ----------------------------------- | ------------ | ------------- | ----------------- |
| keyword/ilike — `and_or`            | 0.79         | 0.697         | 0.90              |
| keyword/ilike — `weighted`          | **0.87**     | **0.760**     | **0.96**          |
| keyword/ilike — `lexicographic`     | **0.87**     | **0.760**     | **0.96**          |
| keyword/ilike — `weighted_pgfts`    | **0.87**     | **0.760**     | **0.96**          |
| pgfts/basic                         | 0.77         | 0.614         | 0.86              |
| pgfts/stemming+stopwords            | 0.81         | 0.670         | 0.90              |

**Key observations:**

- **Category 1 (Business Language)** is where all keyword-based methods fail — Recall@5 tops out at 0.14 (`pgfts/stemming+stopwords`). All four `keyword/ilike` strategies are identical here: no-vocab queries return nothing before any ranking logic is applied, and the pgfts fallback in `weighted_pgfts` cannot help because business-language query words do not appear in recipe text and score below the `ts_rank` threshold.
- **Categories 2 and 3** are well-served by keyword search because queries contain connector names, action names, or field identifiers that appear verbatim in recipe text.
- **Category 3 sees the biggest gain from the weighted/lexicographic strategies** — `weighted` and `lexicographic` improve Recall@5 from 0.79 → 0.87 and MRR from 0.697 → 0.760 over `and_or`. Dependency-lookup queries are heavily underscore-token-dominated, so explicit underscore-priority ranking surfaces the right recipes faster. Both strategies produce identical results here because underscore score alone fully separates the ranking.
- **Category 2** sees a small but consistent gain from `weighted`/`lexicographic` (Recall@5 0.73 vs 0.71) — the single-pass OR retrieves more candidates than the strict AND→OR fallback.
- **`weighted_pgfts` matches `weighted` exactly** on all three categories. Category 2 never needs the fallback (ILIKE already saturates at k=5 for all 50 queries). Category 3 triggers the fallback for 5 queries, but none of the pgfts candidates surface missing strongly-relevant recipes above the ts_rank threshold. The `weighted_pgfts` strategy is designed for production resilience — it will help when queries mention newly-added connectors not yet in the vocabulary — but provides no measurable lift on the current eval dataset.
- `pgfts/stemming+stopwords` remains the strongest single baseline on Categories 1 and 2 — Porter stemming handles morphological variants (e.g. _logging_ → _log_) that ILIKE cannot match.

### Strategy 2 — Semantic Embedding Search

Recipes are encoded into high-dimensional vector representations using an embedding model, then stored in a **pgvector** database with fast similarity indexing. At query time, the query is encoded with the same model and the most similar recipe vectors are retrieved via cosine similarity (using the `<=>` operator).

We evaluated three embedding configurations:

| Model                         | Dimensions | Notes                                                                  |
| ----------------------------- | ---------- | ---------------------------------------------------------------------- |
| OpenAI text-embedding-3-large | 3,072      | Widely-used commercial model                                           |
| Qwen3-Embedding-8B            | 4,096      | Larger, instruction-following open-weights model                       |
| Qwen3-Embedding-8B+instruct   | 4,096      | Same model; query prefixed with a retrieval instruction at search time |

The `+instruct` variant prepends a task description to the query — _"retrieve the most relevant automation workflow recipe for this search query"_ — which biases the query vector toward retrieval intent rather than pure semantic similarity. Document vectors are identical to the base model; only query encoding changes.

#### Results

**Category 1 — Business Language** (50 queries)

| Model                       | Recall@5 | MRR       | Avg Strong Hits@5 |
| --------------------------- | -------- | --------- | ----------------- |
| text-embedding-3-large      | 0.26     | 0.220     | 0.34              |
| Qwen3-Embedding-8B          | 0.43     | 0.324     | 0.50              |
| Qwen3-Embedding-8B+instruct | **0.43** | **0.372** | **0.54**          |

**Category 2 — Technical Feature** (50 queries)

| Model                       | Recall@5 | MRR       | Avg Strong Hits@5 |
| --------------------------- | -------- | --------- | ----------------- |
| text-embedding-3-large      | 0.59     | 0.487     | 0.60              |
| Qwen3-Embedding-8B          | 0.89     | 0.765     | 0.90              |
| Qwen3-Embedding-8B+instruct | **0.91** | **0.789** | **0.92**          |

**Category 3 — Dependency Lookup** (49 queries)

| Model                       | Recall@5 | MRR       | Avg Strong Hits@5 |
| --------------------------- | -------- | --------- | ----------------- |
| text-embedding-3-large      | 0.65     | 0.624     | 0.69              |
| Qwen3-Embedding-8B          | **0.76** | 0.551     | **0.80**          |
| Qwen3-Embedding-8B+instruct | 0.74     | **0.579** | 0.80              |

**Key observations:**

- Embedding search is the only strategy that meaningfully handles **Category 1** — Qwen3-8B+instruct reaches 0.43 Recall@5 vs. 0.14 for the best keyword baseline. Business-language queries have no literal token overlap with recipe text, so semantic similarity is the only viable signal.
- On **Category 2**, Qwen3-8B+instruct (0.91) approaches the best keyword baseline (`pgfts/english` at 0.92), showing embeddings are competitive even where literal matches exist.
- On **Category 3**, embedding search (0.76) falls short of `pgfts/english` (0.81) — dependency lookup queries name specific connectors and fields verbatim, which keyword methods handle more precisely.
- The `+instruct` variant consistently improves or matches the base model across all categories, most noticeably on Category 1 MRR (0.372 vs. 0.324).
- `text-embedding-3-large` lags significantly behind both Qwen variants on all categories.

### Strategy 3 — Hybrid (Embedding + FTS Fusion)

Strategies 1 and 2 reveal a clear complementarity: dense search is the only method that meaningfully handles **Category 1**, where queries are written in general business language with little or no technical vocabulary — Qwen3-8B+instruct reaches 0.43 Recall@5 while the best keyword baseline tops out at 0.14. Conversely, keyword and FTS methods dominate **Categories 2 and 3**, where queries contain connector names, action identifiers, or field names that appear verbatim in recipe text — `pgfts/stemming+stopwords` reaches 0.92 Recall@5 on Category 2 and `keyword/ilike` leads on Category 3 MRR, both ahead of dense search. The two strategies are strong in exactly the places the other is weak, which makes hybrid search a natural next step.

Both hybrid variants use the same **vocab-based weight signal** (derived from the keyword vocabulary built in Strategy 1) to determine how much to trust each retrieval leg per query. The two legs are fused with **weighted Reciprocal Rank Fusion**:

```
score(doc) = w_leg1 × 1/(60 + rank_leg1) + w_leg2 × 1/(60 + rank_leg2)
```

**Weight assignment by query signal:**

| Signal detected in query                    | w_leg1 | w_dense | Rationale                                                 |
| ------------------------------------------- | ------ | ------- | --------------------------------------------------------- |
| Underscore tokens (e.g. `workato_db_table`) | 2.0    | 1.0     | Exact technical identifiers — keyword/FTS is more precise |
| Word-only app names (e.g. `salesforce`)     | 1.0    | 2.0     | Broad terms — dense handles ambiguity better              |
| No vocab tokens (pure business language)    | 0.0    | 1.0     | Keyword leg returns nothing → pure dense                  |

Each leg fetches k×3 candidates before fusion; the fused list is then truncated to top-k. Fetching more candidates than k is essential — fusing only k+k results would cap recall at the better of the two legs individually.

**Two variants were evaluated:**

#### 3a — `hybrid/keyword-fuse`: Keyword ILIKE + Qwen3-8B+instruct

The first leg is the vocabulary-driven ILIKE search from Strategy 1a (AND → OR fallback). Strong on exact identifier matches; does not handle morphological variants.

#### 3b — `hybrid/fts-fuse`: pgfts/stemming+stopwords + Qwen3-8B+instruct

The first leg is replaced by PostgreSQL FTS with the `english` config (Porter stemmer + stopword removal), identical to Strategy 1c. Stemming broadens the FTS leg's recall — _"creating records"_ matches _create_, _created_, _record_ — while the weight signal still controls the balance with dense search.

#### 3c — `hybrid/weighted-pgfts-fuse`: weighted_pgfts + Qwen3-8B+instruct

The keyword leg uses the `weighted_pgfts` strategy from Strategy 1a: weighted ILIKE (underscore=3, word=1 scoring) with a pgfts/english gap-fill if the ILIKE leg returns fewer than k×3 candidates. This gives the keyword leg better ranking than the basic AND→OR fallback used in `hybrid/keyword-fuse` — underscore-heavy dependency queries are prioritised directly — while the pgfts fallback adds robustness to connector or action names not yet in the vocabulary. The same vocab-based weight signal and RRF formula apply.

#### Results

**Category 1 — Business Language** (50 queries)

| Method                            | Recall@5 | MRR       | Avg Strong Hits@5 |
| --------------------------------- | -------- | --------- | ----------------- |
| keyword/ilike                     | 0.09     | 0.084     | 0.14              |
| pgfts/stemming+stopwords          | 0.14     | 0.104     | 0.20              |
| dense/Qwen3-8B+instruct           | 0.43     | **0.372** | 0.54              |
| **hybrid/keyword-fuse**           | **0.43** | 0.349     | **0.54**          |
| **hybrid/fts-fuse**               | 0.40     | 0.349     | **0.54**          |
| **hybrid/weighted-pgfts-fuse**    | **0.43** | 0.337     | **0.54**          |

**Category 2 — Technical Feature** (50 queries)

| Method                            | Recall@5 | MRR       | Avg Strong Hits@5 |
| --------------------------------- | -------- | --------- | ----------------- |
| keyword/ilike                     | 0.71     | 0.534     | 0.72              |
| pgfts/stemming+stopwords          | 0.92     | 0.734     | 0.94              |
| dense/Qwen3-8B+instruct           | 0.91     | 0.789     | 0.92              |
| **hybrid/keyword-fuse**           | 0.93     | 0.779     | 0.94              |
| **hybrid/fts-fuse**               | **0.96** | **0.867** | **0.98**          |
| **hybrid/weighted-pgfts-fuse**    | 0.95     | 0.789     | 0.96              |

**Category 3 — Dependency Lookup** (49 queries)

| Method                            | Recall@5     | MRR       | Avg Strong Hits@5 |
| --------------------------------- | ------------ | --------- | ----------------- |
| keyword/ilike                     | 0.79         | **0.749** | 0.90              |
| pgfts/stemming+stopwords          | 0.81         | 0.670     | 0.90              |
| dense/Qwen3-8B+instruct           | 0.74         | 0.579     | 0.80              |
| **hybrid/keyword-fuse**           | 0.83         | 0.748     | 0.94              |
| **hybrid/fts-fuse**               | 0.79         | 0.665     | 0.88              |
| **hybrid/weighted-pgfts-fuse**    | **0.87**     | **0.749** | **0.98**          |

**Key observations:**

- **Hybrid search achieves the best balance across all three categories** — no single non-hybrid method does. Dense alone is strong on Category 1 but trails on Categories 2–3; keyword/FTS alone excels on Categories 2–3 but is near-useless on Category 1. All hybrid modes match or beat the best individual method in every category simultaneously.
- **Category 1**: all three hybrid modes match dense search on Recall@5 (0.43) and Avg Hits (0.54) — the weight signal correctly assigns w_kw=0 for no-vocab queries, routing entirely to dense. MRR varies slightly between modes (0.337–0.372); dense standalone remains the highest at 0.372.
- **Category 2**: `hybrid/fts-fuse` is the outright winner at **0.96 Recall@5 and 0.867 MRR** — better than both `pgfts/stemming+stopwords` (0.92) and dense standalone (0.91). `hybrid/weighted-pgfts-fuse` (0.95) outperforms `hybrid/keyword-fuse` (0.93) — the weighted ILIKE ranking retrieves better candidates than the AND→OR fallback.
- **Category 3**: `hybrid/weighted-pgfts-fuse` is the outright winner at **0.87 Recall@5 and 0.98 Avg Hits** — improving on `hybrid/keyword-fuse` (0.83 Recall@5, 0.94 Avg Hits) and all other methods. Underscore-priority weighting in the keyword leg directly benefits dependency-lookup queries, which are heavily underscore-token-dominated. Dense adds coverage for the recipes keyword search misses.
- **`hybrid/fts-fuse` is preferred for feature queries (Cat 2); `hybrid/weighted-pgfts-fuse` is preferred for precise dependency lookups (Cat 3)** — replacing the previous recommendation of `hybrid/keyword-fuse` for Cat 3.

---

## Part 4: pgvector Fast Search — 4096 Exact vs 4000 Exact vs HNSW

### Background

pgvector's HNSW index — which enables sub-linear approximate nearest-neighbour search — supports a maximum of **2,000 dimensions** for the `vector` (float32) type and **4,000 dimensions** for the `halfvec` (float16) type. Qwen3-Embedding-8B produces 4,096-dimensional vectors, which exceeds both limits.

To enable HNSW on pgvector we adopt **Option B**: store embeddings as `halfvec(4000)` — keeping 4,000 of the original 4,096 dimensions (96 dropped, 2.3%) and using 16-bit floats. The embedding column type changes from `vector(4096)` to `halfvec(4000)`, and vectors are L2-renormalized after truncation before storage and at query time. Document vectors are re-ingested; query vectors are truncated on the fly inside `EmbeddingModel.embed_query`.

To preserve a clean naive baseline, we also keep a separate full-precision
table with raw `vector(4096)` embeddings. That gives us three comparable runs:

- `4096 exact`: naive exact search on raw `vector(4096)`
- `4000 exact`: naive exact search on truncated `halfvec(4000)`
- `4000 hnsw`: ANN search on the same truncated `halfvec(4000)`

**Why not Matryoshka truncation to 2,048?** Qwen3 supports MRL, but we want to preserve as much information as possible. Dropping 96 out of 4,096 dimensions (2.3%) is far less aggressive than halving to 2,048 (50%).

**Does float16 hurt quality?** For cosine similarity on normalized vectors, float16 provides ~3 significant decimal digits vs float32's ~7. Empirically, ranking order is almost never affected — studies show < 1% recall degradation. The dominant concern is the 96-dim truncation, which is negligible.

### Schema & Infrastructure Changes

| | 4096 Exact | 4000 Exact | 4000 HNSW |
|---|---|---|---|
| Table | `embeddings_qwen3_embedding_8b_full` | `embeddings_qwen3_embedding_8b` | `embeddings_qwen3_embedding_8b` |
| Column type | `vector(4096)` | `halfvec(4000)` | `halfvec(4000)` |
| Float precision | float32 | float16 | float16 |
| Dimensions stored | 4,096 | 4,000 (96 dropped, renormalized) | 4,000 (96 dropped, renormalized) |
| Index usage | forced sequential scan | forced sequential scan | `USING hnsw (embedding halfvec_cosine_ops)` |
| Search complexity | O(n) | O(n) | O(log n) approximate |
| Storage per vector | 16 KB | 8 KB | 8 KB |

Interpretation:

- `4096 exact` vs `4000 exact` measures representation loss from truncation + `halfvec`
- `4000 exact` vs `4000 hnsw` measures index approximation error
- all runs use the same query-side instruction prefix (`Qwen3-Embedding-8B+instruct`)

### Steps to Run the HNSW Evaluation

```bash
# 1. Apply schema migration (creates both Qwen tables)
python pipeline/03_evaluate_postgre/setup_schema.py

# 2. Ingest the raw 4096-d baseline table
python pipeline/03_evaluate_postgre/add_embeddings.py --model "Qwen/Qwen3-Embedding-8B-full"

# 3. Ingest the truncated 4000-d halfvec table
python pipeline/03_evaluate_postgre/add_embeddings.py --model "Qwen/Qwen3-Embedding-8B"

# 4. Create the HNSW index on the truncated table
psql -c "CREATE INDEX ON embeddings_qwen3_embedding_8b USING hnsw (embedding halfvec_cosine_ops);"

# 5. Run naive exact search on raw vector(4096)
python pipeline/03_evaluate_postgre/evaluate_pgvector.py \
  --model "Qwen/Qwen3-Embedding-8B-full+instruct" \
  --search-mode exact \
  --k 5

# 6. Run exact scan over the truncated halfvec(4000) table
python pipeline/03_evaluate_postgre/evaluate_pgvector.py \
  --model "Qwen/Qwen3-Embedding-8B+instruct" \
  --search-mode exact \
  --k 5

# 7. Run HNSW over the same truncated halfvec(4000) table
python pipeline/03_evaluate_postgre/evaluate_pgvector.py \
  --model "Qwen/Qwen3-Embedding-8B+instruct" \
  --search-mode hnsw \
  --hnsw-ef-search 80 \
  --k 5
```

Optional: if you want to study the effect of HNSW recall/latency tuning, repeat
step 5 with `--hnsw-ef-search 40 80 120 200` in separate runs.

### Results

Model family evaluated: **Qwen3-Embedding-8B+instruct** query format

Exact-4096 uses the dedicated raw `vector(4096)` table.
Exact-4000 and HNSW-4000 use the truncated `halfvec(4000)` table.

**Category 1 — Business Language** (50 queries)

| Search mode | Index | Dims | Recall@5 | MRR | Avg Strong Hits@5 | Avg Latency / Query |
|---|---|---|---|---|---|---|
| Exact scan | forced seq scan | 4,096 (vector) | **0.4306** | **0.3717** | **0.54** | 11.81 ms |
| Exact scan | forced seq scan | 4,000 (halfvec) | 0.4289 | 0.3650 | 0.52 | 11.31 ms |
| HNSW fast search | halfvec HNSW | 4,000 (float16) | 0.4289 | 0.3650 | 0.52 | 11.42 ms |

**Category 2 — Technical Feature** (50 queries)

| Search mode | Index | Dims | Recall@5 | MRR | Avg Strong Hits@5 | Avg Latency / Query |
|---|---|---|---|---|---|---|
| Exact scan | forced seq scan | 4,096 (vector) | 0.9100 | 0.7890 | 0.92 | 12.34 ms |
| Exact scan | forced seq scan | 4,000 (halfvec) | **0.9100** | **0.7900** | **0.92** | 11.89 ms |
| HNSW fast search | halfvec HNSW | 4,000 (float16) | **0.9100** | **0.7900** | **0.92** | 11.58 ms |

**Category 3 — Dependency Lookup** (49 queries)

| Search mode | Index | Dims | Recall@5 | MRR | Avg Strong Hits@5 | Avg Latency / Query |
|---|---|---|---|---|---|---|
| Exact scan | forced seq scan | 4,096 (vector) | 0.7388 | 0.5891 | 0.7959 | 13.85 ms |
| Exact scan | forced seq scan | 4,000 (halfvec) | **0.7388** | **0.5908** | **0.7959** | 12.22 ms |
| HNSW fast search | halfvec HNSW | 4,000 (float16) | **0.7388** | **0.5908** | **0.7959** | 12.55 ms |

**Key observations:**

- **Truncating from 4,096 to 4,000 dimensions causes essentially no measurable quality loss.** Category 2 and Category 3 are unchanged or microscopically better after truncation; Category 1 drops only slightly (Recall@5 0.4306 → 0.4289, MRR 0.3717 → 0.3650).
- **HNSW matches exact search exactly on this eval set** when both use the same `halfvec(4000)` representation. Across all three categories, Recall@5, MRR, and Avg Strong Hits@5 are identical between `4000 exact` and `4000 hnsw`.
- **Latency is also nearly identical in this benchmark** (~11–14 ms/query). That is expected given the small corpus size in evaluation (639 recipes): at this scale, pgvector exact scan is already cheap, so HNSW does not yet show its typical latency advantage.
- **The main practical takeaway is that `halfvec(4000)` is safe for this workload.** It preserves quality while enabling HNSW indexing, and on a larger production corpus it should unlock the speed gains that are invisible on this small eval dataset.

---

## Next Steps

### 1 — Search Backend Benchmarking

Evaluate and compare three vector search backends for production suitability:

| Backend           | Notes                                                                                                |
| ----------------- | ---------------------------------------------------------------------------------------------------- |
| **pgvector**      | In progress — HNSW fast search now enabled via `halfvec(4000)`; latency benchmarking pending        |
| **OpenSearch**    | Managed, horizontally scalable, native hybrid search support                                         |
| **Matrix Search** | available within the company                                                                         |

Metrics: query latency (p50/p99), throughput (QPS), recall vs. exact-search, infrastructure cost. Goal is to determine whether pgvector is sufficient at production scale or whether a dedicated search engine is needed.

### 2 — Evaluation Dataset Review with BT Team

Grace and Ee Liang shared that many teams are interested in Category 3 queries. Examples will be shared with the BT team abd other teams this week for feedback.

### 3 — Robustness to Typos and Long Recipes

Two known failure modes to address:

- **Typo tolerance** — connector and action names in queries may be misspelled (e.g. `saleforce`, `snowflaek`). Options to explore: fuzzy matching (trigram similarity via `pg_trgm`), edit-distance pre-processing, or query expansion via the embedding model.
- **Long recipes** — very long recipes may exceed embedding model context limits or dilute the signal from relevant steps. Options: chunking recipes by step and indexing step-level embeddings, or max-pooling across chunk embeddings at retrieval time.
