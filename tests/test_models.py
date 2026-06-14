"""Tests for the model registry module (models.py)."""

import json
import os
from unittest.mock import patch

import pytest

from kb import models as registry
from kb.core import AGENT_MODEL_KEY


def _init_kb(root: str) -> None:
    """Stand-in for ``kb init``: write a minimal config/kb.yml so kb_root works."""
    cfg = os.path.join(root, "config", "kb.yml")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("records_dir: records\n")


class TestAdd:
    def test_add_creates_metadata_file(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            rec = registry.add(
                "kb-domain-v1",
                base_model="claude-opus-4-7",
                dataset_path=".kb/training/sft-dataset/train.jsonl",
                backend="openai_ft",
                notes="first pass",
                tags=["rag"],
            )
        assert rec["id"] == "kb-domain-v1"
        assert rec["base_model"] == "claude-opus-4-7"
        assert rec["backend"] == "openai_ft"
        assert rec["created_at"]
        # The file is on disk in the expected location.
        path = os.path.join(root, registry.MODELS_DIR, "kb-domain-v1.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
        assert stored["id"] == "kb-domain-v1"
        assert stored["tags"] == ["rag"]

    def test_add_refuses_duplicate_without_overwrite(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("dup", base_model="m", dataset_path="d",
                         backend="external")
            with pytest.raises(ValueError) as excinfo:
                registry.add("dup", base_model="m", dataset_path="d",
                             backend="external")
        assert "already exists" in str(excinfo.value)
        # overwrite=True succeeds.
        with patch("kb.models.kb_root", return_value=root):
            registry.add("dup", base_model="m2", dataset_path="d",
                         backend="external", overwrite=True,
                         notes="replaced")
        with open(os.path.join(root, registry.MODELS_DIR, "dup.json"),
                  encoding="utf-8") as f:
            rec = json.load(f)
        assert rec["base_model"] == "m2"
        assert rec["notes"] == "replaced"

    def test_add_rejects_invalid_slug(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            with pytest.raises(ValueError):
                registry.add("Bad Slug!", base_model="m", dataset_path="d",
                             backend="external")

    def test_add_rejects_unknown_backend(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            with pytest.raises(ValueError):
                registry.add("ok", base_model="m", dataset_path="d",
                             backend="not-real")


class TestList:
    def test_list_returns_all_models(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("a", base_model="m", dataset_path="d",
                         backend="external")
            registry.add("b", base_model="m", dataset_path="d",
                         backend="external")
            all_models = registry.list_all()
        ids = [m["id"] for m in all_models]
        assert ids == ["a", "b"]

    def test_list_empty_when_no_dir(self, tmp_path):
        # No _init_kb; .kb/models does not exist.
        with patch("kb.models.kb_root", return_value=str(tmp_path)):
            assert registry.list_all() == []

    def test_list_filters_by_tag(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("a", base_model="m", dataset_path="d",
                         backend="external", tags=["rag"])
            registry.add("b", base_model="m", dataset_path="d",
                         backend="external", tags=["web"])
            registry.add("c", base_model="m", dataset_path="d",
                         backend="external", tags=["rag", "domain"])
        with patch("kb.models.kb_root", return_value=root):
            rag = registry.list_all(tag="rag")
        assert {m["id"] for m in rag} == {"a", "c"}


class TestShow:
    def test_show_returns_model(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("m1", base_model="claude-opus-4-7",
                         dataset_path="d", backend="openai_ft")
        with patch("kb.models.kb_root", return_value=root):
            rec = registry.show("m1")
        assert rec is not None
        assert rec["id"] == "m1"
        assert rec["base_model"] == "claude-opus-4-7"

    def test_show_returns_none_for_missing(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            assert registry.show("ghost") is None


class TestUseAndGetDefault:
    def test_use_writes_to_config(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("m1", base_model="m", dataset_path="d",
                         backend="external")
            registry.use("m1")
        # kb.yml now carries agent_model: m1 — and the original key survives.
        with open(os.path.join(root, "config", "kb.yml"), encoding="utf-8") as f:
            text = f.read()
        assert AGENT_MODEL_KEY + ":" in text
        assert "records_dir: records" in text

    def test_use_rejects_unregistered(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            with pytest.raises(FileNotFoundError):
                registry.use("ghost")

    def test_get_default_returns_used_model(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("m1", base_model="claude-opus-4-7",
                         dataset_path="d", backend="openai_ft")
            registry.use("m1")
            default = registry.get_default()
        assert default is not None
        assert default["id"] == "m1"
        assert default["base_model"] == "claude-opus-4-7"

    def test_get_default_returns_none_when_unset(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            assert registry.get_default() is None

    def test_get_default_warns_on_dangling_config(self, tmp_path, caplog):
        root = str(tmp_path)
        _init_kb(root)
        # Inject a dangling reference directly into the config file.
        cfg = os.path.join(root, "config", "kb.yml")
        with open(cfg, "a", encoding="utf-8") as f:
            f.write(f"{AGENT_MODEL_KEY}: ghost\n")
        with patch("kb.models.kb_root", return_value=root):
            with caplog.at_level("WARNING", logger="kb.models"):
                result = registry.get_default()
        assert result is None
        # The dangling reference should have been logged.
        assert any("ghost" in rec.message for rec in caplog.records)


class TestEvalRecord:
    def test_eval_record_persists(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            registry.add("m1", base_model="m", dataset_path="d",
                         backend="external")
            rec = registry.eval_record(
                "m1",
                {"val_pairs": 62, "exact_match": 0.41, "rougeL": 0.78},
            )
        # Returned record echoes the inputs plus bookkeeping fields.
        assert rec["val_pairs"] == 62
        assert rec["exact_match"] == 0.41
        assert rec["model_id"] == "m1"
        assert rec["recorded_at"]
        # File on disk under .kb/models/eval/<id>.json.
        path = os.path.join(root, registry.MODELS_DIR, registry.EVAL_SUBDIR,
                            "m1.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
        assert stored["rougeL"] == 0.78
