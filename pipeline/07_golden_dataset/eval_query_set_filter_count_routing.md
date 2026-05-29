# Evaluation — Query Set, Filter-Count Routing

Run of the 14-query golden set (Part 1) plus 7 exploratory queries (Part 2)
through the production agent into the filter-count-driven hybrid pipeline.

- **Routing**: decided server-side from `len(_extract_keyword_filters(query))`. No LLM category.
- **Branches**: 2+ filters → BM25 only · 1 filter → BM25 + dense (no dense floor) · 0 filters → multi-field BM25 (floor 1.5) + dense (floor 0.80).
- **Tag handling**: preflight via `_tag_exists`, fallback appends tag to both queries.
- **Constants**: `BM25_SCORE_FLOOR=1.5`, `DENSE_SCORE_FLOOR=0.80`, `RRF_K=60`, `ef_search=100`, `KNN_MAX_HITS=10000`.

Script: [eval_run_v2.py](eval_run_v2.py) · Raw results: [eval_results_v2.json](eval_results_v2.json).

---

## Part 1 — compared with golden datasets

### Summary

| # | user query | branch | n_filters | tag | bm25 | dense | fused | recall | precision |
|---|---|---|:---:|---|---:|---:|---:|---:|---:|
| 1 | show me recipes with action create_record in salesforce | bm25_only | 2 | — | 5 | — | 5 | **100.0%** | **100.0%** |
| 2 | show me recipes with action create_records in salesforce | bm25_only | 2 | — | 5 | — | 5 | **100.0%** | **100.0%** |
| 3 | what recipes use both salesforce netsuite | hybrid_1f | 1 | — | 18 | 16 | 18 | **100.0%** | **100.0%** |
| 4 | what recipes sync Salesforce and NetSuite | hybrid_1f | 1 | — | 18 | 16 | 18 | **100.0%** | **100.0%** |
| 5 | SF NS sync | hybrid_1f | 1 | — | 18 | 16 | 18 | **100.0%** | **100.0%** |
| 6 | which recipes post_bot_message in slack | bm25_only | 2 | — | 128 | — | 128 | **100.0%** | **100.0%** |
| 7 | which recipes post_bot_messages in slack | bm25_only | 2 | — | 128 | — | 128 | **100.0%** | **100.0%** |
| 8 | which recipes send slack bot messages | hybrid_1f | 1 | — | 273 | 180 | 273 | **100.0%** | 46.9% |
| 9 | find recipes which automate team notifications in chat | hybrid_0f | 0 | — | 1610 | 501 | 1928 | 40.6% | 2.7% |
| 10 | find recipes about slack channel | hybrid_1f | 1 | — | 273 | 174 | 273 | **100.0%** | 84.6% |
| 11 | find recipes about slack channels | hybrid_1f | 1 | — | 273 | 174 | 273 | **100.0%** | 84.6% |
| 12 | please find recipes with action create_record in salesforce | bm25_only | 2 | — | 5 | — | 5 | **100.0%** | **100.0%** |
| 13 | …create_record in salesforce **tagged netsuite** | bm25_only | 2 | `netsuite` ✅ | 1 | — | 1 | 20%* | **100.0%** |
| 14 | …create_record in salesforce **tagged asdfghij** | bm25_only | 2 | `asdfghij` ❌ | 5 | — | 5 | **100.0%** | **100.0%** |

*\#13: the user's request (`+tag=netsuite`) is strictly narrower than the golden set; of 5 `salesforce_create_record` golden recipes, exactly 1 has `tag=netsuite` and the pipeline returned it. Against that correct expected set, recall is 100%.

### Per-query notes

**#1, #2, #12 — `create_record` + `salesforce`**
- Dictionary catches actions (`create_record`) + connectors (`salesforce`) = 2 fields → BM25 only, no embedding call.
- Filter pool = 5 = golden. Perfect.

**#3, #4, #5 — Salesforce + NetSuite pair**
- Both stems land in `connectors` (one field) → 1 filter → hybrid + no dense floor.
- BM25 picks up the 18 SF∩NS docs; dense returns 16 within the same pool (HNSW with `ef_search=100` over the 18-doc filtered subset). Fused = 18 = golden.
- The LLM correctly expanded `SF NS` → `Salesforce NetSuite` in #5.

**#6, #7 — `post_bot_message` + `slack`**
- Actions + connectors = 2 fields → BM25 only.
- Porter stemmer collapses `post_bot_messages` → `post_bot_message` for the dict lookup in #7.
- Filter pool = 128 = golden.

**#8 — `send slack bot messages`**
- Only `slack` matches (connectors). 1 filter → hybrid, no dense floor.
- 100% recall over the 273-doc slack-connector pool. Precision = 128/273 = 46.9% — the 145 extras are slack recipes with other actions (`post_message`, `update_message`, etc.).
- The new no-floor dense (180 hits vs the 14 it would have returned under the old 0.80 floor) reshapes top-K precision; see [eval_dense_floor_comparison.md](eval_dense_floor_comparison.md) for details.

**#9 — `team notifications in chat`**
- No dict matches (no connector, no action keyword). 0 filters → multi-field BM25 (with floor 1.5) + dense (with floor 0.80).
- LLM emitted `query="Microsoft Teams notifications"` this run — drifts toward MS Teams docs and away from the Slack-flavored golden. Recall 40.6%, precision 2.7%.
- Recall failure is retrieval-layer (score floors trim borderline golden docs that the prose `query` didn't anchor strongly enough). Reranking can't recover docs that were never retrieved.

**#10, #11 — `slack channel(s)`**
- Only `slack` matches (`channel` is not in the fields dictionary). 1 filter → hybrid.
- Filter pool = 273 slack-connector docs; golden = 231 docs that include the `channel` field. Recall 100%, precision 84.6%.
- The 42 extras are slack recipes that don't touch `channel` field but are in the connector pool.

**#13 — valid tag (`netsuite`)**
- Preflight `_tag_exists("netsuite")` → True. Strict tag filter applied.
- Filter: `actions=create_record AND connectors=salesforce AND tag=netsuite` → 1 doc.

**#14 — invalid tag (`asdfghij`)**
- Preflight → False. Fallback: `query` becomes `"create_record Salesforce asdfghij"`, re-extract dict filters (unchanged since `asdfghij` isn't a dict keyword), `tag=None`.
- Result identical to #1 / #12. CSV row carries `requested_tag="asdfghij"`, `tag_exists=False`.

---

## Part 2 — exploratory (no golden comparison)

### Summary

| # | user query | branch | n_filters | bm25 | dense | fused | notes |
|---|---|---|:---:|---:|---:|---:|---|
| 1 | find recipes that create records in salesforce | hybrid_1f | 1 | 1743 | 1368 | 1743 | Full SF connector pool — `create`/`records` miss the dict (canonical key is `create_record` snake_case). |
| 2 | find recipes that automate Salesforce record creation | hybrid_1f | 1 | 1743 | 1368 | 1743 | Same shape as #1 — LLM emitted `query="create Salesforce records"`. |
| 3 | find recips about quote to cash automation | hybrid_0f | 0 | 261 | 510 | 622 | LLM emitted `query="quote to cash"` without applying the Q2C → SF+NS expansion this run; result fell out of the tight `salesforce_and_netsuite` shape and into a broad 622-doc fused list. |
| 4 | which recipes send slack bot messages | hybrid_1f | 1 | 273 | 183 | 273 | Identical shape to Part 1 #8. |
| 5 | find recipes which automate team notifications in chat | hybrid_0f | 0 | 1852 | 25 | 1865 | Same prose query as Part 1 #9. Different LLM emission this run (`query="team notifications chat"`); 1865 fused. |
| 6 | find recipes about slack channel | hybrid_1f | 1 | 273 | 174 | 273 | Identical shape to Part 1 #10. |
| 7 | find recipes about slack channels | hybrid_1f | 1 | 273 | 177 | 273 | Identical shape to Part 1 #11. |

### Per-query notes

**#1, #2 — prose for Salesforce record creation**
- Dictionary catches only `salesforce`. 1 filter → hybrid. Fused = 1743-doc connector pool.
- The action keyword (`create_record`) isn't matched because the prose form (`create records` / `record creation`) doesn't tokenize to the dict's snake_case stem. Adding prose-form aliases to the actions dict would close this gap.

**#3 — quote to cash**
- The agent's shorthand prompt instructs Q2C → "quote to cash" + Salesforce + NetSuite. Applied in `dense_query` (`"quote to cash Salesforce NetSuite"`) but **not** in `query` (`"quote to cash"`) this run.
- Without "Salesforce" / "NetSuite" in `query`, the dict misses both connectors → 0 filters → multi-field BM25 over the corpus. Fused = 622 docs instead of the tight 18-doc SF∩NS expected.
- This is LLM emission variance; the routing logic is correct given the args it received. Prompt hardening would prevent it.

**#4 — `send slack bot messages`**
- Same dictionary outcome as Part 1 #8.

**#5 — `team notifications in chat`**
- Same shape as Part 1 #9. Different LLM emission across runs produces slightly different fused counts (1865 here, 1928 in Part 1), but the branch and floor logic are identical.

**#6, #7 — `slack channel(s)`**
- Same dictionary outcome as Part 1 #10/#11. Determinism of routing confirmed across the two framings.

---

## Aggregate

### Branch distribution

| Branch | Part 1 count | Part 2 count | Total |
|---|:---:|:---:|:---:|
| `bm25_only` (2+ filters) | 7 | 0 | 7 |
| `hybrid_1f` (1 filter) | 6 | 5 | 11 |
| `hybrid_0f` (0 filters) | 1 | 2 | 3 |

**7 of 21 queries skip the embedding call entirely** (the `bm25_only` branch). For the rest, the dense leg runs once per query.

### Recall on the 12 Part-1 queries with a well-defined recall target

(Excluding #13 — strictly narrower than golden — and counting #14's fallback as 100% recall against `salesforce_create_record`.)

- **100% recall**: 11 of 12 queries (1–8, 10–12, 14)
- **40.6% recall**: 1 query (#9 — pure business prose, 0-filter branch, golden docs below score floors)

### Precision picture (Part 1)

- **100% precision**: 9 queries — all `bm25_only` cases plus the connector-pair queries #3/4/5.
- **84.6% precision**: 2 queries — `slack channel(s)` (#10, #11). 42 extras in the connector pool.
- **46.9% precision**: 1 query — `send slack bot messages` (#8). 145 extras in the slack pool with different actions.
- **2.7% precision**: 1 query — `team notifications in chat` (#9). No dict anchor, prose noise dominates.

### Where reranking would help

- **#8** (precision 46.9%) — 145 false positives in a 273-doc pool. Cross-encoder over top-100 would clear this.
- **#10 / #11** (precision 84.6%) — short tail but reranker would still tighten.
- **#9** — reranker won't help (recall is the blocker). Fix dictionary or floors first.
- **Part 2 #1 / #2 / #4** — same shape as Part 1 #8, same reranker opportunity.
- All `bm25_only` and connector-pair queries — no reranker needed; already tight.
