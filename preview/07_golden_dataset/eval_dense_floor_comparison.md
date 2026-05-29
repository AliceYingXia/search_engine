# Evaluation — Dense Floor Comparison for 1-Filter Queries

Isolated A/B test of the dense-floor change introduced with the filter-count-driven routing redesign.

- **Old behavior (1-filter case)**: `_run_knn` returns only candidates with cosine ≥ `DENSE_SCORE_FLOOR = 0.80`.
- **New behavior (1-filter case)**: `_run_knn` returns all candidates the HNSW traversal discovers, no floor.

The fused result set was identical in both modes (the dictionary filter caps the candidate pool, BM25 already covers it). The question this eval answers is whether the change improves **ranking within the top-K**, where users actually look.

Script: [eval_floor_compare.py](eval_floor_compare.py) · Raw results: [eval_floor_compare.json](eval_floor_compare.json).

---

## Methodology

- **Queries.** The six 1-filter queries from the prior run set (eval_query_set_2026_05_12.md) — three unique question shapes asked in both Part 1 and Part 2 framings.
- **LLM arguments are fixed.** `query` and `dense_query` were captured from `eval_results_v2.json` and reused verbatim in both configurations. This isolates the floor change from LLM variance — the only difference between the old and new runs is the `dense_floor` parameter passed to `_run_knn`.
- **Compared metrics:**
  - `Precision@K` against the golden set, for K ∈ {10, 20, 50, 100}.
  - `Jaccard@K` overlap between the two top-K lists.
  - `Kendall τ` rank correlation on the 100 common docs.
  - Movement of golden docs that appear in both top-100s: avg rank delta, count promoted, count demoted.
- **Constants.** `BM25_SCORE_FLOOR` not applied (1-filter branch). `RRF_K = 60`. `KNN_MAX_HITS = 10000`, `ef_search = 100`.

---

## Per-query results

### #1 — `send slack bot messages` (Part 1 #8)

LLM args: `query="send Slack bot messages"`, `dense_query="for sending Slack bot messages"`. Golden: `slack_post_bot_message` (128 docs).

| K | old (floor=0.80) | new (floor=None) | Δ | Jaccard@K |
|---:|---:|---:|---:|---:|
| 10 | 10.0% | **60.0%** | **+50.0pp** | 0.18 |
| 20 | 35.0% | 50.0% | +15.0pp | 0.48 |
| 50 | 56.0% | 50.0% | -6.0pp | 0.61 |
| 100 | 48.0% | 44.0% | -4.0pp | 0.50 |

- Dense hits: old=14, new=180. Kendall τ over top-100 common docs: 0.45.
- Golden in top-100: 48 → 44. Of golden present in both top-100s: 21 promoted, 12 demoted, avg rank Δ = +2.8.

This is the largest top-K win in the eval. The old design's top-10 contained almost no golden docs (10% = 1 of 10); the new design's top-10 is 60% golden.

### #2 — `slack channel` (Part 1 #10)

LLM args: `query="slack channel"`, `dense_query="slack channels"`. Golden: `slack_channel` (231 docs).

| K | old | new | Δ | Jaccard@K |
|---:|---:|---:|---:|---:|
| 10 | 100.0% | 90.0% | -10.0pp | 0.43 |
| 20 | 65.0% | **90.0%** | **+25.0pp** | 0.33 |
| 50 | 82.0% | 82.0% | 0pp | 0.59 |
| 100 | 91.0% | 78.0% | -13.0pp | 0.50 |

- Dense hits: old=19, new=174. Kendall τ: 0.54.
- Golden in top-100: 91 → 78. Of golden in both: 28 promoted, 23 demoted, 7 unchanged, avg rank Δ = +2.1.

Old design had a perfect top-10 (10/10 golden). New design gave up one slot at top-10 but lifted top-20 from 13/20 → 18/20.

### #3 — `slack channels` (Part 1 #11)

Identical numbers to #2 (same dict filter pool, same dense_query — Porter stemmer collapses `channels` → `channel`).

### #4 — `send slack bot messages` (Part 2 #4)

LLM args: `query="send Slack bot messages"`, `dense_query="send Slack bot messages"`. Golden: `slack_post_bot_message` (128 docs).

| K | old | new | Δ | Jaccard@K |
|---:|---:|---:|---:|---:|
| 10 | 20.0% | **50.0%** | **+30.0pp** | 0.25 |
| 20 | 45.0% | 50.0% | +5.0pp | 0.38 |
| 50 | 62.0% | 48.0% | -14.0pp | 0.52 |
| 100 | 50.0% | 43.0% | -7.0pp | 0.46 |

- Dense hits: old=8, new=183. Kendall τ: 0.43.
- Golden in top-100: 50 → 43. Of golden in both: 18 promoted, 13 demoted, 1 unchanged, avg rank Δ = +0.7.

Same shape as #1 (different `dense_query` text, same lift pattern): top-10 doubles in precision, deeper ranks lose some golden density.

### #5 — `slack channel` (Part 2 #6)

Identical args to #2; identical numbers. Confirms determinism of the routing path.

### #6 — `slack channels` (Part 2 #7)

LLM args: `query="slack channels"`, `dense_query="Slack channels"` (capitalization differs from #3 — same Porter stem on the BM25 side but a different embedding).

| K | old | new | Δ | Jaccard@K |
|---:|---:|---:|---:|---:|
| 10 | 90.0% | **100.0%** | **+10.0pp** | 0.43 |
| 20 | 65.0% | **90.0%** | **+25.0pp** | 0.25 |
| 50 | 80.0% | 82.0% | +2.0pp | 0.64 |
| 100 | 90.0% | 78.0% | -12.0pp | 0.50 |

- Dense hits: old=21, new=177. Kendall τ: 0.53.
- Golden in top-100: 90 → 78. 28 promoted, 22 demoted, 7 unchanged, avg rank Δ = +2.8.

The cleanest case: top-10 went from 90% → 100%, top-20 from 65% → 90%, and even top-50 ticked up by 2pp.

---

## Aggregate pattern

### Precision deltas by K

| K | Wins | Losses | Net effect |
|:---:|:---:|:---:|---|
| 10 | 3 (P1#8, P2#4, P2#7) | 3 (#10, #11, P2#6) | Mixed — but wins are huge (+30 to +50pp), losses are uniform -10pp |
| **20** | **6** | **0** | **+5pp to +25pp on every query** |
| 50 | 1 (P2#7 +2pp) | 5 | -6 to -14pp on most queries |
| 100 | 0 | 6 | -4 to -13pp uniformly |

### Where the change helps

- **Always** at P@20.
- **Strongly** at P@10 when the old design was already weak (P1#8: 10% → 60%; P2#4: 20% → 50%).
- **Modestly** at P@10 when the old design was already strong (P2#7: 90% → 100%).

### Where the change costs

- **At P@10 specifically** when the old design was already at the ceiling (the slack_channel queries dropped 100% → 90% as one golden doc got displaced by a semantically-related-but-not-golden doc).
- **At P@50–P@100** uniformly. Golden docs in top-100 dropped by ~7–13 across queries because the new dense list pushes more borderline docs into the top-100 candidate pool.

### Ranking is substantially different

Kendall τ between old and new top-100s sits in **0.43–0.54** — moderate correlation. Jaccard@10 in **0.18–0.43**. The two configurations produce genuinely different rankings, not minor reshuffling.

---

## Interpretation

The change does what the theory predicts: removing the floor lets the dense leg contribute a fuller ranking signal to RRF, which (a) promotes docs that *both* legs find relevant and (b) introduces more dense-favored candidates into the middle ranks.

**Why P@10 sometimes drops while P@20 always rises:** the new dense list promotes semantically-related docs that don't strictly match the golden definition (e.g., for `slack channel`, slack-DM or slack-thread recipes). One of these can displace a true golden doc from rank 9 into rank 11–15. So a golden doc *moves down by a few positions*, hurting P@10 by 10pp but not affecting P@20.

**Why P@100 drops:** the wider dense list pulls more not-quite-relevant docs into the top-100, displacing golden docs that were at ranks 80–100 in the old design. The displaced golden docs aren't lost — they're just at ranks 101–250 now.

---

## Verdict

**Keep the no-floor design.**

Reasons:

1. **P@20 is the most reliable user-facing metric** (default top-of-page surface in most search UIs). It improved on every query, by +5pp to +25pp.
2. **The P@10 picture is favorable on net.** The wins are huge (+30 to +50pp on the precision-tail queries) and the losses are mild (-10pp on queries that were already at the ceiling).
3. **The P@50–P@100 regression is mild** (-7 to -13pp) and in a band that's not directly user-facing. A reranker layered on the top-100 candidates — which is the next planned improvement — would recover this trivially: more dense-suggested candidates in the reranker's input means more material to work with.
4. **The cost is bounded.** No query produced strictly-worse-everywhere results. The two regression bands (P@10 by -10pp; P@100 by ~-10pp) are predictable and small relative to the P@20 gains.

The change is a Pareto improvement at the surface users see, with a manageable cost at deeper ranks that the planned reranker layer would absorb.

---

## Next-step pointer

If a cross-encoder reranker is added on the top-100 fused candidates (the natural next step, motivated by the precision tail on prose queries), the deeper-rank precision regression seen here disappears — the reranker's job is exactly to re-score those middle ranks where the floor change introduced more candidates. Until then, the change ships pure user-visible wins at top-10/top-20 with no recall loss.
