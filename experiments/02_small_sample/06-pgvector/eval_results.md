# pgvector Search Evaluation Results

**Index:** 115 seed recipes
**Ground truth:** `strong_list` (both GPT-5.2 and Claude rated "Strongly Related")
**Search type:** Exact sequential scan (no HNSW index)
**Metrics:** Precision@5, Recall@5, MRR

---

## Seed Recipe Step Count Statistics

The 115 seed recipes have highly variable complexity:

| Stat | Value |
|------|-------|
| Min | 3 |
| Max | 77 |
| Median | 14 |
| Mean | 20.4 |
| Std dev | 18.6 |
| p25 | 7 |
| p75 | 28 |

| Bucket | Count |
|--------|-------|
| 1–10 | 47 |
| 11–20 | 28 |
| 21–30 | 14 |
| 31–40 | 10 |
| 41–50 | 7 |
| 51–60 | 5 |
| 61–77 | 4 |

The distribution is right-skewed — most recipes are small (≤20 steps), with a long tail of complex workflows. See `step_count_histogram.png`.

---

## Summary (k=5)

Sorted by Category 1 MRR descending.

| Model | Category | Queries | Precision@5 | Recall@5 | MRR | Avg strong hits@5 | Avg weak hits@5 |
|---|---|---|---|---|---|---|---|
| Qwen/Qwen3-Embedding-8B+instruct | Category 1 | 112 | **0.3964** | **0.7353** | **0.9371** | **1.98** | 1.32 |
| Qwen/Qwen3-Embedding-8B+instruct | Category 2 | 100 | **0.2040** | **0.9850** | **0.9425** | **1.02** | **1.49** |
| Qwen/Qwen3-Embedding-8B | Category 1 | 112 | 0.3732 | 0.7033 | 0.9286 | 1.87 | 1.24 |
| Qwen/Qwen3-Embedding-8B | Category 2 | 100 | 0.1980 | 0.9550 | 0.8808 | 0.99 | 1.37 |
| Qwen/Qwen3-Embedding-4B+instruct | Category 1 | 112 | 0.3732 | 0.6987 | 0.9051 | 1.87 | 1.31 |
| Qwen/Qwen3-Embedding-4B+instruct | Category 2 | 100 | 0.2000 | 0.9650 | 0.9123 | 1.00 | 1.43 |
| Qwen/Qwen3-Embedding-4B | Category 1 | 112 | 0.3679 | 0.6854 | 0.8808 | 1.84 | 1.05 |
| Qwen/Qwen3-Embedding-4B | Category 2 | 100 | 0.1920 | 0.9250 | 0.8415 | 0.96 | 1.21 |
| Qwen/Qwen3-Embedding-0.6B+instruct | Category 1 | 112 | 0.3429 | 0.6515 | 0.8443 | 1.71 | 1.21 |
| Qwen/Qwen3-Embedding-0.6B+instruct | Category 2 | 100 | 0.1880 | 0.9150 | 0.8408 | 0.94 | 1.22 |
| text-embedding-3-large | Category 1 | 112 | 0.3518 | 0.6478 | 0.8321 | 1.76 | 1.28 |
| text-embedding-3-large | Category 2 | 100 | 0.1960 | 0.9450 | 0.8577 | 0.98 | 1.37 |
| Qwen/Qwen3-Embedding-0.6B | Category 1 | 112 | 0.3250 | 0.6208 | 0.7955 | 1.63 | 1.14 |
| Qwen/Qwen3-Embedding-0.6B | Category 2 | 100 | 0.1900 | 0.9200 | 0.8353 | 0.95 | 1.31 |
| text-embedding-3-small | Category 1 | 112 | 0.2839 | 0.5446 | 0.6979 | 1.42 | 1.13 |
| text-embedding-3-small | Category 2 | 100 | 0.1860 | 0.8950 | 0.8125 | 0.93 | 1.22 |
| mixedbread-ai/mxbai-embed-large-v1 | Category 1 | 112 | 0.2554 | 0.4530 | 0.6396 | 1.28 | 1.15 |
| mixedbread-ai/mxbai-embed-large-v1 | Category 2 | 100 | 0.1940 | 0.9350 | 0.8262 | 0.97 | 1.25 |
| intfloat/multilingual-e5-large-instruct | Category 1 | 112 | 0.2732 | 0.4744 | 0.6339 | 1.37 | 1.12 |
| intfloat/multilingual-e5-large-instruct | Category 2 | 100 | 0.1880 | 0.9100 | 0.8262 | 0.94 | 1.23 |
| BAAI/bge-m3 | Category 1 | 112 | 0.2321 | 0.4340 | 0.5671 | 1.16 | 0.87 |
| BAAI/bge-m3 | Category 2 | 100 | 0.1920 | 0.9250 | 0.8325 | 0.96 | 1.14 |

---

## text-embedding-3-large  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3518 | 0.6478 | 0.8321 |
| Category 2 | 100 | 0.1960 | 0.9450 | 0.8577 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.76 / 5 | 1.28 / 5 |
| Category 2 | 0.98 / 5 | 1.37 / 5 |

On average, **3.04 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.35 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

---

## text-embedding-3-small  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.2839 | 0.5446 | 0.6979 |
| Category 2 | 100 | 0.1860 | 0.8950 | 0.8125 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.42 / 5 | 1.13 / 5 |
| Category 2 | 0.93 / 5 | 1.22 / 5 |

On average, **2.55 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.15 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

---

## BAAI/bge-m3  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.2321 | 0.4340 | 0.5671 |
| Category 2 | 100 | 0.1920 | 0.9250 | 0.8325 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.16 / 5 | 0.87 / 5 |
| Category 2 | 0.96 / 5 | 1.14 / 5 |

On average, **2.03 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.10 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

**Notes:**
- Weakest model on Category 1 across all metrics — MRR of 0.57 means the first relevant recipe is frequently not near the top.
- Category 2 performance recovers well (MRR 0.83, Recall 0.93), suggesting it handles specific trigger-outcome queries reasonably but struggles with broader process queries.

---

## Qwen/Qwen3-Embedding-0.6B  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3250 | 0.6208 | 0.7955 |
| Category 2 | 100 | 0.1900 | 0.9200 | 0.8353 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.63 / 5 | 1.14 / 5 |
| Category 2 | 0.95 / 5 | 1.31 / 5 |

---

## Qwen/Qwen3-Embedding-0.6B+instruct  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3429 | 0.6515 | 0.8443 |
| Category 2 | 100 | 0.1880 | 0.9150 | 0.8408 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.71 / 5 | 1.21 / 5 |
| Category 2 | 0.94 / 5 | 1.22 / 5 |

### Instruction vs. no instruction (Qwen3-Embedding-0.6B)

| Metric | Without instruction | With instruction | Δ |
|---|---|---|---|
| Category 1 Precision@5 | 0.3250 | 0.3429 | +0.0179 |
| Category 1 Recall@5 | 0.6208 | 0.6515 | +0.0307 |
| Category 1 MRR | 0.7955 | 0.8443 | **+0.0488** |
| Category 2 Precision@5 | 0.1900 | 0.1880 | −0.0020 |
| Category 2 Recall@5 | 0.9200 | 0.9150 | −0.0050 |
| Category 2 MRR | 0.8353 | 0.8408 | +0.0055 |

**Key takeaway:** The instruction prefix gives a meaningful boost on Category 1 (MRR +0.05), with negligible effect on Category 2. Use `+instruct` in production.

---

## Qwen/Qwen3-Embedding-4B  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3679 | 0.6854 | 0.8808 |
| Category 2 | 100 | 0.1920 | 0.9250 | 0.8415 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.84 / 5 | 1.05 / 5 |
| Category 2 | 0.96 / 5 | 1.21 / 5 |

On average, **2.89 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.17 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

---

## Qwen/Qwen3-Embedding-4B+instruct  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3732 | 0.6987 | 0.9051 |
| Category 2 | 100 | 0.2000 | 0.9650 | 0.9123 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.87 / 5 | 1.31 / 5 |
| Category 2 | 1.00 / 5 | 1.43 / 5 |

On average, **3.18 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.43 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

### Instruction vs. no instruction (Qwen3-Embedding-4B)

| Metric | Without instruction | With instruction | Δ |
|---|---|---|---|
| Category 1 Precision@5 | 0.3679 | 0.3732 | +0.0053 |
| Category 1 Recall@5 | 0.6854 | 0.6987 | +0.0133 |
| Category 1 MRR | 0.8808 | 0.9051 | **+0.0243** |
| Category 2 Precision@5 | 0.1920 | 0.2000 | +0.0080 |
| Category 2 Recall@5 | 0.9250 | 0.9650 | +0.0400 |
| Category 2 MRR | 0.8415 | 0.9123 | **+0.0708** |

**Key takeaway:** The instruction prefix gives a strong lift on Category 2 MRR (+0.07), the largest instruction boost across all Qwen3 sizes. Use `+instruct` in production.

---

## Qwen/Qwen3-Embedding-8B  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3732 | 0.7033 | 0.9286 |
| Category 2 | 100 | 0.1980 | 0.9550 | 0.8808 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.87 / 5 | 1.24 / 5 |
| Category 2 | 0.99 / 5 | 1.37 / 5 |

On average, **3.11 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.36 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

---

## Qwen/Qwen3-Embedding-8B+instruct  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.3964 | 0.7353 | 0.9371 |
| Category 2 | 100 | 0.2040 | 0.9850 | 0.9425 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.98 / 5 | 1.32 / 5 |
| Category 2 | 1.02 / 5 | 1.49 / 5 |

On average, **3.30 out of 5** returned results per Category 1 query are either strongly or weakly relevant.
On average, **2.51 out of 5** returned results per Category 2 query are either strongly or weakly relevant.

### Instruction vs. no instruction (Qwen3-Embedding-8B)

| Metric | Without instruction | With instruction | Δ |
|---|---|---|---|
| Category 1 Precision@5 | 0.3732 | 0.3964 | +0.0232 |
| Category 1 Recall@5 | 0.7033 | 0.7353 | +0.0320 |
| Category 1 MRR | 0.9286 | 0.9371 | **+0.0085** |
| Category 2 Precision@5 | 0.1980 | 0.2040 | +0.0060 |
| Category 2 Recall@5 | 0.9550 | 0.9850 | +0.0300 |
| Category 2 MRR | 0.8808 | 0.9425 | **+0.0617** |

**Key takeaway:** The instruction prefix helps across both categories, with a particularly large lift on Category 2 MRR (+0.06). Use `+instruct` in production.

---

## intfloat/multilingual-e5-large-instruct  (k=5)

| Category | Queries | Precision@5 | Recall@5 | MRR |
|---|---|---|---|---|
| Category 1 | 112 | 0.2732 | 0.4744 | 0.6339 |
| Category 2 | 100 | 0.1880 | 0.9100 | 0.8262 |

### Top-5 hit breakdown (avg per query)

| Category | Avg strong hits in top-5 | Avg weak hits in top-5 |
|---|---|---|
| Category 1 | 1.37 / 5 | 1.12 / 5 |
| Category 2 | 0.94 / 5 | 1.23 / 5 |

**Notes:**
- Category 2 performance is solid (MRR 0.83, Recall 0.91), on par with most other models.
- Category 1 is weaker — lower Recall@5 (0.47) and MRR (0.63) suggest it misses several relevant recipes for process-oriented queries.

---

## Model Comparison

| Metric | te-3-large | te-3-small | bge-m3 | Qwen3-0.6B | Qwen3-0.6B+inst | me5-large-inst | mxbai-large | Qwen3-4B | Qwen3-4B+inst | Qwen3-8B | Qwen3-8B+inst |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Cat1 Precision@5** | 0.3518 | 0.2839 | 0.2321 | 0.3250 | 0.3429 | 0.2732 | 0.2554 | 0.3679 | 0.3732 | 0.3732 | **0.3964** |
| **Cat1 Recall@5** | 0.6478 | 0.5446 | 0.4340 | 0.6208 | 0.6515 | 0.4744 | 0.4530 | 0.6854 | 0.6987 | 0.7033 | **0.7353** |
| **Cat1 MRR** | 0.8321 | 0.6979 | 0.5671 | 0.7955 | 0.8443 | 0.6339 | 0.6396 | 0.8808 | 0.9051 | 0.9286 | **0.9371** |
| **Cat2 Precision@5** | 0.1960 | 0.1860 | 0.1920 | 0.1900 | 0.1880 | 0.1880 | 0.1940 | 0.1920 | 0.2000 | 0.1980 | **0.2040** |
| **Cat2 Recall@5** | 0.9450 | 0.8950 | 0.9250 | 0.9200 | 0.9150 | 0.9100 | 0.9350 | 0.9250 | 0.9650 | 0.9550 | **0.9850** |
| **Cat2 MRR** | 0.8577 | 0.8125 | 0.8325 | 0.8353 | 0.8408 | 0.8262 | 0.8262 | 0.8415 | 0.9123 | 0.8808 | **0.9425** |

**Key takeaways:**
- **Best overall:** `Qwen3-Embedding-8B+instruct` leads on every metric across both categories — Category 1 MRR 0.9371, Category 2 MRR 0.9425, Recall@5 0.9850.
- **4B is a strong middle ground:** `Qwen3-4B+instruct` (MRR Cat1 0.9051, Cat2 0.9123) sits between 0.6B+instruct and 8B, offering a good cost/quality trade-off on Baseten without the full 8B cost.
- **Instruction boost is largest at 4B for Category 2:** The +instruct lift on Category 2 MRR is +0.07 for 4B, larger than both 0.6B (+0.005) and 8B (+0.06). Always use `+instruct` with Qwen3 models.
- **Scale wins on Category 1:** Cat1 MRR follows a clear trend — 0.6B (0.84) → 4B (0.91) → 8B (0.94) — confirming model size is the dominant factor for process-oriented queries.
- **Cost/quality trade-off:** `Qwen3-0.6B+instruct` still offers the best value for local/offline use — it matches `text-embedding-3-large` on Category 1 at zero API cost. The 4B and 8B models require Baseten or equivalent GPU hosting.
- **BAAI/bge-m3** and **mxbai-embed-large-v1** remain the weakest on Category 1 (MRR ~0.57–0.64).
- **Category 2 is easier for all models** — most achieve Recall@5 > 0.90 since the strong list is typically a single recipe that is reliably retrieved.
