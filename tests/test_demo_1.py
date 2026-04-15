from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo_1"


def load_process_module():
    sys.modules.setdefault("pandas", types.ModuleType("pandas"))
    module_path = DEMO_DIR / "01_process_json" / "process_recipe_json_files.py"
    spec = importlib.util.spec_from_file_location("demo_1_process_recipe_json_files", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_retrieval_module():
    common_pkg = types.ModuleType("common")
    common_models = types.ModuleType("common.models")

    class DummyEmbeddingModel:
        table = "embeddings_qwen3_embedding_8b_full"

    common_models.EmbeddingModel = DummyEmbeddingModel
    sys.modules["common"] = common_pkg
    sys.modules["common.models"] = common_models

    module_path = DEMO_DIR / "common" / "retrieval.py"
    spec = importlib.util.spec_from_file_location("demo_1_common_retrieval", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


PROCESS = load_process_module()
RETRIEVAL = load_retrieval_module()


SAMPLE_RECIPE = {
    "keyword": "recipe",
    "block": [
        {
            "keyword": "trigger",
            "provider": "slack",
            "name": "new_message",
            "comment": "Listen for incoming messages",
            "extended_output_schema": [
                {"name": "channel_id"},
                {"name": "message_text"},
            ],
        },
        {
            "keyword": "action",
            "provider": "salesforce",
            "name": "search_records",
            "comment": "Find the account by external id",
            "input": {
                "object": "Account",
                "external_id": "123",
                "3fa85f64-5717-4562-b3fc-2c963f66afa6": "ignore me",
            },
            "extended_output_schema": [
                {"name": "account_id"},
                {"name": "owner", "properties": [{"name": "email"}]},
            ],
        },
    ],
}


class Demo1ProcessTests(unittest.TestCase):
    def test_process_file_extracts_expected_fields(self) -> None:
        payload = {
            "recipe_uid": "recipe-123",
            "flow_id": 10,
            "version_no": 2,
            "author_id": 42,
            "payload": json.dumps(SAMPLE_RECIPE),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "recipe.json"
            path.write_text(json.dumps(payload))
            row = PROCESS.process_file(path)

        self.assertEqual(row["recipe_uid"], "recipe-123")
        self.assertEqual(row["flow_id"], 10)
        self.assertEqual(row["version_no"], 2)
        self.assertEqual(row["author_id"], 42)
        self.assertEqual(row["connectors"], ["salesforce", "slack"])
        self.assertEqual(row["actions"], ["salesforce/search_records", "slack/new_message"])
        self.assertEqual(row["input_fields"], ["external_id", "object"])
        self.assertEqual(row["datapill_fields"], ["account_id", "channel_id", "email", "message_text", "owner"])
        self.assertEqual(row["step_count"], 3)
        self.assertIn("# Listen for incoming messages", row["text_with_comments"])
        self.assertNotIn("# Listen for incoming messages", row["text_no_comments"])
        self.assertIn("Connectors: salesforce, slack", row["text_no_comments"])


class Demo1RetrievalTests(unittest.TestCase):
    def test_query_signal_detects_structured_exact(self) -> None:
        self.assertEqual(RETRIEVAL.query_signal("recipes impacted by Custom_Status__c"), "structured_exact")

    def test_query_signal_detects_technical_words(self) -> None:
        self.assertEqual(RETRIEVAL.query_signal("salesforce opportunity lookup"), "technical_words")

    def test_query_signal_detects_natural_language(self) -> None:
        query = "which automations handle employee onboarding across departments and teams"
        self.assertEqual(RETRIEVAL.query_signal(query), "natural_language")

    def test_weights_for_signal(self) -> None:
        self.assertEqual(RETRIEVAL.weights_for_signal("structured_exact"), ("structured_exact", 2.0, 1.0))
        self.assertEqual(RETRIEVAL.weights_for_signal("technical_words"), ("technical_words", 1.0, 2.0))
        self.assertEqual(RETRIEVAL.weights_for_signal("natural_language"), ("natural_language", 0.0, 1.0))

    def test_rrf_prefers_documents_supported_by_both_lists(self) -> None:
        ranked = RETRIEVAL.rrf([
            (["doc_a", "doc_b", "doc_c"], 1.0),
            (["doc_b", "doc_c", "doc_d"], 1.0),
        ])
        self.assertEqual(ranked[0], "doc_b")
        self.assertIn("doc_c", ranked[:3])


if __name__ == "__main__":
    unittest.main()
