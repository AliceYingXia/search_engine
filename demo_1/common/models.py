from __future__ import annotations

from dataclasses import dataclass

from common.clients import baseten_batch_embed

DEFAULT_MODEL_NAME = "Qwen/Qwen3-Embedding-8B-full+instruct"


@dataclass
class ModelConfig:
    table: str
    dimension: int
    predict_url: str
    instruction: str | None = None


MODEL_REGISTRY: dict[str, ModelConfig] = {
    DEFAULT_MODEL_NAME: ModelConfig(
        table="embeddings_qwen3_embedding_8b_full",
        dimension=4096,
        predict_url="https://model-wom8ozkq.api.baseten.co/environments/production/predict",
        instruction=(
            "Instruct: Retrieve the most relevant automation workflow recipe "
            "for this search query.\nQuery: "
        ),
    ),
}


class EmbeddingModel:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        if model_name not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model: {model_name}")
        self.name = model_name
        self.config = MODEL_REGISTRY[model_name]
        self.table = self.config.table
        self.source_column = "text_no_comments"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return baseten_batch_embed(self.config.predict_url, texts)

    def embed_query(self, text: str) -> list[float]:
        prepared = f"{self.config.instruction}{text}" if self.config.instruction else text
        return self.embed_texts([prepared])[0]
