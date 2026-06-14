"""Tests for the fine-tune preparation / submission module (finetune.py)."""

import json
import os

import pytest

from kb.finetune import (
    SUPPORTED_BACKENDS,
    SUPPORTED_FORMATS,
    prepare,
    submit,
    to_alpaca,
    to_hf,
    to_openai,
)


def _write_openai_jsonl(path: str, records: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _sample_record() -> dict:
    """Single OpenAI-format SFT record with kb metadata fields."""
    return {
        "messages": [
            {"role": "system", "content": "あなたはドメイン特化のAIアシスタントです。"},
            {"role": "user", "content": "RAGのリトリーバルの役割は？"},
            {"role": "assistant", "content": "クエリに関連する文書を検索しLLMに供給します。"},
        ],
        "_source_doc": "01HXYZ-RAG-OVERVIEW",
        "_difficulty": "basic",
        "_tags": ["rag", "retrieval"],
    }


class TestToHf:
    def test_renames_underscore_fields(self):
        rec = _sample_record()
        out = to_hf(rec)
        assert "system" in out
        assert out["system"] == rec["messages"][0]["content"]
        # `_`-prefixed metadata must be present without the leading underscore.
        assert out["source_doc"] == "01HXYZ-RAG-OVERVIEW"
        assert out["difficulty"] == "basic"
        assert out["tags"] == ["rag", "retrieval"]
        # Original underscore keys are gone.
        for k in out:
            assert not k.startswith("_")
        # messages keeps user + assistant only.
        roles = [m["role"] for m in out["messages"]]
        assert roles == ["user", "assistant"]
        assert "system" not in roles


class TestToOpenai:
    def test_strips_metadata(self):
        rec = _sample_record()
        out = to_openai(rec)
        # Only the canonical key survives.
        assert list(out.keys()) == ["messages"]
        roles = [m["role"] for m in out["messages"]]
        # system is preserved, user + assistant verbatim.
        assert "system" in roles
        assert "user" in roles
        assert "assistant" in roles
        for k in out:
            assert not k.startswith("_")


class TestToAlpaca:
    def test_concatenates_system_into_instruction(self):
        rec = _sample_record()
        out = to_alpaca(rec)
        assert out["instruction"].startswith(rec["messages"][0]["content"])
        # The user message comes after a blank line separator.
        assert rec["messages"][1]["content"] in out["instruction"]
        assert out["input"] == ""
        assert out["output"] == rec["messages"][2]["content"]
        assert out["_kb_meta"]["source_doc"] == "01HXYZ-RAG-OVERVIEW"


class TestPrepareFormats:
    def test_prepare_hf_format(self, tmp_path):
        src = tmp_path / "in.jsonl"
        _write_openai_jsonl(str(src), [_sample_record()])
        out_dir = tmp_path / "out"
        result = prepare(str(src), str(out_dir), "hf")
        assert result["format"] == "hf"
        assert result["count"] == 1
        assert result["had_meta"] is True
        assert os.path.exists(result["output_path"])
        with open(result["output_path"], encoding="utf-8") as f:
            line = f.readline()
        rec = json.loads(line)
        assert rec["source_doc"] == "01HXYZ-RAG-OVERVIEW"
        assert rec["system"]

    def test_prepare_openai_format(self, tmp_path):
        src = tmp_path / "in.jsonl"
        _write_openai_jsonl(str(src), [_sample_record()])
        out_dir = tmp_path / "out"
        result = prepare(str(src), str(out_dir), "openai")
        assert result["format"] == "openai"
        assert result["count"] == 1
        with open(result["output_path"], encoding="utf-8") as f:
            rec = json.loads(f.readline())
        assert list(rec.keys()) == ["messages"]
        assert [m["role"] for m in rec["messages"]] == [
            "system", "user", "assistant",
        ]

    def test_prepare_alpaca_format(self, tmp_path):
        src = tmp_path / "in.jsonl"
        _write_openai_jsonl(str(src), [_sample_record()])
        out_dir = tmp_path / "out"
        result = prepare(str(src), str(out_dir), "alpaca")
        assert result["format"] == "alpaca"
        with open(result["output_path"], encoding="utf-8") as f:
            rec = json.loads(f.readline())
        assert rec["instruction"].startswith("あなたはドメイン特化の")
        assert rec["output"] == "クエリに関連する文書を検索しLLMに供給します。"
        assert rec["_kb_meta"]["source_doc"] == "01HXYZ-RAG-OVERVIEW"

    def test_prepare_handles_invalid_format(self, tmp_path):
        src = tmp_path / "in.jsonl"
        _write_openai_jsonl(str(src), [_sample_record()])
        with pytest.raises(ValueError) as excinfo:
            prepare(str(src), str(tmp_path / "out"), "xml")
        assert "format must be one of" in str(excinfo.value)
        # Confirm the closed set matches the public constant.
        assert set(SUPPORTED_FORMATS) == {"hf", "openai", "alpaca"}

    def test_prepare_handles_empty_dataset(self, tmp_path):
        src = tmp_path / "in.jsonl"
        # Write a file with only blank lines.
        with open(src, "w", encoding="utf-8") as f:
            f.write("\n\n   \n")
        result = prepare(str(src), str(tmp_path / "out"), "openai")
        assert result["count"] == 0
        assert result["had_meta"] is False
        # Output file should exist but be empty.
        with open(result["output_path"], encoding="utf-8") as f:
            assert f.read() == ""


class TestSubmit:
    def test_submit_records_job(self, tmp_path):
        ds = tmp_path / "train.jsonl"
        _write_openai_jsonl(str(ds), [_sample_record()])
        result = submit(
            str(ds), base_model="claude-opus-4-7", backend="openai_ft",
            output_model_id="kb-domain-v1",
            hyperparams={"n_epochs": 3, "lr": 5e-6, "lora": True},
            notes="first pass",
            root=str(tmp_path),
        )
        workdir = result["workdir"]
        assert os.path.isdir(workdir)
        for required in ("job.json", "config.json", "README.md", "status.log"):
            assert os.path.exists(os.path.join(workdir, required)), required
        # job.json parses with the right shape.
        with open(os.path.join(workdir, "job.json"), encoding="utf-8") as f:
            job = json.load(f)
        assert job["status"] == "submitted"
        assert job["base_model"] == "claude-opus-4-7"
        assert job["backend"] == "openai_ft"
        assert job["output_model_id"] == "kb-domain-v1"
        assert job["hyperparams"]["n_epochs"] == 3
        assert job["dataset"]["path"] == str(ds)
        assert "command_hint" in job and "openai" in job["command_hint"]
        # status.log is JSONL with one 'submitted' line.
        with open(os.path.join(workdir, "status.log"), encoding="utf-8") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0]["event"] == "submitted"
        # README mentions how to register the result.
        with open(os.path.join(workdir, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        assert "kb models add" in readme
        assert "kb-domain-v1" in readme

    def test_submit_rejects_unknown_backend(self, tmp_path):
        ds = tmp_path / "train.jsonl"
        _write_openai_jsonl(str(ds), [_sample_record()])
        with pytest.raises(ValueError):
            submit(str(ds), base_model="x", backend="not-a-backend",
                   root=str(tmp_path))
        # Confirm the public backend list is exactly what the design called for.
        assert set(SUPPORTED_BACKENDS) == {
            "openai_ft", "local_lora", "unsloth", "external",
        }
