"""
create_opensearch_indices.py
==============

Creates the recipes index and the single embeddings index in OpenSearch.
Mirrors pipeline/03_evaluate_postgre/setup_schema.py.

Usage
-----
    # Create all indices (skips any that already exist)
    python pipeline/04_evaluate_opensearch/create_opensearch_indices.py

    # Drop and recreate everything from scratch
    python pipeline/04_evaluate_opensearch/create_opensearch_indices.py --recreate

To drop individual indices manually:
    DELETE /recipes
    DELETE /embeddings_qwen3_embedding_8b_full
"""

import argparse

from clients import get_client

# ---------------------------------------------------------------------------
# Index definitions — mirrors setup_schema.py table structure
# ---------------------------------------------------------------------------

RECIPES_INDEX = "recipes"

# Single embedding index — full 4096-dim Qwen3-Embedding-8B vectors, no truncation.
EMBEDDING_INDICES: list[tuple[str, int]] = [
    ("embeddings_qwen3_embedding_8b_full", 4096),
]

RECIPES_BODY = {
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
        "similarity": {
            "default": {
                "type": "BM25",
                "k1":   0.5,
                "b":    0.75,
            }
        },
        # Custom analyzer that mirrors PostgreSQL's english tsvector behaviour:
        # Postgres splits underscore-compound identifiers (e.g. workato_recipe_function)
        # into sub-lexemes (workato + recipe/recip + function) so that natural-language
        # queries like "recipe function" match recipes containing the identifier.
        # OpenSearch's built-in 'english' analyzer treats the whole compound as one token,
        # which breaks Category-2 queries. word_delimiter_graph splits on underscores
        # before stemming, replicating Postgres's behaviour.
        "analysis": {
            "filter": {
                "english_stop": {
                    "type":      "stop",
                    "stopwords": "_english_",
                },
                "english_stemmer": {
                    "type":     "stemmer",
                    "language": "english",
                },
                # Preserves original compound token AND sub-tokens for FTS field.
                "underscore_split": {
                    "type":               "word_delimiter_graph",
                    "split_on_numerics":  False,
                    "preserve_original":  True,
                    "catenate_all":       False,
                },
                # Sub-tokens only (no original) for keyword fields —
                # splits workato_recipe_function → workato, recipe, function
                # and salesforce/search_records → salesforce, search, records
                # No stemming so technical names stay intact.
                "keyword_split": {
                    "type":               "word_delimiter_graph",
                    "split_on_numerics":  False,
                    "preserve_original":  False,
                    "catenate_all":       False,
                },
            },
            "analyzer": {
                # For text_no_comments: mirrors Postgres english tsvector with
                # underscore sub-lexeme splitting + stemming.
                "english_underscore": {
                    "tokenizer": "standard",
                    "filter": [
                        "underscore_split",
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                    ],
                },
                # For connectors / actions / input_fields / datapill_fields:
                # splits on underscores and slashes, lowercases, no stemming.
                # workato_recipe_function → [workato, recipe, function]
                # salesforce/search_records → [salesforce, search, records]
                "keyword_split": {
                    "tokenizer": "standard",
                    "filter": [
                        "keyword_split",
                        "lowercase",
                    ],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "author_id":  {"type": "integer"},
            "flow_id":    {"type": "integer"},
            "version_no": {"type": "integer"},
            "step_count": {"type": "integer"},
            # keyword fields: exact terms query on .keyword, fuzzy match on .text
            "connectors": {
                "type": "keyword",
                "fields": {
                    "text": {"type": "text", "analyzer": "keyword_split"},
                },
            },
            "actions": {
                "type": "keyword",
                "fields": {
                    "text": {"type": "text", "analyzer": "keyword_split"},
                },
            },
            "input_fields": {
                "type": "keyword",
                "fields": {
                    "text": {"type": "text", "analyzer": "keyword_split"},
                },
            },
            "datapill_fields": {
                "type": "keyword",
                "fields": {
                    "text": {"type": "text", "analyzer": "keyword_split"},
                },
            },
            # text_no_comments: custom english_underscore analyzer splits compound
            # identifiers (e.g. workato_recipe_function → workato + recip + function)
            # before stemming, matching Postgres tsvector sub-lexeme behaviour.
            # The .simple sub-field mirrors Postgres's simple config (lowercase only).
            "text_no_comments": {
                "type":     "text",
                "analyzer": "english_underscore",
                "fields": {
                    "simple": {"type": "text", "analyzer": "simple"},
                },
            },
            # payload stored but not indexed (mirrors JSONB column)
            "payload": {"type": "object", "enabled": False},
        },
    },
}


def _embedding_body(dimension: int) -> dict:
    """Index body for a kNN embedding index with cosine similarity and HNSW."""
    return {
        "settings": {
            "index": {
                "knn":                True,
                "number_of_shards":   1,
                "number_of_replicas": 0,
            },
        },
        "mappings": {
            "properties": {
                "embedding": {
                    "type":      "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name":       "hnsw",
                        "space_type": "cosinesimil",
                        "engine":     "lucene",
                        "parameters": {
                            "ef_construction": 512,
                            "m":               16,
                        },
                    },
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Setup logic
# ---------------------------------------------------------------------------

class IndexManager:
    def __init__(self, client, recreate: bool = False):
        self.client   = client
        self.recreate = recreate

    def _create(self, name: str, body: dict) -> None:
        exists = self.client.indices.exists(index=name)
        if exists:
            if self.recreate:
                self.client.indices.delete(index=name)
                print(f"  dropped  : {name}")
            else:
                print(f"  exists   : {name}  (skipping — use --recreate to drop and rebuild)")
                return
        self.client.indices.create(index=name, body=body)
        print(f"  created  : {name}")

    def setup(self) -> None:
        print("Creating recipes index ...")
        self._create(RECIPES_INDEX, RECIPES_BODY)

        print("\nCreating embedding indices ...")
        for name, dim in EMBEDDING_INDICES:
            self._create(name, _embedding_body(dim))

        print("\nDone.")
        print("Next: python pipeline/04_evaluate_opensearch/index_recipe_corpus.py")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate all indices (deletes all indexed data).",
    )
    args = parser.parse_args()

    manager = IndexManager(get_client(), recreate=args.recreate)
    manager.setup()


if __name__ == "__main__":
    main()
