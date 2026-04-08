"""
models.py
=========

Unified embedding model registry and backend classes.

All scripts that need to embed text import EmbeddingModel and MODEL_REGISTRY
from here. This eliminates the duplicate MODEL_CONFIG dictionaries that
previously lived in add_embeddings.py and evaluate_pgvector.py.

Backends
--------
    OpenAIBackend              — OpenAI-compatible gateway (text-embedding-3-*)
    HuggingFaceBackend         — local sentence-transformers
    BasetenPredictBackend      — Baseten single-item /predict endpoint
    BasetenPredictBatchBackend — Baseten batch /predict endpoint

Usage
-----
    from models import EmbeddingModel, MODEL_REGISTRY

    model = EmbeddingModel("Qwen/Qwen3-Embedding-8B+instruct")
    vectors = model.embed_texts(["recipe text …"])   # ingestion
    query_vec = model.embed_query("search query")    # evaluation (uses instruction)
"""

from __future__ import annotations

import math
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests as _requests

from clients import (
    get_hf_model,
    get_openai_client,
    parse_predict_embedding,
    parse_predict_embeddings_batch,
)


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    """All parameters that describe one embedding model variant."""
    table: str
    backend: str
    dimension: Optional[int] = None         # required for ingestion; None for eval-only variants
    predict_url: Optional[str] = None       # Baseten /predict endpoint URL
    model_name: Optional[str] = None        # API model name override (OpenAI backend)
    hf_model: Optional[str] = None          # HuggingFace model ID override
    source_column: str = "text_no_comments"  # recipes column to read for ingestion
    instruction: Optional[str] = None       # query-side instruction prefix (eval only)
    store_dim: Optional[int] = None         # truncate output to this many dims before storage/query
    pg_type: str = "vector"                 # PostgreSQL column type: "vector" or "halfvec"


# Single source of truth — replaces the two separate MODEL_CONFIG dicts.
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "text-embedding-3-small": ModelConfig(
        table="embeddings_text_embedding_3_small",
        dimension=1536,
        backend="openai",
    ),
    "text-embedding-3-large": ModelConfig(
        table="embeddings_text_embedding_3_large",
        dimension=3072,
        backend="openai",
    ),
    "BAAI/bge-m3": ModelConfig(
        table="embeddings_bge_m3",
        dimension=1024,
        backend="huggingface",
    ),
    "Qwen/Qwen3-Embedding-0.6B": ModelConfig(
        table="embeddings_qwen3_embedding_0_6b",
        dimension=1024,
        backend="huggingface",
    ),
    "Qwen/Qwen3-Embedding-0.6B+instruct": ModelConfig(
        table="embeddings_qwen3_embedding_0_6b",    # same doc vectors as base
        backend="huggingface",
        hf_model="Qwen/Qwen3-Embedding-0.6B",
        instruction=(
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    ),
    "intfloat/multilingual-e5-large-instruct": ModelConfig(
        table="embeddings_multilingual_e5_large_instruct",
        dimension=1024,
        backend="huggingface",
        instruction=(
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    ),
    "Qwen/Qwen3-Embedding-4B": ModelConfig(
        table="embeddings_qwen3_embedding_4b",
        dimension=2560,
        backend="baseten_predict_batch",
        predict_url="https://model-3yd060v3.api.baseten.co/environments/production/predict",
    ),
    "Qwen/Qwen3-Embedding-4B+instruct": ModelConfig(
        table="embeddings_qwen3_embedding_4b",      # same doc vectors as base
        backend="baseten_predict_batch",
        predict_url="https://model-3yd060v3.api.baseten.co/environments/production/predict",
        instruction=(
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    ),
    "mixedbread-ai/mxbai-embed-large-v1": ModelConfig(
        table="embeddings_mxbai_embed_large_v1",
        dimension=1024,
        backend="baseten_predict",
        predict_url="https://model-qvvpmnjq.api.baseten.co/environments/production/predict",
    ),
    "Qwen/Qwen3-Embedding-8B": ModelConfig(
        table="embeddings_qwen3_embedding_8b",
        dimension=4096,
        backend="baseten_predict_batch",
        predict_url="https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        store_dim=4000,
        pg_type="halfvec",
    ),
    "Qwen/Qwen3-Embedding-8B+instruct": ModelConfig(
        table="embeddings_qwen3_embedding_8b",      # same doc vectors as base
        backend="baseten_predict_batch",
        predict_url="https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        instruction=(
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
        store_dim=4000,
        pg_type="halfvec",
    ),
}


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------

class EmbeddingBackend(ABC):
    """Abstract base for all embedding backends."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts (document side — no instruction)."""

    def embed_query(self, text: str, instruction: str | None = None) -> list[float]:
        """Embed a single query, optionally prepending an instruction."""
        prepared = (instruction + text) if instruction else text
        return self.embed_texts([prepared])[0]


class OpenAIBackend(EmbeddingBackend):
    def __init__(self, model_name: str):
        self.model_name = model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        resp = get_openai_client().embeddings.create(model=self.model_name, input=texts)
        return [d.embedding for d in sorted(resp.data, key=lambda x: x.index)]


class HuggingFaceBackend(EmbeddingBackend):
    def __init__(self, model_name: str):
        self.model_name = model_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = get_hf_model(self.model_name)
        return model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, text: str, instruction: str | None = None) -> list[float]:
        """Use sentence-transformers' native `prompt` kwarg for instructions."""
        model = get_hf_model(self.model_name)
        kwargs: dict = {"normalize_embeddings": True}
        if instruction:
            kwargs["prompt"] = instruction
        return model.encode([text], **kwargs)[0].tolist()


class BasetenPredictBackend(EmbeddingBackend):
    """Single-item Baseten /predict endpoint."""

    def __init__(self, predict_url: str):
        self.predict_url = predict_url

    def _auth_header(self) -> dict:
        return {"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            r = _requests.post(
                self.predict_url,
                headers=self._auth_header(),
                json={"input": text, "model": "model", "encoding_format": "float"},
            )
            r.raise_for_status()
            results.append(parse_predict_embedding(r.json()))
        return results


class BasetenPredictBatchBackend(EmbeddingBackend):
    """Batch Baseten /predict endpoint."""

    def __init__(self, predict_url: str):
        self.predict_url = predict_url

    def _auth_header(self) -> dict:
        return {"Authorization": f"Api-Key {os.environ['BASETEN_API_KEY']}"}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        r = _requests.post(
            self.predict_url,
            headers=self._auth_header(),
            json={"input": texts, "model": "model", "encoding_format": "float"},
        )
        r.raise_for_status()
        return parse_predict_embeddings_batch(r.json())


# ---------------------------------------------------------------------------
# EmbeddingModel — config + backend in one object
# ---------------------------------------------------------------------------

def _truncate_normalize(vec: list[float], dim: int) -> list[float]:
    """Truncate a vector to `dim` dimensions and L2-renormalize."""
    v = vec[:dim]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm > 0 else v


def _make_backend(name: str, cfg: ModelConfig) -> EmbeddingBackend:
    if cfg.backend == "openai":
        return OpenAIBackend(cfg.model_name or name)
    if cfg.backend == "huggingface":
        return HuggingFaceBackend(cfg.hf_model or name)
    if cfg.backend == "baseten_predict":
        return BasetenPredictBackend(cfg.predict_url)
    if cfg.backend == "baseten_predict_batch":
        return BasetenPredictBatchBackend(cfg.predict_url)
    raise ValueError(f"Unknown backend: {cfg.backend!r}")


class EmbeddingModel:
    """
    Combines a ModelConfig with a live backend.

    Attributes
    ----------
    name          : registry key (e.g. "Qwen/Qwen3-Embedding-8B+instruct")
    config        : ModelConfig
    table         : target embedding table
    source_column : recipes column used for ingestion
    """

    def __init__(self, name: str):
        if name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model: {name!r}. Available: {list(MODEL_REGISTRY)}"
            )
        self.name = name
        self.config = MODEL_REGISTRY[name]
        self._backend = _make_backend(name, self.config)

    @property
    def table(self) -> str:
        return self.config.table

    @property
    def source_column(self) -> str:
        return self.config.source_column

    @property
    def pg_type(self) -> str:
        return self.config.pg_type

    def _prepare(self, vecs: list[list[float]]) -> list[list[float]]:
        dim = self.config.store_dim
        if dim is None:
            return vecs
        return [_truncate_normalize(v, dim) for v in vecs]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts for document ingestion (no instruction prefix)."""
        return self._prepare(self._backend.embed_texts(texts))

    def embed_query(self, text: str) -> list[float]:
        """Embed a query, applying the model's instruction prefix if configured."""
        raw = self._backend.embed_query(text, self.config.instruction)
        return self._prepare([raw])[0]
