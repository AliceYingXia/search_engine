# Embedding Strategy

Reference for the embedding step that converts chunk text into vectors for Qdrant.

Script: `embed_chunks.py`
Input: `example/chunks/<name>_chunks.json`
Output: `example/embedded/<name>_embedded.json`

---

## Three-Model Plan

Three models are used together to support both semantic and hybrid search:

| Model | Provider | Type | Dims | Role |
|---|---|---|---|---|
| `voyage-code-3` | Voyage AI (API) | Dense | 1024 | Best for structured/code-like recipe content |
| `text-embedding-3-large` | OpenAI (API) | Dense | 3072 | Best for natural-language user queries |
| `BGE-M3` | BAAI (local) | Dense + Sparse | 1024 + sparse | Enables hybrid search |

### When to use which dense model

| Scenario | Recommended model |
|---|---|
| Recipe content is structured (connector names, operation names, field paths) | `voyage-code-3` |
| User queries are natural language ("find recipes that create Salesforce opportunities") | `text-embedding-3-large` |

BGE-M3 is always used — it provides the sparse vector for keyword matching regardless of which dense model is chosen.

---

## What BGE-M3 Produces

BGE-M3 is unique in that a **single call** returns both a dense and a sparse vector:

```python
output = model.encode(text, return_dense=True, return_sparse=True)
output["dense_vecs"]       # → 1024-dim dense vector
output["lexical_weights"]  # → sparse vector (token weights, learned)
```

The sparse vector enables **hybrid search** — keyword-level matching on top of semantic matching. Fusion of dense and sparse results is handled by Qdrant using RRF (Reciprocal Rank Fusion).

BGE-M3 runs **locally** — no API key required, no per-call cost.

---

## BGE-M3 Sparse vs BM25

BGE-M3's sparse vector looks structurally similar to BM25 — both assign a scalar weight to each token and ignore the rest. But the weights come from fundamentally different sources.

### How BM25 computes weights

BM25 is a statistical formula with no model and no training:

```
weight(token, doc) = TF(token in doc) × IDF(token across all docs)

IDF = log(total docs / docs containing token)
```

- Rare tokens (low document frequency) get high IDF → high weight
- Common tokens like "the", "is" get low IDF → suppressed naturally
- Each token is scored **independently** — the surrounding words have no effect
- Weights **change** if you add more documents to the corpus (IDF shifts)

### How BGE-M3 sparse computes weights

BGE-M3 passes the full text through a transformer, then assigns a weight to each token present in the text. The weights are fixed outputs of the model — learned during training, not computed from your corpus:

```
"subscribe to pub sub topic"
                  ↓ transformer reads full sentence
→ { "subscribe": 0.82, "pub": 0.71, "sub": 0.68, "topic": 0.55, "to": 0.01 }
```

The model suppresses "to" near zero because it learned that prepositions carry no retrieval signal. The weight of "pub" is elevated because the model understands — from context — that this is a pub/sub messaging pattern, not the standalone word "pub".

### Direct comparison

| Property | BM25 | BGE-M3 sparse |
|---|---|---|
| Weight source | Corpus statistics (TF × IDF) | Learned by transformer during training |
| Context-aware | No — each token scored independently | Yes — full sentence read before scoring |
| Corpus required at query time | Yes — IDF needs the full document index | No — model runs standalone |
| Vocabulary expansion | No | No — only tokens present in the text are weighted |
| Stop word handling | Suppressed by low IDF | Suppressed by near-zero learned weights |
| Semantic gap bridging | No | No — token-level only (dense vector's job) |
| Reliable on small corpora | No — IDF is noisy with few documents | Yes — weights are corpus-independent |

### The key practical difference for this project

BM25 IDF is unreliable on small corpora. A connector name like `workato_pub_sub` appearing in 2 out of 11 chunks gets the same IDF signal as a universally rare term in a million-document corpus — the statistic is meaningless at this scale.

BGE-M3 sparse has no such problem. Its weights are fixed by what the model learned during pre-training on a large dataset. `workato_pub_sub` gets a high weight because the model learned that connector names and action names are retrieval-critical tokens — regardless of how many documents are in your collection.

**Summary:** BGE-M3 sparse is best understood as *context-aware, learned token weights*. It overlaps with BM25 in that both work at the token level and neither bridges a semantic gap, but BGE-M3's weights are more reliable on small corpora and understand token importance from sentence context rather than counting.

---

## Hybrid Search Flow

```
query → voyage-code-3 or text-embedding-3-large  →  dense results   ─┐
      → BGE-M3 sparse                             →  keyword results ─┴→ RRF → final ranking
```

---

## Qdrant Collection Structure

Each Qdrant point stores **three named vectors** plus one sparse vector:

```
Point
├── vectors
│   ├── dense_voyage    (1024 dims, cosine)   ← voyage-code-3
│   ├── dense_openai    (3072 dims, cosine)   ← text-embedding-3-large
│   └── dense_bge       (1024 dims, cosine)   ← BGE-M3 dense
├── sparse_vectors
│   └── sparse_bge      (variable)            ← BGE-M3 sparse
└── payload
    └── { chunk_type, chunk_id, source_file, recipe_name, provider, ... }
```

All vectors are stored together so any combination can be queried at search time without re-embedding.

---

## Testing Plan

Each model is tested individually before combining:

| Phase | Model | What to verify |
|---|---|---|
| 1 | `voyage-code-3` | Dense vectors generated, correct dims (1024), Qdrant ingestion works |
| 2 | `text-embedding-3-large` | Dense vectors generated, correct dims (3072), Qdrant ingestion works |
| 3 | `BGE-M3` | Both dense (1024) and sparse vectors generated, hybrid search works in Qdrant |
| 4 | All three | Combined ingestion, query routing between models, RRF fusion results |

---

## Environment Variables

Required in `.env`:

```
VOYAGE_API_KEY=        # Voyage AI — for voyage-code-3
OPENAI_API_KEY=        # OpenAI — for text-embedding-3-large
QDRANT_URL=            # Qdrant instance URL
QDRANT_API_KEY=        # Qdrant API key (if using Qdrant Cloud)
```

BGE-M3 runs locally — no API key needed.

---

## Dependencies

```
voyageai           # Voyage AI SDK
openai             # OpenAI SDK
FlagEmbedding      # BGE-M3 (local)
qdrant-client      # Qdrant ingestion and search
python-dotenv      # Load .env variables
```

---

## Model Selection: Cost, Quality, and Trade-offs

Benchmark results (13 queries, MRR) and cost comparison for choosing a production model.

### Quality vs cost

| Model | MRR (13 queries) | Ingestion price | Query price | Latency | Dependency |
|---|---|---|---|---|---|
| `text-embedding-3-large` | **1.000** | $0.13 / 1M tokens | $0.13 / 1M tokens | ~200 ms (API) | OpenAI key |
| `text-embedding-3-small` | untested | $0.02 / 1M tokens | $0.02 / 1M tokens | ~200 ms (API) | OpenAI key |
| `voyage-code-3` | 0.859 | $0.06 / 1M tokens | $0.06 / 1M tokens | ~200 ms (API) | Voyage key |
| `BGE-M3` dense | 0.859 | free (local) | free (local) | ~1–2 s (CPU) | none |

### Ingestion cost (one-time)

Ingestion is negligible at any realistic scale — chunks are embedded once and only need re-embedding when content changes.

| Collection size | Avg tokens/chunk | Total tokens | `text-embedding-3-large` cost |
|---|---|---|---|
| 2 recipes, 11 chunks (current) | ~120 | ~1,300 | $0.0002 |
| 100 recipes, ~600 chunks | ~120 | ~72,000 | $0.009 |
| 1,000 recipes, ~6,000 chunks | ~120 | ~720,000 | $0.094 |
| 10,000 recipes, ~60,000 chunks | ~120 | ~7.2M | $0.94 |

### Query cost (ongoing)

A typical search query is ~15 tokens.

| Daily queries | Monthly tokens | `text-embedding-3-large` | `voyage-code-3` |
|---|---|---|---|
| 100 | ~45,000 | $0.006 | $0.003 |
| 1,000 | ~450,000 | $0.06 | $0.03 |
| 10,000 | ~4.5M | $0.59 | $0.27 |
| 100,000 | ~45M | $5.85 | $2.70 |

At typical internal tool usage (hundreds to a few thousand queries per day), the monthly cost is under $1 for either API model. Cost only becomes meaningful at very high volume (100,000+ queries/day).

### Recommendation

**Use `text-embedding-3-large` for production.** It achieves MRR=1.000 on the benchmark — the clearest quality gap over the alternatives — and the cost is negligible at expected usage volumes.

If cost becomes a constraint at high volume:

1. **Test `text-embedding-3-small` first** ($0.02/1M, 6.5× cheaper, same architecture). It may retain most of the quality advantage.
2. **Fall back to `voyage-code-3`** if OpenAI API dependency is a hard constraint (e.g. offline/airgap requirement).
3. **Fall back to `BGE-M3` dense** only if no API connectivity is available. It matches voyage-code-3 on MRR but runs locally with ~1–2 s latency on CPU.

### Why hybrid search is not recommended yet

The benchmark shows no query where sparse retrieval succeeds but dense retrieval fails. Sparse (BGE-M3) introduces additional failures (Q3, Q12) that dense handles correctly. The failing queries (Q1, Q7) require natural-language generalisation that sparse cannot provide. Hybrid search adds complexity — two embeds per query, RRF fusion, BGE-M3 running at query time even when using an API model — without measurable benefit on the current benchmark.

Revisit hybrid when:
- The collection grows and exact technical identifier lookups become common (e.g. connector names, field names, `as` alias values used as queries)
- A benchmark query is found where sparse succeeds and dense fails

---

## Notes

- BGE-M3 runs on CPU if no GPU is available — slower but functional
- All three models are embedded at ingest time and stored together so search can switch models without re-embedding
- `voyage-code-3` and `text-embedding-3-large` are API-based — batch requests to minimise cost and latency
