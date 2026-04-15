from __future__ import annotations

import math
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import EmbeddingSpec


load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def _require_baseten_api_key() -> str:
    api_key = os.getenv("BASETEN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing BASETEN_API_KEY. Set it in your shell or repo .env before running."
        )
    return api_key


def truncate_normalize(vec: list[float], dims: int) -> list[float]:
    kept = vec[:dims]
    norm = math.sqrt(sum(x * x for x in kept))
    return [x / norm for x in kept] if norm > 0 else kept


class QwenEmbeddingClient:
    def __init__(self, spec: EmbeddingSpec):
        self.spec = spec
        self.api_key = _require_baseten_api_key()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Api-Key {self.api_key}"}

    def _prepare_query(self, text: str) -> str:
        if not self.spec.use_instruction:
            return text
        return f"{self.spec.instruction}{text}"

    def embed_batch(
        self,
        texts: list[str],
        *,
        max_retries: int = 5,
        timeout_s: int = 300,
    ) -> list[list[float]]:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = requests.post(
                    self.spec.predict_url,
                    headers=self._headers(),
                    json={"input": texts, "model": "model", "encoding_format": "float"},
                    timeout=timeout_s,
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and "data" in data:
                    vectors = [row["embedding"] for row in sorted(data["data"], key=lambda x: x["index"])]
                elif isinstance(data, list) and data and isinstance(data[0], list):
                    vectors = data
                else:
                    raise ValueError(f"Unexpected Baseten batch response format: {type(data)}")
                return [truncate_normalize(vec, self.spec.dims) for vec in vectors]
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"Baseten embedding batch failed after {max_retries} attempts"
                    ) from exc
                sleep_s = min(2 ** attempt, 30)
                print(f"    request failed ({exc.__class__.__name__}); retrying in {sleep_s}s ...")
                time.sleep(sleep_s)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        all_vectors: list[list[float]] = []
        batch_size = self.spec.batch_size
        total = len(texts)

        for start in range(0, total, batch_size):
            batch = texts[start : start + batch_size]
            print(f"  embedding batch {start + 1}-{start + len(batch)} / {total}")
            vectors = self.embed_batch(batch)
            all_vectors.extend(vectors)

        return all_vectors

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        prepared = [self._prepare_query(text) for text in queries]
        return self.embed_texts(prepared)
