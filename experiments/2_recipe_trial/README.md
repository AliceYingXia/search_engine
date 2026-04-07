# Workato Recipe Semantic Search (RAG)

Semantic search pipeline for Workato recipe JSON exports, backed by Qdrant.

## Pipeline

| Step | Script | Status |
|---|---|---|
| 1. Clean | `clean_recipes.py` | ✅ Done |
| 2. Chunk | `chunk_recipes.py` | ✅ Done |
| 3. Embed | `embed_chunks.py` | ✅ Done |
| 4. Ingest to Qdrant | `ingest_qdrant.py` | ✅ Done |
| 5. Query + Evaluate | `search_qdrant.py` | ✅ Done |

## Step 1 — Clean

```bash
python3 clean_recipes.py
```

Reads `example/*.json`, writes two files per recipe into `example/cleaned/`:

- `*_semantic.json` — content for embedding (pills resolved, stale fields removed)
- `*_tracking.json` — metadata for Qdrant payload (`as`, `uuid`, `parent_as`, `depth`, `config`)

See [docs/cleaning-process.md](docs/cleaning-process.md) for details.

## Step 2 — Chunk

```bash
python3 chunk_recipes.py
```

Reads `example/cleaned/` pairs, writes one chunks file per recipe into `example/chunks/`:

- **Type 1 — recipe chunk** (1 per recipe): `recipe_summary` as embed text + recipe-level payload
- **Type 2 — step chunk** (1 per step): ancestor context + step content as embed text + step-level payload

See [docs/chunking-strategy.md](docs/chunking-strategy.md) for details.

## Docs

| File | Contents |
|---|---|
| [docs/recipe-schema.md](docs/recipe-schema.md) | Workato recipe JSON schema reference |
| [docs/cleaning-process.md](docs/cleaning-process.md) | Cleaning logic, field decisions, pill resolution |
| [docs/chunking-strategy.md](docs/chunking-strategy.md) | Chunk types, embed text format, ancestor context, payload fields |
| [docs/embedding-strategy.md](docs/embedding-strategy.md) | Three-model plan, hybrid search, Qdrant collection structure |
| [docs/retrieval-evaluation.md](docs/retrieval-evaluation.md) | Retrieval architecture, golden dataset, benchmark results and analysis |

## Claude Skills

| Skill | Description |
|---|---|
| `/validate-recipe` | Validate all `example/*.json` files against the schema |
