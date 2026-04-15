RECIPES_INDEX = "recipes"
EMBEDDING_INDICES: list[tuple[str, int]] = [
    ("embeddings_qwen3_embedding_8b_full", 4096),
]

RECIPES_BODY = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "similarity": {
            "default": {"type": "BM25", "k1": 0.5, "b": 0.75}
        },
        "analysis": {
            "filter": {
                "english_stop": {"type": "stop", "stopwords": "_english_"},
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
            "author_id": {"type": "integer"},
            "flow_id": {"type": "integer"},
            "version_no": {"type": "integer"},
            "step_count": {"type": "integer"},
            "connectors": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "keyword_split"}}},
            "actions": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "keyword_split"}}},
            "input_fields": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "keyword_split"}}},
            "datapill_fields": {"type": "keyword", "fields": {"text": {"type": "text", "analyzer": "keyword_split"}}},
            "text_no_comments": {
                "type": "text",
                "analyzer": "english_underscore",
                "fields": {"simple": {"type": "text", "analyzer": "simple"}},
            },
            "payload": {"type": "object", "enabled": False},
        }
    },
}


def embedding_body(dimension: int) -> dict:
    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            }
        },
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                        "parameters": {"ef_construction": 512, "m": 16},
                    },
                }
            }
        },
    }
