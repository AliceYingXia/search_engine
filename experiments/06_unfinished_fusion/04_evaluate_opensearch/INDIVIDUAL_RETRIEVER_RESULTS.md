# Individual Retriever Results: OpenSearch Full-Text vs Dense

This note is a focused results document for the **standalone retrievers** in
`pipeline/04_evaluate_opensearch`:

- **Full-text search** via OpenSearch BM25 or coverage scoring
- **Dense vector search** via OpenSearch HNSW kNN

It is intentionally narrower than the main overview. The goal is to make it
easy to compare each retriever on its own before judging whether hybrid fusion
is helping.

---

## Scope

This document tracks results for:

1. **Standalone FTS**
   - script: [evaluate_full_text_search.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_full_text_search.py)
2. **Standalone dense retrieval**
   - script: [evaluate_dense_vectors.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_dense_vectors.py)

The metrics reported here should be read as the baseline to compare against the
hybrid evaluator in [evaluate_hybrid_search.py](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/evaluate_hybrid_search.py).

---

## Evaluation Setup

- Corpus index: `recipes`
- Top-k: `5`
- Categories:
  - `Category 1` — business-language queries
  - `Category 2` — action-oriented / technical workflow queries
  - `Category 3` — datapill-field / dependency lookup queries
- Ground truth:
  - `strong_list` is used for Recall@5, MRR, and strong-hit counting
  - `weak_list` is reported separately for diagnostic context

### Metrics

- `Precision@5`: fraction of top-5 results that are strongly relevant
- `Recall@5`: fraction of strongly relevant recipes recovered in the top 5
- `MRR`: reciprocal rank of the first strongly relevant result
- `Avg strong hits@5`: average number of strong matches in the top 5
- `Avg weak hits@5`: average number of weak matches in the top 5
- `Avg latency/query ms`: mean per-query search latency

---

## Standalone Full-Text Search

### Retriever configuration

Fill in the exact configuration you want to report, for example:

- Config: `english`
- Scoring: `bm25`
- Search field: `text_no_comments`
- Analyzer: `english_underscore`

### Command

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_full_text_search.py --config english --scoring bm25 --k 5
```

### Results

| Category   | Queries | Precision@5 | Recall@5 | MRR   | Avg Strong Hits@5 | Avg Weak Hits@5 |
| ---------- | ------- | ----------- | -------- | ----- | ----------------- | --------------- |
| Category 1 | 50      | 0.0640      | 0.2373   | 0.1837 | 0.3200          | 0.0200          |
| Category 2 | 50      | 0.1680      | 0.8300   | 0.6967 | 0.8400          | 0.2800          |
| Category 3 | 49      | 0.2122      | 0.9456   | 0.8143 | 1.0612          | 0.0816          |

### Notes

- Category 1 should tell us how much plain lexical search can recover from
  business-language phrasing alone.
- Category 2 should show whether BM25 is already strong enough that dense
  retrieval adds little.
- Category 3 should show whether exact or near-exact token matching dominates
  semantic retrieval.

---

## Standalone Dense Retrieval

### Retriever configuration

Fill in the exact dense model you want to report, for example:

- Model: `Qwen/Qwen3-Embedding-8B-full+instruct`
- Search mode: `os-hnsw`
- Vector index: `embeddings_qwen3_embedding_8b_full`

### Command

```bash
venv/bin/python pipeline/04_evaluate_opensearch/evaluate_dense_vectors.py --model "Qwen/Qwen3-Embedding-8B-full+instruct" --k 5
```

### Results

| Category   | Queries | Precision@5 | Recall@5 | MRR   | Avg Strong Hits@5 | Avg Weak Hits@5 | Avg Latency ms |
| ---------- | ------- | ----------- | -------- | ----- | ----------------- | --------------- | -------------- |
| Category 1 | 50      | 0.1080      | 0.4306   | 0.3717 | 0.5400          | 0.1200          | 36.58          |
| Category 2 | 50      | 0.1840      | 0.9100   | 0.7890 | 0.9200          | 0.2200          | 11.28          |
| Category 3 | 49      | 0.1592      | 0.7388   | 0.5891 | 0.7959          | 0.0408          | 9.15           |

### Notes

- Category 1 is the key semantic benchmark. Dense should usually be strongest
  here because business-language queries often lack literal overlap with recipe
  text.
- Category 2 tests whether dense retrieval remains competitive even when the
  query contains technical workflow clues.
- Category 3 tests the limit case where lexical specificity may outperform
  semantic similarity.

---

## Side-by-Side Comparison

Use this table after both standalone runs are available.

| Category   | Best FTS Recall@5 | Best Dense Recall@5 | Best FTS MRR | Best Dense MRR | Better Retriever |
| ---------- | ----------------- | ------------------- | ------------ | -------------- | ---------------- |
| Category 1 | 0.2373            | 0.4306              | 0.1837       | 0.3717         | Dense            |
| Category 2 | 0.8300            | 0.9100              | 0.6967       | 0.7890         | Dense            |
| Category 3 | 0.9456            | 0.7388              | 0.8143       | 0.5891         | FTS              |

### Suggested interpretation

- If **dense** wins clearly on Category 1, hybrid should default toward dense
  for plain-English queries.
- If **FTS** wins clearly on Category 3, hybrid should avoid letting dense
  disturb exact-match rankings too much.
- If Category 2 is mixed, it is the main place where routing or confidence
  gating must earn its keep.

---

## How To Populate This Document

### From FTS output

The FTS script prints summary rows and also writes per-category CSVs such as:

- `os_fts_<config>_<scoring>_category1_k5.csv`
- `os_fts_<config>_<scoring>_category2_k5.csv`
- `os_fts_<config>_<scoring>_category3_k5.csv`

It also appends summary rows into:

- [eval_summary_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/eval_summary_k5.csv)

### From dense output

The dense script prints summary rows and writes a combined CSV such as:

- `eval_results_<model>_os_hnsw_k5.csv`

It also appends summary rows into:

- [eval_summary_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/eval_summary_k5.csv)

---

## Current Status

Current checked-in standalone OpenSearch results at `k=5` are:

- [eval_summary_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/eval_summary_k5.csv)
- FTS detail CSVs:
  - [os_fts_english_bm25_category1_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/os_fts_english_bm25_category1_k5.csv)
  - [os_fts_english_bm25_category2_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/os_fts_english_bm25_category2_k5.csv)
  - [os_fts_english_bm25_category3_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/os_fts_english_bm25_category3_k5.csv)
- Dense detail CSV:
  - [eval_results_Qwen_Qwen3_Embedding_8B_full+instruct_os_hnsw_k5.csv](/Users/alice/project/semantic_search/search_engine/pipeline/04_evaluate_opensearch/eval_results_Qwen_Qwen3_Embedding_8B_full+instruct_os_hnsw_k5.csv)

### Summary of the standalone picture

- **Category 1** is clearly a semantic retrieval problem. Dense substantially
  outperforms FTS on both Recall@5 and MRR.
- **Category 2** is still won by dense retrieval, though FTS remains fairly
  strong. This makes Category 2 the most interesting hybrid case: both signals
  have value, but dense is still the stronger standalone retriever in the
  current OpenSearch setup.
- **Category 3** is clearly a lexical / exact-match problem. FTS strongly
  outperforms dense on both Recall@5 and MRR.

---

## Recommended Reporting Pattern

When sharing results with others, keep the structure simple:

1. Report standalone FTS first.
2. Report standalone dense second.
3. Name the winner per category.
4. Only then evaluate whether hybrid beats the better standalone retriever.

This avoids a common mistake: judging hybrid search only against intuition
instead of against the strongest standalone baseline.
