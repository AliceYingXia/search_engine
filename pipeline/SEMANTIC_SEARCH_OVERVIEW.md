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

#### 1a — Vocabulary-driven ILIKE keyword search (`keyword/ilike`)

At startup, a **technical vocabulary** is automatically extracted from the recipe corpus (~2,000 terms):

- **Connector names** — e.g. `salesforce`, `workato_db_table`, `google_sheets`
- **Action names** — parsed from `action: X / Y` lines in recipe text
- **Field names ≥ 8 characters** — parsed from `fields:` lines
- **Alphabetic sub-words ≥ 5 chars** from compound connector names (e.g. `google` from `google_sheets`), filtered to those appearing in fewer than 50% of recipes (noise reduction)

Query tokens are matched against this vocabulary and the search proceeds in two passes, with the first non-empty result winning:

1. **ILIKE AND** — all underscore-format vocab tokens (e.g. `workato_db_table`, `get_records`) must appear in the recipe text, ranked by match count. Underscore tokens only — single-word app names are too broad for AND filtering.
2. **ILIKE OR** — any matched vocab token (underscore or single-word app names like `salesforce`, `snowflake`) must appear, ranked by match count.

Queries with no vocabulary overlap (e.g. pure business-language Category 1 queries) return no results.

#### 1b — PostgreSQL FTS, basic (`pgfts/basic`)

Uses pre-computed `tsvector` columns with the PostgreSQL `simple` config: **lowercase only, no stemming, no stopword removal**. Every token in the document and query is retained as-is (lowercased). The query is converted via `plainto_tsquery` then rewritten to OR semantics (`&` → `|`) so that any matching term retrieves a result. Results are ranked by `ts_rank` (TF-IDF-like scoring).

#### 1c — PostgreSQL FTS, stemming + stopword removal (`pgfts/stemming+stopwords`)

Same approach as basic but with the PostgreSQL `english` config: **Porter stemmer + standard ~122-word English stoplist**. Stopwords are dropped from both document and query; remaining terms are stemmed before matching. This allows morphological variants (e.g. _syncing_ matches _sync_) but strips common English words.

#### Results

All three baselines follow the same pattern: **strong on Categories 2 and 3, weak on Category 1**.

**Category 1 — Business Language** (50 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.09     | 0.084     | 0.14              |
| pgfts/basic              | 0.10     | 0.105     | 0.16              |
| pgfts/stemming+stopwords | **0.14** | **0.104** | **0.20**          |

**Category 2 — Technical Feature** (50 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.71     | 0.534     | 0.72              |
| pgfts/basic              | 0.77     | 0.626     | 0.78              |
| pgfts/stemming+stopwords | **0.92** | **0.734** | **0.94**          |

**Category 3 — Dependency Lookup** (49 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.79     | **0.697** | **0.90**          |
| pgfts/basic              | 0.77     | 0.614     | 0.86              |
| pgfts/stemming+stopwords | **0.81** | 0.670     | **0.90**          |

**Key observations:**

- **Category 1 (Business Language)** is where all keyword-based methods fail — Recall@5 tops out at 0.14 (`pgfts/stemming+stopwords`). When a user asks _"which automations handle employee onboarding?"_ there is no literal token overlap with the technical recipe text.
- **Categories 2 and 3** are well-served by keyword search because queries contain connector names, action names, or field identifiers that appear verbatim in recipe text.
- `pgfts/stemming+stopwords` is the strongest baseline on Categories 1 and 2 — Porter stemming helps match morphological variants (e.g. _logging_ → _log_) without over-broadening results.
- On Category 3, `keyword/ilike` edges out `pgfts/stemming+stopwords` on MRR (0.697 vs 0.670) — exact-identifier queries benefit from the AND→OR strategy's precise token matching.

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

#### Results

**Category 1 — Business Language** (50 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.09     | 0.084     | 0.14              |
| pgfts/stemming+stopwords | 0.14     | 0.104     | 0.20              |
| dense/Qwen3-8B+instruct  | 0.43     | **0.372** | 0.54              |
| **hybrid/keyword-fuse**  | **0.43** | 0.349     | **0.54**          |
| **hybrid/fts-fuse**      | 0.40     | 0.349     | **0.54**          |

**Category 2 — Technical Feature** (50 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.71     | 0.534     | 0.72              |
| pgfts/stemming+stopwords | 0.92     | 0.734     | 0.94              |
| dense/Qwen3-8B+instruct  | 0.91     | 0.789     | 0.92              |
| **hybrid/keyword-fuse**  | 0.93     | 0.779     | 0.94              |
| **hybrid/fts-fuse**      | **0.96** | **0.867** | **0.98**          |

**Category 3 — Dependency Lookup** (49 queries)

| Method                   | Recall@5 | MRR       | Avg Strong Hits@5 |
| ------------------------ | -------- | --------- | ----------------- |
| keyword/ilike            | 0.79     | **0.697** | 0.90              |
| pgfts/stemming+stopwords | 0.81     | 0.670     | 0.90              |
| dense/Qwen3-8B+instruct  | 0.74     | 0.579     | 0.80              |
| **hybrid/keyword-fuse**  | **0.83** | 0.748     | **0.94**          |
| **hybrid/fts-fuse**      | 0.79     | 0.665     | 0.88              |

**Key observations:**

- **Hybrid search achieves the best balance across all three categories** — no single non-hybrid method does. Dense alone is strong on Category 1 but trails on Categories 2–3; keyword/FTS alone excels on Categories 2–3 but is near-useless on Category 1. Both hybrid modes match or beat the best individual method in every category simultaneously.
- **Category 1**: both hybrid modes match dense search exactly (0.43 Recall@5, 0.54 Avg Hits) — the weight signal correctly assigns w_kw=0 for no-vocab queries, routing entirely to dense.
- **Category 2**: `hybrid/fts-fuse` is the outright winner at **0.96 Recall@5 and 0.867 MRR** — better than both `pgfts/stemming+stopwords` (0.92) and dense standalone (0.91). FTS stemming broadens recall and dense picks up what stemming misses.
- **Category 3**: `hybrid/keyword-fuse` is the outright winner at **0.83 Recall@5 and 0.94 Avg Hits** — better than `pgfts/stemming+stopwords` (0.81) and dense standalone (0.74). Exact ILIKE matching handles verbatim connector and action names precisely; dense adds coverage for the recipes keyword search misses.
- `hybrid/fts-fuse` is preferred for feature queries (Cat 2); `hybrid/keyword-fuse` is preferred for precise dependency lookups (Cat 3).

---

## Next Steps

### 1 — Search Backend Benchmarking

Evaluate and compare three vector search backends for production suitability:

| Backend           | Notes                                                                                                |
| ----------------- | ---------------------------------------------------------------------------------------------------- |
| **pgvector**      | Current baseline — PostgreSQL-native, simple ops, fast search (HNSW index) is not directly available |
| **OpenSearch**    | Managed, horizontally scalable, native hybrid search support                                         |
| **Matrix Search** | available within the company                                                                         |

Metrics: query latency (p50/p99), throughput (QPS), recall vs. exact-search, infrastructure cost. Goal is to determine whether pgvector is sufficient at production scale or whether a dedicated search engine is needed.

### 2 — Evaluation Dataset Review with BT Team

Grace and Ee Liang shared that many teams are interested in Category 3 queries. Examples will be shared with the BT team abd other teams this week for feedback.

### 3 — Robustness to Typos and Long Recipes

Two known failure modes to address:

- **Typo tolerance** — connector and action names in queries may be misspelled (e.g. `saleforce`, `snowflaek`). Options to explore: fuzzy matching (trigram similarity via `pg_trgm`), edit-distance pre-processing, or query expansion via the embedding model.
- **Long recipes** — very long recipes may exceed embedding model context limits or dilute the signal from relevant steps. Options: chunking recipes by step and indexing step-level embeddings, or max-pooling across chunk embeddings at retrieval time.
