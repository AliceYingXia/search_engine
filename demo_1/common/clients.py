from __future__ import annotations

import os
import ssl
import warnings
from pathlib import Path
from ssl import SSLSocket

import requests as _requests
import urllib3
from dotenv import load_dotenv
from opensearchpy import OpenSearch

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings("ignore", message="When using `ssl_context`", category=UserWarning)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_opensearch_client: OpenSearch | None = None


def _make_no_verify_ssl_context() -> ssl.SSLContext:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx = ssl.SSLContext()  # noqa: S502
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def _wrap_no_verify(sock, server_side=False, do_handshake_on_connect=True,
                        suppress_ragged_eofs=True, server_hostname=None, session=None):
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
    global _opensearch_client
    if _opensearch_client is None:
        missing = [name for name in ("OPENSEARCH_USER", "OPENSEARCH_PASSWORD") if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                "Missing required environment variables for OpenSearch: "
                + ", ".join(missing)
            )
        use_ssl = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
        verify = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
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


def ensure_opensearch_connection() -> None:
    try:
        connected = get_client().ping()
    except Exception as exc:
        raise RuntimeError(
            "Could not connect to OpenSearch. Check OPENSEARCH_* settings in .env "
            "and make sure the service is reachable."
        ) from exc
    if not connected:
        raise RuntimeError(
            "OpenSearch did not respond to ping. Check the host, port, credentials, "
            "and whether the service is running."
        )


def parse_predict_embeddings_batch(response_json) -> list[list[float]]:
    if isinstance(response_json, list) and response_json and isinstance(response_json[0], list):
        return response_json
    if isinstance(response_json, dict) and "data" in response_json:
        return [d["embedding"] for d in sorted(response_json["data"], key=lambda x: x["index"])]
    raise ValueError(f"Unexpected /predict batch response format: {type(response_json)}")


def baseten_batch_embed(predict_url: str, texts: list[str]) -> list[list[float]]:
    api_key = os.getenv("BASETEN_API_KEY")
    if not api_key:
        raise RuntimeError("Missing BASETEN_API_KEY in .env.")

    try:
        response = _requests.post(
            predict_url,
            headers={"Authorization": f"Api-Key {api_key}"},
            json={"input": texts, "model": "model", "encoding_format": "float"},
            timeout=60,
        )
        response.raise_for_status()
        return parse_predict_embeddings_batch(response.json())
    except _requests.RequestException as exc:
        raise RuntimeError(
            "Failed to fetch embeddings from Baseten. Check BASETEN_API_KEY, network access, "
            "and the configured embedding endpoint."
        ) from exc
