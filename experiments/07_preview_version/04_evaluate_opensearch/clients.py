"""
clients.py
==========

Shared infrastructure for the evaluate_opensearch pipeline:

  - OpenSearch client factory (from environment variables)
  - Lazy OpenAI API client factory
  - HuggingFace SentenceTransformer cache
  - Low-level Baseten /predict response parsers
  - Eval dataset helpers

All other scripts in this folder import from here rather than
re-defining these objects individually.

API clients are initialised lazily so that scripts which only need the
client object don't require all env vars to be set upfront.
"""

import os
import ssl
import warnings
from pathlib import Path
from ssl import SSLSocket

import urllib3
from dotenv import load_dotenv
from openai import OpenAI
from opensearchpy import OpenSearch
from sentence_transformers import SentenceTransformer

# Suppress urllib3's InsecureRequestWarning — expected for local dev with self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# Suppress opensearch-py's "ssl_context overrides other SSL kwargs" notice
warnings.filterwarnings("ignore", message="When using `ssl_context`", category=UserWarning)

load_dotenv(Path(__file__).parent.parent.parent / ".env")

# ---------------------------------------------------------------------------
# Lazy OpenAI API client
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

# ---------------------------------------------------------------------------
# OpenSearch client (lazy singleton)
# ---------------------------------------------------------------------------

_opensearch_client: OpenSearch | None = None


def _make_no_verify_ssl_context() -> ssl.SSLContext:
    """Return an SSL context that skips certificate verification entirely.

    pip-system-certs patches ssl.SSLContext.wrap_socket at Python startup
    (via sitecustomize.py) to route all SSL through macOS's truststore, which
    rejects OpenSearch's default self-signed cert even when verify_certs=False.

    Setting wrap_socket on the *instance* takes precedence over the class-level
    patch in Python's attribute lookup, so urllib3 calls our version instead.
    Our version calls SSLSocket._create directly — the same thing the original
    ssl.py wrap_socket does — without the macOS verification layer on top.
    """
    # PROTOCOL_TLS_CLIENT enforces cert verification at the C level in
    # Python 3.14 + OpenSSL 3.6, ignoring verify_mode=CERT_NONE. The
    # deprecated bare SSLContext() does not have this restriction.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx = ssl.SSLContext()  # noqa: S502
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def _wrap_no_verify(sock, server_side=False, do_handshake_on_connect=True,
                        suppress_ragged_eofs=True, server_hostname=None, session=None):
        # urllib3 may have overwritten verify_mode before calling wrap_socket;
        # re-assert CERT_NONE so the C-level handshake skips verification.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return SSLSocket._create(
            sock,
            server_side=server_side,
            do_handshake_on_connect=do_handshake_on_connect,
            suppress_ragged_eofs=suppress_ragged_eofs,
            server_hostname=server_hostname,
            context=ctx,
            session=session,
        )

    ctx.wrap_socket = _wrap_no_verify
    return ctx


def get_client() -> OpenSearch:
    """Return the shared OpenSearch client, creating it once."""
    global _opensearch_client
    if _opensearch_client is None:
        use_ssl = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
        verify  = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"

        _opensearch_client = OpenSearch(
            hosts=[{
                "host": os.getenv("OPENSEARCH_HOST", "localhost"),
                "port": int(os.getenv("OPENSEARCH_PORT", "9200")),
            }],
            http_auth=(
                os.environ["OPENSEARCH_USER"],
                os.environ["OPENSEARCH_PASSWORD"],
            ),
            use_ssl=use_ssl,
            ssl_context=_make_no_verify_ssl_context() if use_ssl and not verify else None,
            ssl_show_warn=False,
        )
    return _opensearch_client
