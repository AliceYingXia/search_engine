# OpenSearch text analysis

How each field in the `bt_recipe` index is tokenized and stored. All custom components
are defined in [create_index.py](create_index.py); this doc explains the chains and shows
what tokens come out for representative inputs.

## Field → analysis map

| Field | Type | Analyzer / Normalizer |
|---|---|---|
| `recipe_uid` | keyword | — (exact match) |
| `flow_id`, `version_no`, `author_id`, `step_count` | numeric | — |
| `tag` | text | analyzer `tag_text` |
| `description`, `usage`, `search_text` | text | analyzer `customize_text` |
| `connectors`, `actions`, `fields` | keyword | normalizer `lowercase_normalizer` |
| `description_qwen`, `usage_qwen`, `combined_qwen` | knn_vector | — |

Tokenizer used everywhere: **standard** (Lucene UAX#29 word segmentation).

## Analyzers

### `customize_text` — prose fields (description, usage, search_text)

```
standard tokenizer
  → lowercase
  → english_stop      (Lucene's English stop list)
  → corpus_stop       (Workato-corpus boilerplate)
  → english_stemmer   (Porter)
```

Example: *"Workato recipe that syncs Salesforce accounts when triggered by a webhook"*

| Stage | Tokens |
|---|---|
| standard tokenizer | `[Workato, recipe, that, syncs, Salesforce, accounts, when, triggered, by, a, webhook]` |
| lowercase | `[workato, recipe, that, syncs, salesforce, accounts, when, triggered, by, a, webhook]` |
| english_stop | `[workato, recipe, syncs, salesforce, accounts, when, triggered, webhook]` |
| corpus_stop | `[syncs, salesforce, accounts, webhook]` |
| english_stemmer | `[sync, salesforc, account, webhook]` |

Query strings pass through the same chain at search time, so *"sync salesforce accounts"* matches the doc above — both sides reduce to `[sync, salesforc, account]`.

### `tag_text` — tag field

```
standard tokenizer
  → tag_word_split    (word_delimiter_graph)
  → lowercase
  → english_stop
  → english_stemmer
```

| Input tag | Tokens stored |
|---|---|
| `salesforce` | `[salesforc]` |
| `Salesforces` | `[salesforc]` ← matches `salesforce` via stemming |
| `Google-Drive` | `[googl, drive]` |
| `GoogleDrive` | `[googl, drive]` ← case transition |
| `sale_force` | `[sale, forc]` |
| `office365` | `[office365]` ← `split_on_numerics=False` keeps this whole |
| `o365` | `[o365]` |

`corpus_stop` is intentionally **not** in this chain — its stopword list targets prose
boilerplate, not short tag identifiers.

## Custom filters

| Filter | Type | Purpose |
|---|---|---|
| `english_stop` | built-in `stop` (`_english_`) | Strip standard English stopwords (a, the, of, to, with, ...) |
| `english_stemmer` | built-in `stemmer` (`english`) | Porter-family stemming (`accounts → account`, `syncing → sync`) |
| `corpus_stop` | custom `stop` | Strip workato-corpus boilerplate: `automation, workato, recipe, recipes, function, triggered, operations, when` |
| `tag_word_split` | `word_delimiter_graph` | Split on punctuation / underscores / case transitions; `split_on_numerics=False`, `preserve_original=False`, `catenate_all=False` |

### `tag_word_split` option details

| Option | Value | Effect |
|---|---|---|
| `split_on_numerics` | False | `office365` / `o365` / `s3` survive as single tokens |
| `preserve_original` | False | Emit only split parts (no original concatenated form) |
| `catenate_all` | False | Don't emit a joined version (`google-drive` does **not** also produce `googledrive`) |

The `_graph` suffix means the filter emits a token graph (DAG of positions) instead of a
flat stream, so phrase queries still work correctly across splits — preferred over the
older non-graph `word_delimiter` filter.

## Normalizers

### `lowercase_normalizer` — keyword facets (connectors, actions, fields)

Just lowercases each multi-valued keyword. No tokenization — `term`/`terms` queries
against these fields are exact-match, but case-insensitive after this normalizer.

## Design notes

- **Prose vs identifier split.** Prose fields get the heaviest chain (stop + corpus-stop + stem) for recall under noisy queries. Tag gets word-delimiter splitting for naming-convention tolerance plus stemming for singular/plural matching, but no corpus-stop.
- **Keyword fields use a normalizer, not an analyzer.** `connectors`/`actions`/`fields` are exact-match facets consumed by `term`/`terms` filters in [`../05_search/search_recipes.py`](../05_search/search_recipes.py). Tokenization or stemming there would break exact-match semantics.
- **Server-side stopword removal mirrors LLM instructions.** The agent's system prompt in [`../05_search/agent.py`](../05_search/agent.py) lists the same corpus stopwords as `corpus_stop`, and tells the LLM it does **not** need to strip them from `query` since the analyzer does it server-side. For `dense_query`, the LLM still strips them manually — embeddings don't pre-filter.
- **`split_on_numerics=False` for tags.** Connector tags often embed digits intentionally (`s3`, `o365`, `oauth2`). Default `word_delimiter_graph` would mangle these into separate letter/digit tokens.
- **Stemmer aggressiveness.** `english_stemmer` is Porter-family — `operations → oper` collides with `operating`/`operator`. Acceptable for recipe retrieval; switch to `light_english` if those distinctions ever matter.
