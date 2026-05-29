"""
create_index.py

Create (or recreate) the bt_recipe index in OpenSearch.

Usage:
    python create_index.py [--recreate]

Env vars (or .env at project root):
    OPENSEARCH_URL   default http://localhost:9200
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from opensearchpy import OpenSearch

load_dotenv(Path(__file__).parent.parent.parent / ".env")

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
INDEX_NAME     = "bt_recipe"
DIMS           = 4096

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "knn.algo_param.ef_search": 100,
        },
        "similarity": {
            "default": {"type": "BM25", "k1": 0.5, "b": 0.75}
        },
        "analysis": {
            "filter": {
                "english_stop":    {"type": "stop", "stopwords": "_english_"},
                "english_stemmer": {"type": "stemmer", "language": "english"},
                "underscore_split": {
                    "type": "word_delimiter_graph",
                    "split_on_numerics": False,
                    "preserve_original": True,
                    "catenate_all": False,
                },
                "keyword_split": {
                    "type": "word_delimiter_graph",
                    "split_on_numerics": False,
                    "preserve_original": False,
                    "catenate_all": False,
                },
            },
            "analyzer": {
                "english_underscore": {
                    "tokenizer": "standard",
                    "filter": [
                        "underscore_split",
                        "lowercase",
                        "english_stop",
                        "english_stemmer",
                    ],
                },
                "keyword_split": {
                    "tokenizer": "standard",
                    "filter": ["keyword_split", "lowercase"],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "recipe_uid":  {"type": "keyword"},
            "flow_id":     {"type": "long"},
            "version_no":  {"type": "integer"},
            "author_id":   {"type": "long"},
            "step_count":  {"type": "integer"},
            "tag":         {"type": "text", "analyzer": "keyword_split"},

            # text fields with english analyzer
            "description": {"type": "text", "analyzer": "english_underscore"},
            "usage":       {"type": "text", "analyzer": "english_underscore"},
            "search_text": {"type": "text", "analyzer": "english_underscore"},

            # keyword + boosted text fields
            "connectors": {
                "type": "text",
                "analyzer": "keyword_split",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "actions": {
                "type": "text",
                "analyzer": "keyword_split",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "input_fields": {
                "type": "text",
                "analyzer": "keyword_split",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "datapill_fields": {
                "type": "text",
                "analyzer": "keyword_split",
            },

            # knn vectors
            "description_qwen": {
                "type": "knn_vector",
                "dimension": DIMS,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "faiss",
                    "parameters": {"ef_construction": 256, "m": 16},
                },
            },
            "usage_qwen": {
                "type": "knn_vector",
                "dimension": DIMS,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "faiss",
                    "parameters": {"ef_construction": 256, "m": 16},
                },
            },
            "combined_qwen": {
                "type": "knn_vector",
                "dimension": DIMS,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "faiss",
                    "parameters": {"ef_construction": 256, "m": 16},
                },
            },
        }
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true",
                        help="Delete and recreate the index if it already exists")
    args = parser.parse_args()

    client = OpenSearch(OPENSEARCH_URL)

    if client.indices.exists(index=INDEX_NAME):
        if args.recreate:
            client.indices.delete(index=INDEX_NAME)
            print(f"Deleted existing index: {INDEX_NAME}")
        else:
            print(f"Index '{INDEX_NAME}' already exists. Use --recreate to drop and rebuild.")
            sys.exit(0)

    client.indices.create(index=INDEX_NAME, body=INDEX_BODY)
    print(f"Created index '{INDEX_NAME}' (dim={DIMS}, faiss hnsw, cosinesimil).")


if __name__ == "__main__":
    main()
