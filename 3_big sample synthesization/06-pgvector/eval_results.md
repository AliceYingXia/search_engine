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

---

## With-Comments vs. No-Comments Retrieval

**Design:** Inline step comments (e.g. `action: salesforce / search_sobjects  # Fetch Account Name using Account ID`) were stripped from all recipe summaries using `re.sub(r"[ \t]+#[^\n]*", "", summary)`. Two `_nc` (no-comments) embedding tables were created — one for `text-embedding-3-large` and one for `Qwen3-Embedding-8B+instruct` — and evaluated against the same query–recipe pairs. Queries are embedded identically in both variants; only the indexed document text differs.

### Summary

| Model | Variant | Cat1 P@5 | Cat1 R@5 | Cat1 MRR | Cat2 P@5 | Cat2 R@5 | Cat2 MRR |
|---|---|---|---|---|---|---|---|
| text-embedding-3-large | with-comments | 0.3518 | 0.6478 | 0.8321 | 0.1960 | 0.9450 | 0.8577 |
| text-embedding-3-large | no-comments   | 0.2768 | 0.4849 | 0.6310 | 0.1760 | 0.8500 | 0.7373 |
| Qwen3-8B+instruct      | with-comments | 0.3964 | 0.7353 | 0.9371 | 0.2040 | 0.9850 | 0.9425 |
| Qwen3-8B+instruct      | no-comments   | 0.3446 | 0.6337 | 0.8054 | 0.1960 | 0.9500 | 0.8592 |

### text-embedding-3-large: with-comments vs. no-comments

| Metric | With-comments | No-comments | Δ |
|---|---|---|---|
| Category 1 Precision@5 | 0.3518 | 0.2768 | **+0.0750** |
| Category 1 Recall@5    | 0.6478 | 0.4849 | **+0.1629** |
| Category 1 MRR         | 0.8321 | 0.6310 | **+0.2011** |
| Category 2 Precision@5 | 0.1960 | 0.1760 | +0.0200 |
| Category 2 Recall@5    | 0.9450 | 0.8500 | +0.0950 |
| Category 2 MRR         | 0.8577 | 0.7373 | **+0.1204** |

Queries where with-comments wins: **36 / 112** (Cat1) · No-comments wins: **12 / 112**

### Qwen3-Embedding-8B+instruct: with-comments vs. no-comments

| Metric | With-comments | No-comments | Δ |
|---|---|---|---|
| Category 1 Precision@5 | 0.3964 | 0.3446 | **+0.0518** |
| Category 1 Recall@5    | 0.7353 | 0.6337 | **+0.1016** |
| Category 1 MRR         | 0.9371 | 0.8054 | **+0.1317** |
| Category 2 Precision@5 | 0.2040 | 0.1960 | +0.0080 |
| Category 2 Recall@5    | 0.9850 | 0.9500 | +0.0350 |
| Category 2 MRR         | 0.9425 | 0.8592 | **+0.0833** |

Queries where with-comments wins: **28 / 112** (Cat1) · No-comments wins: **8 / 112**

**Key takeaway:** Comments in recipe summaries provide substantial retrieval signal for both models. Category 1 MRR drops by **0.20** for `text-embedding-3-large` and **0.13** for `Qwen3-8B+instruct` when comments are removed. The effect is smaller on Category 2 because those queries tend to match on connector names and trigger/action names that are preserved in both variants. Always index comments.

---

## Examples: With-Comments vs. No-Comments

The examples below are all Category 1 queries evaluated with `text-embedding-3-large`. Each block shows the target recipe's rank in the with-comments index (`rank_w`) and no-comments index (`rank_nc`), along with the first few lines of the recipe text in both forms and the comments that were stripped.

---

### Examples where WITH-COMMENTS helps (comments carry query-relevant signal)

**Example 1** — `query_id: 5770830_q4`

> **Query:** "How can I search for IT incidents using an employee's email, incident number, or description?"
>
> **Target:** `5770830_63320749_v18` | rank_w = **1** | rank_nc = **not retrieved**

The comments on each step explicitly label what each lookup is doing (`# Checks if user email is present`, `# Searches the Incident table based on Incident number`). Stripping them leaves only generic action names like `service_now / search_objects_v2` and `workato_genie / start_workflow`, which no longer surface the "incident", "email", or "description" concepts.

```
WITH COMMENTS:
- trigger: workato_genie / start_workflow  # Trigger : Starts the workflow when search for incidents is requested.
  - action: workato_variable / declare_list  # Creates incident list variable
  - if [and: present]  # Condition Check: Checks if user email is present
    - action: service_now / search_objects_v2  # Searches the User table for the email id.
    - if [and: blank]  # Condition Check: If no record for the email id is present.
      - stop  # Stops the workflow and passes the error message.
  - if [or: present]  # Condition Check: Checks if incident number is present
    - action: service_now / search_objects_v2  # Searches the Incident table based on Incident number

NO COMMENTS:
- trigger: workato_genie / start_workflow
  - action: workato_variable / declare_list
  - if [and: present]
    - action: service_now / search_objects_v2
    - if [and: blank]
      - stop
  - if [or: present]
    - action: service_now / search_objects_v2
```

---

**Example 2** — `query_id: 5770830_q2`

> **Query:** "How can users update an IT support ticket based on whether they are the requester or the assigned agent?"
>
> **Target:** `5770830_63322825_v15` | rank_w = **1** | rank_nc = **3**

Comments describe the role-based branching logic (`# Checks if the given ticket is present`, `# Searches for requester details`) that directly matches the query's "requester or assigned agent" framing.

```
WITH COMMENTS:
- trigger: workato_genie / start_workflow  # Trigger: Starts the workflow when user requests for update to a ticket in Freshservice.
  - action: freshservice_connector / __adhoc_http_action  # Gets the ticket details in Freshservice.
  - if [and: blank]  # Condition Check: Checks if the given ticket is present.
    - stop  # Stops the job with appropriate error message.
  - action: freshservice_connector / search_requesters  # Searches for requester details in Freshservice.
  - action: workato_variable / declare_variable  # User Id as Requester Id

NO COMMENTS:
- trigger: workato_genie / start_workflow
  - action: freshservice_connector / __adhoc_http_action
  - if [and: blank]
    - stop
  - action: freshservice_connector / search_requesters
  - action: workato_variable / declare_variable
```

---

**Example 3** — `query_id: 5770830_q13`

> **Query:** "How can I look up app store permissions for an application?"
>
> **Target:** `5770830_63323445_v4` | rank_w = **1** | rank_nc = **4**

This is a short recipe (4 steps). Comments provide the entire semantic description (`# Searches for App Permissions in Lumos`, `# Responds with App Permissions details`). Without them, only the connector name `lumos_connector` carries any signal.

```
WITH COMMENTS:
- trigger: workato_genie / start_workflow  # Trigger: Starts the workflow when there is request to get Appstore Permissions for an App in Lumos.
  - action: lumos_connector / search_record  # Searches for App Permissions in Lumos.
  - action: workato_custom_code / invoke_custom_ruby_code  # Removes the hidden permissions details.
  - action: workato_genie / workflow_return_result  # Responds with App Permissions details.

NO COMMENTS:
- trigger: workato_genie / start_workflow
  - action: lumos_connector / search_record
  - action: workato_custom_code / invoke_custom_ruby_code
  - action: workato_genie / workflow_return_result
```

---

**Example 4** — `query_id: 206503_q3`

> **Query:** "Which automations start a demo run and provision user access to demo applications?"
>
> **Target:** `206503_63722861_v21` | rank_w = **2** | rank_nc = **not retrieved**

Comments describe the demo provisioning business logic (`# Retrieve demo run and validate`, `# Provision App Access`). The underlying action names (`workato_db_table / get_records`, `workato_recipe_function / execute`) give no hint of the demo provisioning intent.

```
WITH COMMENTS:
- trigger: workato_recipe_function / execute
  - action: workato_db_table / get_records  # Retrieve demo run and validate that it's in the right state to run
  - if [and: equals_to]
    - stop
  - action: workato_db_table / get_records  # Search for demo specified within demo run
  - action: workato_recipe_function / call_recipe  # Provision App Access

NO COMMENTS:
- trigger: workato_recipe_function / execute
  - action: workato_db_table / get_records
  - if [and: equals_to]
    - stop
  - action: workato_db_table / get_records
  - action: workato_recipe_function / call_recipe
```

---

**Example 5** — `query_id: 2136196_q6`

> **Query:** "Which automations route customer support requests to the right team and notify the right people based on the customer account?"
>
> **Target:** `2136196_45586140_v16` | rank_w = **1** | rank_nc = **2**

Comments label each routing branch (`# Fetch Account Name, CSM, AC using Account ID`, `# Account found`, `# Tiago's team`). Without them, the branching logic reads as opaque `if [and: contains]` / `if [and: greater_than]` conditions with no routing or customer-account context.

```
WITH COMMENTS:
- trigger: workato_recipe_function / execute
  - action: salesforce / search_sobjects  # Fetch Account Name, CSM, AC using Account ID
  - if [and: greater_than]  # Account found
    - action: workato_variable / declare_variable
    - if [and: contains]  # Tiago's team
      - action: google_sheets / get_spreadsheet_rows_v4

NO COMMENTS:
- trigger: workato_recipe_function / execute
  - action: salesforce / search_sobjects
  - if [and: greater_than]
    - action: workato_variable / declare_variable
    - if [and: contains]
      - action: google_sheets / get_spreadsheet_rows_v4
```

---

### Examples where NO-COMMENTS helps (comments add noise that hurts ranking)

In these cases the _target_ recipe itself has zero (or very few) comments and is ranked identically in both variants. The improvement comes from the no-comments index removing misleading comment text from _other_ competing recipes, which would otherwise rank above the target due to superficial keyword matches.

---

**Example 1** — `query_id: 206503_q8`

> **Query:** "Which recipes clean up AI conversation threads, files, and knowledge stores after a process completes?"
>
> **Target:** `206503_48764256_v9` | rank_w = **2** | rank_nc = **1** (0 comments in target)

The target recipe has no comments. In the with-comments index, a different recipe ranked #1 whose inline comments mention "thread" or "cleanup" language; stripping those comments removes the false match and lets the target rise to the top.

---

**Example 2** — `query_id: 2136196_q8`

> **Query:** "Which recipes update project and billing milestone amounts on a schedule and generate a report file?"
>
> **Target:** `2136196_46501051_v7` | rank_w = **2** | rank_nc = **1** (0 comments in target)

The target uses `clock / scheduled_event` → `salesforce / search_sobjects_soql` → `csv_parser / create_csv_lines` → `google_drive / upload_file`. All the relevant signal is in action names. Another recipe with schedule-related comments ranks #1 in the with-comments index but drops once comments are stripped.

---

**Example 3** — `query_id: 2973760_q14`

> **Query:** "What automations look up a device management user and return the result to a business process request?"
>
> **Target:** `2973760_48480389_v45` | rank_w = **2** | rank_nc = **1** (0 comments in target)

The target is a compact recipe: `jamf_connector / get_user_by_username` → `lookup_table / search_entries` → `work_genie_connector / complete_run_process_action`. The device-management signal is entirely in connector/action names. A competing recipe's comments boosted it above the target in the with-comments index.

---

**Example 4** — `query_id: 618946_q1`

> **Query:** "Which automations set up and authorize new application connections when requested?"
>
> **Target:** `2136196_53123742_v5` | rank_w = **2** | rank_nc = **1** (1 comment in target)

The single comment in the target (`# For DEMO we use a different connection named after the user's email`) introduces "DEMO" and "email" noise that doesn't match the query. In the no-comments index this noise is gone and the recipe's connector-setup action names (`workato_app / search_connections`, `workato_recipe_function / call_recipe`) rank it #1.

---

**Example 5** — `query_id: 618946_q10`

> **Query:** "Which recipes search for employee records in our HR system and compile the results into a list?"
>
> **Target:** `618946_61123948_v9` | rank_w = **3** | rank_nc = **2** (0 comments in target)

The target has no comments; the improvement is driven by comments in higher-ranked competitors being stripped, reducing their apparent similarity to the HR-search query.

---
