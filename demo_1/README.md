# Demo 1

`demo_1` is organized as a simple production-style pipeline:

1. `01_process_json`
   Convert raw recipe JSON files into normalized records.
2. `02_ingest_opensearch`
   Create indices, index normalized recipes, and build embeddings.
3. `03_query`
   Retrieve results for live queries with FTS, dense search, and hybrid RRF.

Shared code lives in `common/` so each stage stays small and focused.

Supporting docs:
- [METHODOLOGY.md](/Users/alice/project/semantic_search/search_engine/demo_1/METHODOLOGY.md)

Setup files:
- [.env.example](/Users/alice/project/semantic_search/search_engine/demo_1/.env.example)
- [requirements.txt](/Users/alice/project/semantic_search/search_engine/demo_1/requirements.txt)

## Folder layout

```text
demo_1/
  common/
  01_process_json/
  02_ingest_opensearch/
  03_query/
```

## End-to-end flow

### 1. Process raw JSON files

Input:
- a directory of raw recipe JSON files

Output:
- `01_process_json/processed/recipes.parquet`

```bash
python demo_1/01_process_json/process_recipe_json_files.py --input-dir /path/to/recipe_jsons
```

### 2. Create indices

```bash
python demo_1/02_ingest_opensearch/create_indices.py
```

Use `--recreate` if you want to rebuild from scratch.

### 3. Index processed recipes

```bash
python demo_1/02_ingest_opensearch/index_processed_recipes.py
```

You can also point it to a different parquet file with `--input`.

### 4. Build embeddings

```bash
python demo_1/02_ingest_opensearch/build_embeddings.py
```

Use `--missing-only` to embed only recipes that are not yet in the embedding index.

### 5. Query the system

```bash
python demo_1/03_query/search_recipes.py --query "salesforce opportunity status impact" --top-k 5
```

This always runs query-signal weighted RRF across FTS and dense search.

For demo safety, you can allow a fallback to FTS-only if dense embedding fails.
If the query would not normally run FTS, the script will do a last-resort FTS
search instead of exiting:

```bash
python demo_1/03_query/search_recipes.py --query "salesforce opportunity status impact" --allow-fts-fallback
```
