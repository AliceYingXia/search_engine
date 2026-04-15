# Embedding Production Benchmarks

This folder is a clean workspace for testing whether `Qwen3-Embedding-8B`
retains retrieval quality after truncation, using open retrieval benchmarks.

## Goal

Answer this question with larger public datasets:

- Does `Qwen3-Embedding-8B` at `2000` dimensions remain competitive with
  `4096` and `4000` dimensions?

We keep the methodology close to the existing repo:

- same `Qwen3-Embedding-8B` Baseten endpoint
- same retrieval instruction prefix
- same truncation + L2 renormalization rule
- exact cosine retrieval first
- optional ANN backends later

## Design

The code here is intentionally lightweight:

- small dataclasses for config
- mostly functional pipeline
- no deep inheritance or framework structure

Files:

- `config.py` — experiment settings and default paths
- `prepare_trec_covid.py` — download and build a qrels-covered TREC-COVID subset
- `qwen_client.py` — Baseten embedding client, truncation, normalization
- `datasets.py` — loaders for local BEIR-style datasets
- `search.py` — exact cosine retrieval
- `evaluate.py` — Recall, MRR, NDCG metrics
- `run_beir.py` — CLI entrypoint for one benchmark run

## Expected Dataset Layout

`run_beir.py` expects a local BEIR-style dataset directory:

```text
<dataset_dir>/
  corpus.jsonl
  queries.jsonl
  qrels/
    test.tsv
```

The JSONL schema matches BEIR conventions:

- `corpus.jsonl`: `_id`, `title`, `text`
- `queries.jsonl`: `_id`, `text`
- `qrels/test.tsv`: `query-id`, `corpus-id`, `score`

## Example Commands

Prepare a deterministic TREC-COVID subset with all 50 queries and 20K docs:

```bash
python experiments/embedding_production/prepare_trec_covid.py \
  --output-dir experiments/embedding_production/data/trec-covid-20k \
  --target-docs 20000
```

Run exact retrieval on a local dataset with 4096 dimensions:

```bash
python experiments/embedding_production/run_beir.py \
  --dataset-dir experiments/embedding_production/data/trec-covid-20k \
  --dims 4096
```

Run the 2000-dimension variant:

```bash
python experiments/embedding_production/run_beir.py \
  --dataset-dir experiments/embedding_production/data/trec-covid-20k \
  --dims 2000
```

Use the retrieval instruction explicitly:

```bash
python experiments/embedding_production/run_beir.py \
  --dataset-dir experiments/embedding_production/data/trec-covid-20k \
  --dims 2000 \
  --use-instruction
```

## Notes

- The client uses the same `BASETEN_API_KEY` and Qwen3-8B predict endpoint as
  the existing pipeline.
- Truncation is prefix truncation: keep the first `N` dimensions, then
  L2-renormalize.
- This scaffold focuses on exact retrieval first. ANN and multi-dataset batch
  orchestration can be added once the first public benchmark run is working.
- `prepare_trec_covid.py` uses Hugging Face datasets and requires:
  `python -m pip install datasets pyarrow`
