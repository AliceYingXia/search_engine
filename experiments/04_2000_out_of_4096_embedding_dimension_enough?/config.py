from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "results"

QWEN3_8B_PREDICT_URL = (
    "https://model-wom8ozkq.api.baseten.co/environments/production/predict"
)

DEFAULT_INSTRUCTION = (
    "Instruct: Retrieve the most relevant document for this search query.\n"
    "Query: "
)

SUPPORTED_DIMS = (4096, 4000, 2000)
DEFAULT_BATCH_SIZE = 64


@dataclass(frozen=True)
class EmbeddingSpec:
    model_name: str
    predict_url: str
    dims: int
    use_instruction: bool = True
    instruction: str = DEFAULT_INSTRUCTION
    batch_size: int = DEFAULT_BATCH_SIZE


DEFAULT_SPEC = EmbeddingSpec(
    model_name="Qwen/Qwen3-Embedding-8B",
    predict_url=QWEN3_8B_PREDICT_URL,
    dims=4096,
    use_instruction=True,
)
