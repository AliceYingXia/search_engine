from pathlib import Path

BASE_DIR          = Path(__file__).parent
SUMMARIES_PATH    = BASE_DIR.parent / "01_process_data" / "cleaned" / "recipe_summaries.parquet"
ENV_PATH          = BASE_DIR.parent.parent / ".env"
PGVECTOR_CSV_PATH = BASE_DIR / "recipes_for_pgvector.csv"

MODEL_GPT52  = "azure/gpt-5.2"
MODEL_CLAUDE = "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"

CHUNK_SIZE            = 20    # max recipes per LLM relevance call
MAX_CONNECTOR_OVERLAP = 0.50  # max signal-connector overlap between any two seeds
INFRA_CONNECTOR_FREQ  = 0.50  # connectors in >50% of an author's recipes are infra
MIN_CONNECTORS        = 3     # seeds must have at least this many total distinct connectors

POSITIVE_LABELS = {"Strongly Related", "Weakly Related"}

LLM_MAX_ATTEMPTS = 3   # total attempts (1 original + 2 retries)
LLM_BACKOFF_BASE = 2   # sleep = LLM_BACKOFF_BASE ** attempt  (2s, 4s, ...)
