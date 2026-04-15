"""
clients.py
==========

Shared infrastructure for the evaluate_embeddings pipeline:

  - Postgres DSN (from environment variables)
  - Lazy OpenAI API client factory
  - HuggingFace SentenceTransformer cache
  - Low-level Baseten /predict response parsers

All other scripts in this folder import from here rather than
re-defining these objects individually.

API clients are initialised lazily so that scripts which only need the
database connection (e.g. setup_schema.py) can import get_connection()
without requiring BASE_URL / API_KEY to be set.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Postgres connection settings
# ---------------------------------------------------------------------------
DSN = dict(
    host     = os.getenv("PGHOST",     "localhost"),
    port     = int(os.getenv("PGPORT", "5432")),
    dbname   = os.getenv("PGDATABASE", "postgres"),
    user     = os.getenv("PGUSER",     "postgres"),
    password = os.getenv("PGPASSWORD", "postgres"),
)


def get_connection() -> psycopg2.extensions.connection:
    """Return a new psycopg2 connection using DSN."""
    return psycopg2.connect(**DSN)


# ---------------------------------------------------------------------------
# API clients (lazy — instantiated on first call)
# ---------------------------------------------------------------------------
_openai_client: OpenAI | None = None


def get_openai_client() -> OpenAI:
    """Return the shared OpenAI-compatible gateway client, creating it once."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(
            base_url=os.environ["BASE_URL"],
            api_key=os.environ["API_KEY"],
        )
    return _openai_client


# ---------------------------------------------------------------------------
# HuggingFace SentenceTransformer cache
# ---------------------------------------------------------------------------
_hf_models: dict[str, SentenceTransformer] = {}


def get_hf_model(model: str) -> SentenceTransformer:
    """Load a SentenceTransformer model, caching it for the process lifetime."""
    if model not in _hf_models:
        print(f"  Loading {model} from HuggingFace (downloading if not cached) ...")
        _hf_models[model] = SentenceTransformer(model, token=os.getenv("HF_TOKEN"))
    return _hf_models[model]


# ---------------------------------------------------------------------------
# Baseten /predict response parsers
# ---------------------------------------------------------------------------

def parse_predict_embedding(response_json) -> list[float]:
    """Parse a single embedding from a Baseten /predict response."""
    if isinstance(response_json, list):
        return response_json
    if isinstance(response_json, dict):
        if "embedding" in response_json:
            return response_json["embedding"]
        if "data" in response_json:
            return response_json["data"][0]["embedding"]
    raise ValueError(f"Unexpected /predict response format: {type(response_json)}")


def parse_predict_embeddings_batch(response_json) -> list[list[float]]:
    """Parse a list of embeddings from a Baseten /predict batch response."""
    if isinstance(response_json, list) and response_json and isinstance(response_json[0], list):
        return response_json
    if isinstance(response_json, dict) and "data" in response_json:
        return [d["embedding"] for d in sorted(response_json["data"], key=lambda x: x["index"])]
    raise ValueError(f"Unexpected /predict batch response format: {type(response_json)}")


# ---------------------------------------------------------------------------
# Eval dataset helpers
# ---------------------------------------------------------------------------

def parse_uid_list(s) -> list[str]:
    """Parse a comma-separated string of recipe UIDs from an eval dataset column."""
    import pandas as pd
    if pd.isna(s) or str(s).strip() == "":
        return []
    return [uid.strip() for uid in str(s).split(",") if uid.strip()]
