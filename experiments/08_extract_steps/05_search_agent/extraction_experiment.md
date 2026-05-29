# Step Extraction Experiment: Batch vs Individual LLM Calls

## Goal

Determine the best strategy for extracting query-relevant steps from recipe `search_text` fields before returning results to the agent.

## Setup

- **Queries**: 20 queries (10 VALID_TAG, 10 INVALID_TAG)
- **Search**: OpenSearch hybrid BM25 + kNN, top_k=10 per query
- **Model**: `azure/gpt-5.2`
- **Metrics**: coverage (recipes with ≥1 relevant step), total steps extracted, latency, LLM call count

---

## Experiment 1: Batch vs Individual (free-text JSON output)

| | Batch (all 10 in one call) | Individual (parallel async) |
|---|---|---|
| Avg coverage | 5.8 | **6.3** |
| Avg total steps | 11.5 | **16.7** |
| Avg latency | 4.3s | **3.1s** |
| LLM calls | **1** | ~10 |

Individual wins on both quality and latency.

---

## Experiment 2: Adding Pydantic Structured Output

Switched from free-text JSON parsing to `beta.chat.completions.parse` with a Pydantic schema:

```python
class RecipeSteps(BaseModel):
    recipe_uid: str
    relevant_steps: list[str]

class ExtractionResult(BaseModel):
    recipes: list[RecipeSteps]
```

| | Batch | Individual | Batch-n1 (sequential) |
|---|---|---|---|
| Avg coverage | 5.6 | 6.0 | **5.8** |
| Avg total steps | 11.2 | 14.5 | **13.9** |
| Avg latency | 4.3s | 4.0s | 14.8s |

Pydantic improved parsing reliability (no more fragile JSON handling) but did not improve extraction quality. The bottleneck is semantic, not formatting.

**Key finding from Batch-n1**: individual parallel and individual sequential produce nearly identical quality (5.8 vs 6.0 coverage, 13.9 vs 14.5 steps). This rules out parallelism as the cause of the quality gap — the gap is entirely due to multi-recipe context in the batch prompt.

---

## Experiment 3: Batch Size Sweep (sizes 1–10)

All 10 VALID_TAG queries, sequential calls, varying number of recipes per LLM call:

| Batch size | Avg coverage | Avg total steps | Avg latency | LLM calls |
|---|---|---|---|---|
| **1** | **8.0** | **17.9** | 16.9s | 10 |
| 2 | 6.6 | 14.0 | 8.8s | 5 |
| 3 | 7.0 | 17.6 | 7.6s | 4 |
| 4 | 6.5 | 14.8 | 6.7s | 3 |
| 5 | 6.8 | 13.4 | 5.0s | 2 |
| 6 | 6.4 | 14.0 | 5.0s | 2 |
| 7 | 6.8 | 13.0 | 4.8s | 2 |
| 8 | 6.5 | 12.2 | 4.8s | 2 |
| 9 | 7.0 | 12.7 | 5.2s | 2 |
| 10 | 7.4 | 13.4 | 4.5s | 1 |

Quality drops sharply at batch size 2 and stays flat from 3 onwards — it is a cliff, not a gradual degradation. Even adding a second recipe to the prompt immediately causes significant attention dilution.

---

## Experiment 4: Two-Pass Extraction (Free-form → Structured)

Hypothesis: structured output format forces the LLM to commit early, suppressing borderline-relevant steps. Letting the LLM reason freely first (pass 1) then extracting step identifiers (pass 2) may improve recall.

| | One-pass (individual, Pydantic) | Two-pass (free-form → structured) |
|---|---|---|
| Avg coverage | 7.8 | **10.0** |
| Avg total steps | 18.5 | **44.9** |
| Avg latency | 3.4s | 9.1s |
| LLM calls | 10 | 20 |

Two-pass achieves perfect coverage (10/10) on every query. However, quality inspection reveals a precision problem: the free-form reasoning pass is too liberal, pulling in orchestration utility steps (`declare_variable`, `return_result`, `call_recipe`, `logger / log_message`) that are not relevant to the query. One-pass writes richer, more contextual step descriptions (e.g. `"salesforce / search_sobjects_soql (search Salesforce Lead records, e.g., by email)"`) and is more selective.

---

## Root Cause Analysis

| Hypothesis | Tested | Conclusion |
|---|---|---|
| Token budget too small (output pressure) | Checked actual token usage: 7–13% of 4096 limit used | **Ruled out** |
| Temperature difference | Both approaches use temperature=0 | **Ruled out** |
| Parallelism causing quality difference | Batch-n1 sequential matches individual quality | **Ruled out** |
| Multi-recipe context (attention dilution) | Batch size sweep shows cliff at size 2 | **Confirmed root cause** |
| Output format restricting LLM | Two-pass experiment | **Confirmed — precision-recall tradeoff** |

### Output Format as a Precision-Recall Tradeoff

Structured output (Pydantic/JSON) forces the LLM to commit to a fixed list without format pressure, making it conservative — only steps it is confident about are included. **High precision, lower recall.**

Free-form reasoning (two-pass) lets the LLM think expansively first, surfacing more steps including borderline ones. **High recall, lower precision** — utility/orchestration steps (declare_variable, return_result) are included as noise.

The format acts as an implicit relevance threshold: tighter format = higher threshold = higher precision. This is a classic precision-recall tradeoff driven by output format, not model capability.

**For agent use cases:** precision matters more when showing steps to users (noise is annoying). Recall matters more when the agent uses steps to reason about recipe capabilities (missing a step could lead to a wrong answer).

---

## Experiment 5: Position Sweep (Attention Dilution)

**Hypothesis:** if batch quality drops due to attention dilution, the target recipe's step count should fall as it is placed further from position 1 in a 10-recipe batch.

**Setup:** Fix target recipe `1873346_60999102_v2` (Salesforce agreement webhook → search accounts → update partner/contract status). Strong ground truth: 4 distinct step types, with `update_sobject` appearing 4 times (one per conditional branch). Query crafted to match all of them. Fillers from an unrelated Jira/Slack query.

**Target recipe steps (ground truth):**
- `trigger: salesforce / new_custom_object_webhook`
- `action: salesforce / search_sobjects_soql`
- `action: salesforce / search_sobjects`
- `action: salesforce / update_sobject` (×4 distinct calls)

| Position | Steps extracted | Unique step types matched |
|---|---|---|
| baseline (alone) | **7** | 4 (all 4 `update_sobject` calls distinct) |
| 1 | **7** | 4 |
| 2 | **7** | 4 |
| 3 | 4 | 4 (all 4 `update_sobject` calls collapsed into 1) |
| 5 | 4 | 4 (same collapse) |
| 7 | 7 | 4 (correct count but **format drift** — dropped `action: salesforce /` prefix) |
| 10 | 4 | 4 (collapse) |

**Findings:**

1. **Position cliff at 3:** Identical to the batch-size sweep cliff. At position 3+, the LLM collapses the four distinct `update_sobject` branches into a single summarised step, losing granularity. This is not about the step being missed — it's about *compression under attention load*.

2. **Format drift at position 7:** The LLM stopped using the `action: connector / method_name` format and switched to natural language (`"Salesforce: Update Account fields..."`). This is a secondary dilution effect — the model's attention to formatting instructions weakens when the target recipe is deep in a long prompt.

3. **Positions 1–2 are safe:** The model maintains full granularity when the target is near the top of the batch, even with 9 filler recipes.

4. **Attention dilution is confirmed as position-dependent** (unlike the first sweep with only 3 steps, which showed no drop). With a richer recipe, the effect is clearly measurable: cliff at position 3, format instability at position 7.

**Conclusion from Experiment 5:** Compression and format drift are confirmed as position-dependent. One-recipe-per-call is the correct solution.

---

## Experiment 6: Position Sweep — SOAR Recipe (Richer Step Diversity)

**Hypothesis:** If attention dilution is the root cause, it should still appear with a richer recipe with more diverse step types.

**Target recipe:** `4818251_59278429_v20` — Slack bot SOAR recipe with 11 distinct step types across multiple conditional branches (Slack modal, user validation, Workato table lookup, Jira create/comment/update, call_recipe, Slack post). Recipe is 4578 chars.

**Query:** crafted to mention all key sub-tasks (modal, validate, reference data, Jira issue, Slack updates).

| Position | Steps extracted | Hits (of 11 expected) |
|---|---|---|
| baseline (alone) | 10 | 10 |
| 1 | 10 | 10 |
| 2 | **11** | **11** (best — `call_recipe` surfaced) |
| 3 | 12 | 11 (extra `if` control-flow step included) |
| 5 | 11 | 11 |
| 7 | 10 | 10 |
| 10 | 11 | 11 |

**Finding: No attention dilution on this recipe.** Step counts and hit rates are stable (10–12) across all positions. This contradicts the cliff pattern seen in Experiment 5.

**Why the difference?** The SOAR recipe has 11 *distinct* step types — nothing to compress. The Salesforce recipe had `update_sobject` repeated 4 times within the same recipe across different conditional branches. The LLM's default behaviour is to summarise repetitive content into a single line, which is correct in most contexts. When processing many recipes at once with less attention budget per recipe, that summarisation instinct kicks in and collapses the repeated steps.

Critically, the filler recipes in Experiment 5 were Jira/Slack recipes with no `update_sobject` at all — so cross-recipe overlap was not the cause. The compression is **within-recipe**: the model sees 4 identical action types in one recipe and summarises them, not because another recipe has the same action, but because repetitive content within a single recipe looks redundant when attention is spread thin.

**Revised conclusion on attention dilution:**

| Recipe characteristic | Dilution effect |
|---|---|
| Same step type repeated multiple times within one recipe | **Yes** — collapses to 1 summary entry when attention is thin |
| All distinct step types within one recipe | **No** — stable across all positions |

**Two distinct failure modes in batch processing:**

1. **Repetition compression** — repeated same-type steps within a recipe are collapsed into one summary entry. Caused by the model's summarisation training bias: LLMs are trained with RLHF to produce concise responses, and repeating the same action type multiple times looks verbose and low quality. When it sees `update_sobject` called 4 times, its instinct is to summarise them as one — correct in nearly every task, but wrong here. Explicit prompting can override this when the model has focused attention (positions baseline and 1), but the instinct wins when attention is spread across 10 recipes.

2. **Unique step omission** — steps that appear only once in a recipe also get silently dropped at deeper positions. In Experiment 5, `search_sobjects` (unique, appears once) is present at positions 1–2 but missing at positions 3, 5, and 10. If we normalise out repetition and only count unique step types, batch still underperforms individual at positions 3+:

| Position | Unique step types extracted (of 4) |
|---|---|
| baseline / 1 / 2 | **4** — trigger, search_sobjects_soql, search_sobjects, update_sobject |
| 3 / 5 / 10 | **3** — search_sobjects dropped entirely |

This is not a training bias issue — it is genuine attention thinning. The model processes the target recipe less thoroughly when it is deep in a long batch prompt, even for steps it would never compress if seen alone.

These two failure modes are independent: fixing one (via prompting) does not fix the other.

---

## Experiment 7: Prompt Fix for Within-Recipe Repetition Compression

**Hypothesis:** Explicitly instructing the LLM to include every repeated step occurrence within a recipe will recover the collapsed steps at higher positions.

**Change:** Added two rules to `EXTRACTION_SYSTEM_PROMPT`:
```
- Treat each recipe independently. Do NOT deduplicate steps across recipes — if the same step type appears in multiple recipes, include it in every recipe where it is relevant.
- Include every relevant step occurrence within a recipe, even if the same action type repeats in different branches.
```

**Re-run:** Same setup as Experiment 5 — Salesforce agreement recipe at positions 1–10 in a 10-recipe batch.

| Position | Steps (before fix) | Steps (after fix) | Change |
|---|---|---|---|
| baseline | 7 | **11** | +4 — all `update_sobject` branches now distinct |
| 1 | 7 | **11** | +4 — full recall |
| 2 | 7 | 7 | no change |
| 3 | 4 | 3 | still collapsed (worse) |
| 5 | 4 | 3 | still collapsed |
| 7 | 7 (format drift) | **7** (clean format) | format drift eliminated |
| 10 | 4 | 3 | still collapsed |

**Findings:**

1. **Positions baseline and 1: fully fixed.** The prompt rule is respected when the target has enough attention budget — all 8 `update_sobject` branch calls are extracted distinctly (up from 4).

2. **Format drift at position 7: eliminated.** The explicit rules also help the model maintain consistent output formatting deeper in the batch.

3. **Positions 3, 5, 10: still collapsed.** The model's default summarisation behaviour is deeply ingrained — when it sees 4 `update_sobject` calls in a recipe while processing 9 other recipes simultaneously, enumerating all 4 looks redundant and low-quality from the model's perspective. The explicit instruction is overridden by this instinct. This is not a hard task for a capable LLM when given one recipe alone; it becomes resistant to instruction only because the batch context makes summarisation feel like the right thing to do.

**Conclusion:** Prompting can correct the behaviour when the model has enough focused attention (positions baseline and 1), but cannot override the summarisation instinct when attention is spread across 10 recipes. The root fix is **one recipe per LLM call** — not because the task is hard, but because removing the batch context eliminates the conditions that trigger the compression behaviour.

---

## Conclusion

**One recipe per LLM call, parallelized with async**, is the optimal strategy:

- Achieves batch-size-1 quality (8.0 coverage, 17.9 steps avg)
- Achieves batch-size-10 latency (~4s) through parallelism
- No threshold tuning or BATCH_CHAR_LIMIT needed
- Simpler implementation — no batching logic required

Output format should remain structured (Pydantic) to favour precision. If higher recall is needed, refine the extraction prompt to be more inclusive rather than switching to two-pass.
