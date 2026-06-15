"""Tests for CLI: kb init, kb add, kb show, kb concept."""

import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from kb import models as registry  # noqa: F401 — used by TestModelsShowEvalScores
from kb.cli import main
from kb.core import DOC_DIR, RECORDS_DIR, shard_path  # noqa: F401 — Phase 13.2 tests
from kb.index import (  # noqa: F401 — used by TestHealthModelsFlag
    index_document,
    index_path,
    init_db,
)


class TestInit:
    def test_init_creates_structure(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["init", "."])
            assert result.exit_code == 0
            assert os.path.exists(os.path.join("config", "kb.yml"))
            assert os.path.isdir("records")
            assert os.path.isdir("inbox")

    def test_init_idempotent_fails(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["init", "."])
            assert result.exit_code == 1


class TestAdd:
    def test_add_creates_document(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "add", "--title", "Test", "--source", "https://example.com",
                "--content", "Hello world",
            ])
            assert result.exit_code == 0
            assert "Added:" in result.output

            # Find the created file
            doc_dir = os.path.join("records", "doc")
            files = []
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    files.append(os.path.join(root, fn))
            assert len(files) == 1

            with open(files[0]) as f:
                content = f.read()
            assert "id: " in content
            assert "title: Test" in content
            assert "Hello world" in content

    def test_add_requires_init(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, [
                "add", "--title", "Test", "--content", "x",
            ])
            assert result.exit_code == 1
            assert "Not in a knowledge bucket" in result.output

    def test_add_stdin_content(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "add", "--title", "Stdin Test",
            ], input="Content from stdin\n")
            assert result.exit_code == 0

    def test_add_source_key_in_front_matter(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "add", "--title", "Test", "--source", "https://example.com",
                "--content", "Hello world",
            ])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    with open(os.path.join(root, fn)) as f:
                        content = f.read()
                    assert "source_key: url:" in content
                    return
            pytest.fail("No document file found")

    def test_add_memo_source_key(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "add", "--title", "My Memo", "--type", "memo",
                "--content", "Some notes",
            ])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    with open(os.path.join(root, fn)) as f:
                        content = f.read()
                    assert "source_key: memo:" in content
                    return
            pytest.fail("No document file found")


class TestShow:
    def _add_doc(self, runner, title="Test Doc", content="Hello world"):
        result = runner.invoke(main, [
            "add", "--title", title, "--source", "https://example.com",
            "--content", content,
        ])
        # Extract doc_id from output like "Added: 01K2Z9P7Y8QWERTY1234567890"
        for line in result.output.splitlines():
            if line.startswith("Added:"):
                return line.split(":")[1].strip()
        return None

    def test_show_displays_metadata(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            doc_id = self._add_doc(runner, title="My Title", content="Body text here")
            assert doc_id is not None

            result = runner.invoke(main, ["show", doc_id])
            assert result.exit_code == 0
            assert f"ID:          {doc_id}" in result.output
            assert "Title:       My Title" in result.output
            assert "Source type: web" in result.output
            assert "Source:      https://example.com" in result.output
            assert "Body text here" in result.output

    def test_show_not_found(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["show", "nonexistent_id"])
            assert result.exit_code == 1
            assert "Document not found" in result.output

    def test_show_requires_init(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["show", "some_id"])
            assert result.exit_code == 1
            assert "Not in a knowledge bucket" in result.output

    def test_show_truncates_long_body(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            long_content = "\n".join(f"Line {i}" for i in range(30))
            doc_id = self._add_doc(runner, content=long_content)
            result = runner.invoke(main, ["show", doc_id])
            assert result.exit_code == 0
            assert "more lines, use --full to show" in result.output

    def test_show_full_flag(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            long_content = "\n".join(f"Line {i}" for i in range(30))
            doc_id = self._add_doc(runner, content=long_content)
            result = runner.invoke(main, ["show", doc_id, "--full"])
            assert result.exit_code == 0
            assert "more lines" not in result.output
            assert "Line 29" in result.output

    def test_show_with_concepts(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "add", "--title", "Tagged Doc", "--content", "text",
                "--concepts", "rust, systems-programming",
            ])
            doc_id = None
            for line in result.output.splitlines():
                if line.startswith("Added:"):
                    doc_id = line.split(":")[1].strip()

            result = runner.invoke(main, ["show", doc_id])
            assert result.exit_code == 0
            assert "Concepts:" in result.output
            assert "rust" in result.output


class TestConcept:
    def _setup_with_graph(self, runner):
        """Init bucket, add doc with concepts, build graph."""
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, [
            "add", "--title", "Rust Guide", "--source", "https://example.com/rust",
            "--content", "Rust is a systems programming language.",
            "--concepts", "rust, systems-programming",
        ])
        doc_id = None
        for line in result.output.splitlines():
            if line.startswith("Added:"):
                doc_id = line.split(":")[1].strip()

        # Build index and graph
        runner.invoke(main, ["index", "--rebuild"])
        runner.invoke(main, ["graph", "build"])
        return doc_id

    def test_concept_displays_metadata(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            self._setup_with_graph(runner)
            result = runner.invoke(main, ["concept", "rust"])
            assert result.exit_code == 0
            assert "ID:       rust" in result.output
            assert "Label:    rust" in result.output
            assert "Kind:     concept" in result.output
            assert "DF:       1" in result.output

    def test_concept_shows_documents(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            self._setup_with_graph(runner)
            result = runner.invoke(main, ["concept", "rust"])
            assert result.exit_code == 0
            assert "Documents" in result.output
            assert "Rust Guide" in result.output

    def test_concept_not_found(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            self._setup_with_graph(runner)
            result = runner.invoke(main, ["concept", "nonexistent"])
            assert result.exit_code == 1
            assert "Concept not found" in result.output

    def test_concept_requires_init(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["concept", "rust"])
            assert result.exit_code == 1
            assert "Not in a knowledge bucket" in result.output

    def test_concept_shows_note_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            self._setup_with_graph(runner)
            # Create a concept note
            os.makedirs(os.path.join("records", "concept"), exist_ok=True)
            with open(os.path.join("records", "concept", "rust.md"), "w") as f:
                f.write("# Rust\n\nA systems programming language.\n")

            result = runner.invoke(main, ["concept", "rust"])
            assert result.exit_code == 0
            assert "Concept Note" in result.output
            assert "systems programming language" in result.output

    def test_concept_shows_cooccurring(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # Add docs where rust+systems-programming co-occur in 2+ docs
            runner.invoke(main, [
                "add", "--title", "Rust Guide", "--source", "https://example.com/rust",
                "--content", "Rust is a systems programming language.",
                "--concepts", "rust, systems-programming",
            ])
            runner.invoke(main, [
                "add", "--title", "Rust Patterns", "--source", "https://example.com/patterns",
                "--content", "Design patterns in Rust.",
                "--concepts", "rust, systems-programming, design-patterns",
            ])
            runner.invoke(main, [
                "add", "--title", "Rust Memory", "--source", "https://example.com/memory",
                "--content", "Memory management in Rust.",
                "--concepts", "rust, systems-programming",
            ])
            # Build index and graph (which builds co-occurrence edges)
            runner.invoke(main, ["index", "--rebuild"])
            runner.invoke(main, ["graph", "build"])

            result = runner.invoke(main, ["concept", "rust"])
            assert result.exit_code == 0
            assert "Co-occurring concepts" in result.output


class TestAddPaperSourceKey:
    @patch("kb.parsers.paper.parse_paper")
    def test_source_key_in_front_matter(self, mock_parse):
        mock_parse.return_value = {
            "title": "Test Paper",
            "source_type": "paper",
            "source_url": "https://arxiv.org/abs/2301.12345",
            "body": "Abstract text",
            "metadata": {"authors": ["Alice"], "arxiv_id": "2301.12345"},
        }
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["add-paper", "2301.12345"])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    with open(os.path.join(root, fn)) as f:
                        content = f.read()
                    assert "source_key: arxiv:" in content
                    return
            pytest.fail("No document file found")


class TestAddPdfSourceKey:
    @patch("kb.parsers.pdf.parse_pdf")
    def test_source_key_in_front_matter(self, mock_parse):
        mock_parse.return_value = {
            "title": "Test PDF",
            "source_type": "pdf",
            "source_url": "https://s3.example.com/doc.pdf",
            "body": "Extracted text",
            "metadata": {"page_count": 5, "author": "Bob"},
        }
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # Create a dummy PDF file
            with open("test.pdf", "w") as f:
                f.write("fake pdf")
            result = runner.invoke(main, ["add-pdf", "test.pdf"])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    with open(os.path.join(root, fn)) as f:
                        content = f.read()
                    assert "source_key: url:" in content
                    return
            pytest.fail("No document file found")


class TestAddRepoSourceKey:
    @patch("kb.parsers.repo.parse_repo")
    def test_source_key_in_front_matter(self, mock_parse):
        mock_parse.return_value = {
            "title": "user/repo",
            "source_type": "git_repo",
            "source_url": "https://github.com/user/repo",
            "body": "# README\nHello",
            "metadata": {"language": "Python", "stars": 42, "topics": []},
        }
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["add-repo", "https://github.com/user/repo"])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    with open(os.path.join(root, fn)) as f:
                        content = f.read()
                    assert "source_key: repo:" in content
                    return
            pytest.fail("No document file found")


class TestAddRepoDedup:
    @patch("kb.parsers.repo.parse_repo")
    def test_re_add_updates_not_duplicates(self, mock_parse):
        """Re-adding the same repo URL updates the existing doc, no dupe."""
        mock_parse.return_value = {
            "title": "user/repo",
            "source_type": "git_repo",
            "source_url": "https://github.com/user/repo",
            "body": "# README\nHello",
            "metadata": {"language": "Python", "stars": 42, "topics": []},
        }
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, ["add-repo", "https://github.com/user/repo"])
            # Re-add with changed content
            mock_parse.return_value["body"] = "# README\nUpdated content"
            result = runner.invoke(main, ["add-repo", "https://github.com/user/repo"])
            assert result.exit_code == 0

            doc_dir = os.path.join("records", "doc")
            count = 0
            for root, dirs, filenames in os.walk(doc_dir):
                for fn in filenames:
                    if fn.endswith(".md"):
                        count += 1
            assert count == 1  # exactly one doc, not two


class TestDoctor:
    def test_doctor_passes_on_clean_bucket(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, ["add", "--title", "T", "--content", "body",
                                 "--type", "web", "--source", "https://x.com"])
            result = runner.invoke(main, ["doctor"])
            assert result.exit_code == 0
            assert "All checks passed" in result.output

    def test_doctor_fails_on_broken_front_matter(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # Write a doc with a colon in the title that breaks YAML
            import os as _os
            doc_dir = _os.path.join("records", "doc", "ab", "cd")
            _os.makedirs(doc_dir)
            with open(_os.path.join(doc_dir, "01KTEST.md"), "w") as f:
                f.write("---\nid: 01KTEST\ntitle: bad: title\n"
                        "source_type: web\nsource_key: url:x\n---\n\nbody\n")
            result = runner.invoke(main, ["doctor"])
            assert result.exit_code != 0


class TestModelsCLI:
    def test_models_list_outside_bucket_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["models"])
            assert result.exit_code == 1
            assert "kb init" in result.output

    def test_models_list_empty(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["models"])
            assert result.exit_code == 0
            assert "No models registered" in result.output

    def test_models_add_and_list(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
                "--notes", "first pass",
            ])
            assert result.exit_code == 0
            assert "Registered model 'kb-domain-v1'" in result.output

            result = runner.invoke(main, ["models"])
            assert result.exit_code == 0
            assert "kb-domain-v1" in result.output
            assert "claude-opus-4-7" in result.output

    def test_models_show_and_use(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            result = runner.invoke(main, ["models", "show", "kb-domain-v1"])
            assert result.exit_code == 0
            assert "id: kb-domain-v1" in result.output
            assert "base_model: claude-opus-4-7" in result.output

            result = runner.invoke(main, ["models", "use", "kb-domain-v1"])
            assert result.exit_code == 0
            assert "Active model: kb-domain-v1" in result.output

            # The active line appears in subsequent list output.
            result = runner.invoke(main, ["models"])
            assert "(active = kb-domain-v1)" in result.output

    def test_models_show_missing_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["models", "show", "ghost"])
            assert result.exit_code == 1
            assert "Model not found" in result.output

    def test_models_use_unregistered_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["models", "use", "ghost"])
            assert result.exit_code == 1
            assert "not registered" in result.output

    def test_models_list_json(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            result = runner.invoke(main, ["models", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert isinstance(data, list)
            assert data[0]["id"] == "kb-domain-v1"


class TestConfigCLI:
    def test_config_get_unset(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["config", "get", "agent_model"])
            assert result.exit_code == 0
            assert "(unset) agent_model" in result.output

    def test_config_set_and_get(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # First register a model so the agent_model validation passes.
            runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            result = runner.invoke(main, [
                "config", "set", "agent_model", "kb-domain-v1",
            ])
            assert result.exit_code == 0
            assert "agent_model = kb-domain-v1" in result.output

            result = runner.invoke(main, ["config", "get", "agent_model"])
            assert result.exit_code == 0
            assert result.output.strip() == "kb-domain-v1"

    def test_config_set_rejects_unregistered(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "config", "set", "agent_model", "ghost",
            ])
            assert result.exit_code == 1
            assert "'ghost' is not registered" in result.output

    def test_config_unset(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            runner.invoke(main, [
                "config", "set", "agent_model", "kb-domain-v1",
            ])
            result = runner.invoke(main, ["config", "unset", "agent_model"])
            assert result.exit_code == 0
            assert "(unset)" in result.output

    def test_config_get_requires_key(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["config", "get"])
            assert result.exit_code == 2


class TestFinetuneCLI:
    def test_finetune_prepare_converts_dataset(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # Write a tiny openai-format JSONL next to the default dataset
            # path so the default lookup finds it.
            ds_dir = os.path.join(".kb", "training", "sft-dataset")
            os.makedirs(ds_dir)
            ds = os.path.join(ds_dir, "train.jsonl")
            with open(ds, "w") as f:
                f.write(
                    '{"messages":[{"role":"system","content":"sys"},'
                    '{"role":"user","content":"hi"},'
                    '{"role":"assistant","content":"hello"}],'
                    '"_source_doc":"x","_difficulty":"basic",'
                    '"_tags":["rag"]}\n'
                )
            out_dir = "out"
            os.makedirs(out_dir)
            result = runner.invoke(main, [
                "finetune", "prepare",
                "--format", "openai", "--output", os.path.join(out_dir, "out.jsonl"),
            ])
            assert result.exit_code == 0, result.output
            # --output's parent dir is used; the filename is derived from the
            # source dataset, so the result is <out>/train.openai.jsonl.
            out_path = os.path.join(out_dir, "train.openai.jsonl")
            assert os.path.isfile(out_path), out_path
            with open(out_path) as f:
                line = f.readline()
            rec = json.loads(line)
            assert "_source_doc" not in rec
            assert rec["messages"][0]["role"] == "system"
            assert rec["messages"][1]["content"] == "hi"

    def test_finetune_unknown_subcommand_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["finetune", "wat"])
            assert result.exit_code == 1
            assert "Unknown finetune subcommand" in result.output

    def test_finetune_submit_records_job(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            ds_dir = os.path.join(".kb", "training", "sft-dataset")
            os.makedirs(ds_dir)
            ds = os.path.join(ds_dir, "train.jsonl")
            with open(ds, "w") as f:
                f.write('{"messages":[{"role":"user","content":"q"},'
                        '{"role":"assistant","content":"a"}]}\n')
            result = runner.invoke(main, [
                "finetune", "submit",
                "--output-model-id", "kb-test-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            assert result.exit_code == 0
            assert "Recorded job" in result.output
            assert os.path.isdir(os.path.join(".kb", "finetune"))
            # There should be exactly one job dir with the expected files.
            entries = os.listdir(os.path.join(".kb", "finetune"))
            assert len(entries) == 1
            job_dir = os.path.join(".kb", "finetune", entries[0])
            for fn in ("job.json", "config.json", "README.md", "status.log"):
                assert os.path.isfile(os.path.join(job_dir, fn)), fn

    def test_finetune_outside_bucket_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["finetune", "prepare"])
            assert result.exit_code == 1
            assert "kb init" in result.output


class TestInitAgentModel:
    def test_init_writes_agent_model_in_config(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["init", "."])
            assert result.exit_code == 0
            with open(os.path.join("config", "kb.yml")) as f:
                text = f.read()
            assert "agent_model:" in text

    def test_init_creates_models_and_finetune_dirs(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            assert os.path.isdir(os.path.join(".kb", "models"))
            assert os.path.isdir(os.path.join(".kb", "finetune"))


class TestConfigCommandInvocations:
    """Additional CLI invocation tests for ``kb config``.

    The integration phase already covered happy-path get/set/unset and the
    agent_model validation. These tests cover the rest of the surface that
    the design promised but the integration tests didn't pin down:
    ``agent_model`` round-trips through kb.yml, an unknown config key can
    still be written (the CLI is a generic scalar writer for 13.1), and the
    init-written ``agent_model: ""`` survives a subsequent unset round-trip.
    """

    def test_config_set_agent_model_round_trips_in_yaml(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-domain-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            runner.invoke(main, [
                "config", "set", "agent_model", "kb-domain-v1",
            ])
            # Read the raw file and confirm agent_model: is in it.
            with open(os.path.join("config", "kb.yml")) as f:
                text = f.read()
            assert "agent_model" in text
            assert "kb-domain-v1" in text

    def test_config_set_unknown_key_works(self):
        # The CLI is a generic scalar writer in 13.1. Setting a key the
        # rest of the codebase doesn't know about is allowed — it shows up
        # in kb.yml and can be retrieved via ``kb config get``.
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "config", "set", "my_custom_key", "hello",
            ])
            assert result.exit_code == 0, result.output
            assert "my_custom_key = hello" in result.output

            result = runner.invoke(main, ["config", "get", "my_custom_key"])
            assert result.exit_code == 0
            assert result.output.strip() == "hello"

    def test_config_init_default_agent_model_survives_unset(self):
        # kb init writes agent_model: "" by default. An unset on a fresh
        # bucket should be a no-op on the file (still present, still empty).
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            with open(os.path.join("config", "kb.yml")) as f:
                before = f.read()
            assert "agent_model" in before
            result = runner.invoke(main, ["config", "unset", "agent_model"])
            assert result.exit_code == 0
            with open(os.path.join("config", "kb.yml")) as f:
                after = f.read()
            assert "agent_model" in after

    def test_config_set_requires_key_and_value(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # No value: usage error.
            result = runner.invoke(main, ["config", "set", "agent_model"])
            assert result.exit_code == 2
            assert "Usage" in result.output

    def test_config_unset_unknown_key_is_silent(self):
        # Unsetting a key that was never set is a successful no-op so that
        # shell scripts can pipe through ``kb config unset`` without
        # branching on first-run.
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "config", "unset", "definitely_not_set",
            ])
            assert result.exit_code == 0


class TestFinetuneCommandInvocations:
    """Additional CLI invocation tests for ``kb finetune`` and ``kb models``.

    The integration phase covered the basic prepare/submit/list/use
    happy paths. These tests focus on invocation-level guarantees: the
    format flag flows through, the missing-dataset case is caught, the
    submit-only flags are required, the recorded job.json has the right
    hyperparams shape, and ``kb models list`` actually shows the active
    model's id (not just any model).
    """

    def _write_default_dataset(self):
        ds_dir = os.path.join(".kb", "training", "sft-dataset")
        os.makedirs(ds_dir, exist_ok=True)
        ds = os.path.join(ds_dir, "train.jsonl")
        with open(ds, "w") as f:
            f.write(
                '{"messages":[{"role":"user","content":"q"},'
                '{"role":"assistant","content":"a"}]}\n'
            )
        return ds

    def test_finetune_prepare_hf_format(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            self._write_default_dataset()
            out_dir = "out_hf"
            os.makedirs(out_dir)
            result = runner.invoke(main, [
                "finetune", "prepare",
                "--format", "hf",
                "--output", os.path.join(out_dir, "anything.jsonl"),
            ])
            assert result.exit_code == 0, result.output
            out_path = os.path.join(out_dir, "train.hf.jsonl")
            assert os.path.isfile(out_path), out_path
            with open(out_path) as f:
                rec = json.loads(f.readline())
            # HF format drops the underscore-prefixed metadata fields.
            assert "messages" in rec

    def test_finetune_prepare_missing_dataset_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            # No dataset written.
            result = runner.invoke(main, [
                "finetune", "prepare", "--format", "openai",
            ])
            assert result.exit_code == 1
            assert "dataset not found" in result.output

    def test_finetune_submit_requires_output_model_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            self._write_default_dataset()
            result = runner.invoke(main, [
                "finetune", "submit", "--base-model", "claude-opus-4-7",
            ])
            assert result.exit_code == 2
            assert "--output-model-id" in result.output

    def test_finetune_submit_records_hyperparams(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            self._write_default_dataset()
            result = runner.invoke(main, [
                "finetune", "submit",
                "--output-model-id", "kb-test-v1",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
                "--epochs", "5",
                "--lr", "1e-5",
                "--batch-size", "16",
                "--no-lora",
                "--notes", "second pass",
            ])
            assert result.exit_code == 0, result.output
            entries = os.listdir(os.path.join(".kb", "finetune"))
            assert len(entries) == 1
            with open(os.path.join(".kb", "finetune", entries[0], "job.json")) as f:
                job = json.load(f)
            assert job["hyperparams"]["n_epochs"] == 5
            assert job["hyperparams"]["lr"] == 1e-5
            assert job["hyperparams"]["batch_size"] == 16
            assert job["hyperparams"]["lora"] is False
            assert job["notes"] == "second pass"
            assert job["base_model"] == "claude-opus-4-7"

    def test_finetune_submit_rejects_unknown_backend(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            self._write_default_dataset()
            # Bypass Click's --backend Choice validation by patching the
            # function: the integration already covers the Choice guard.
            # We exercise the deeper ValueError inside finetune.submit.
            from kb import finetune as ft
            with patch.object(ft, "submit",
                              side_effect=ValueError("backend must be one of (...)")):
                result = runner.invoke(main, [
                    "finetune", "submit",
                    "--output-model-id", "kb-test-v1",
                    "--base-model", "claude-opus-4-7",
                ])
            # The CLI's --backend default is openai_ft, so the submit path
            # runs; the patched submit raises and CLI exits 1.
            assert result.exit_code == 1
            assert "backend" in result.output

    def test_models_list_marks_active_model(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-first",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            runner.invoke(main, [
                "models", "add", "kb-second",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
            ])
            runner.invoke(main, ["models", "use", "kb-second"])
            result = runner.invoke(main, ["models"])
            assert result.exit_code == 0
            # Active line must be present and identify the chosen one.
            assert "(active = kb-second)" in result.output
            assert "(active = kb-first)" not in result.output

    def test_models_list_tag_filter(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            runner.invoke(main, [
                "models", "add", "kb-rag",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
                "--tag-add", "rag",
            ])
            runner.invoke(main, [
                "models", "add", "kb-finetune",
                "--base-model", "claude-opus-4-7",
                "--backend", "openai_ft",
                "--tag-add", "ft",
            ])
            result = runner.invoke(main, ["models", "--tag", "rag"])
            assert result.exit_code == 0
            assert "kb-rag" in result.output
            assert "kb-finetune" not in result.output


# ---------------------------------------------------------------------------
# Phase 13.2: kb evaluate and kb health --models
# ---------------------------------------------------------------------------


def _write_analyzed_doc(root, ulid, *, body="doc body", title="t"):
    """Write a doc with an analysis block so the eval pipeline picks it up."""
    rel = shard_path(ulid)
    abs_dir = os.path.join(root, RECORDS_DIR, DOC_DIR, os.path.dirname(rel))
    os.makedirs(abs_dir, exist_ok=True)
    abs_path = os.path.join(root, RECORDS_DIR, DOC_DIR, rel)
    text = (
        f"---\nid: {ulid}\ntitle: {title}\nsource_type: web\n"
        f"analysis:\n  analyzer_version: analyzer_v1\n"
        f"  confidence: 0.8\n  importance: 0.5\n---\n\n{body}\n"
    )
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)
    return abs_path


def _patched_eval_agent(side_effect_json):
    """Mock kb.evaluate.call_agent to return a canned JSON string.

    The canned response must satisfy parse_analysis_response: title, summary,
    key_points, primary_concepts (with id/label), candidate_concepts,
    display_tags, entities, confidence, importance.
    """
    return patch("kb.evaluate.call_agent", side_effect=side_effect_json)


def _canned_eval_response(prompt):
    """Default canned response for evaluate tests; importance=0.5."""
    return json.dumps({
        "title": "x", "summary": "a summary",
        "why_important": "x", "key_points": [],
        "primary_concepts": [{"id": "rag", "label": "rag"}],
        "candidate_concepts": [],
        "display_tags": [], "entities": [],
        "confidence": 0.9, "importance": 0.5,
    })


class TestEvaluateCLI:
    def test_evaluate_requires_init(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, [
                "evaluate", "--baseline", "a", "--candidate", "b",
            ])
            assert result.exit_code == 1
            assert "Not in a knowledge bucket" in result.output

    def test_evaluate_json_with_mocks(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        # Add two analyzed docs so the pipeline picks them up.
        for ulid in ("01HEVAL00000000000000AAAA",
                     "01HEVAL00000000000000BBBB"):
            _write_analyzed_doc(root, ulid)

        with _patched_eval_agent(_canned_eval_response):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 2, "5": 0},
                    "judge_failures": 0,
                    "judge_per_doc": [
                        {"doc_id": "01HEVAL00000000000000AAAA",
                         "score": 4, "reasoning": "ok"},
                        {"doc_id": "01HEVAL00000000000000BBBB",
                         "score": 4, "reasoning": "ok"},
                    ],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                result = runner.invoke(main, [
                    "evaluate",
                    "--baseline", "base-x",
                    "--candidate", "cand-x",
                    "--json",
                ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["baseline"] == "base-x"
        assert data["candidate"] == "cand-x"
        m = data["metrics"]
        for k in ("concept_jaccard_mean", "concept_f1_mean",
                  "importance_kl", "baseline_failure_rate",
                  "candidate_failure_rate"):
            assert k in m, f"missing metric: {k}"

    def test_evaluate_text_summary(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        _write_analyzed_doc(root, "01HEVAL00000000000000CCCC")

        with _patched_eval_agent(_canned_eval_response):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 3.0, "judge_score_median": 3,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 1, "4": 0, "5": 0},
                    "judge_failures": 0, "judge_per_doc": [],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                result = runner.invoke(main, [
                    "evaluate", "--baseline", "b1", "--candidate", "c1",
                ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        # Text summary must contain the headline metrics and the report path.
        assert "Docs evaluated:" in result.output
        assert "concept_jaccard_mean" in result.output
        assert "Report saved: .kb/models/eval/c1.json" in result.output

    def test_evaluate_persists_report_file(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        _write_analyzed_doc(root, "01HEVAL00000000000000DDDD")

        with _patched_eval_agent(_canned_eval_response):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0},
                    "judge_failures": 0, "judge_per_doc": [],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                result = runner.invoke(main, [
                    "evaluate", "--baseline", "b2", "--candidate", "c2",
                    "--json",
                ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        eval_path = os.path.join(root, ".kb", "models", "eval", "c2.json")
        assert os.path.isfile(eval_path)
        with open(eval_path, encoding="utf-8") as f:
            stored = json.load(f)
        assert stored["model_id"] == "c2"
        assert stored["baseline"] == "b2"
        assert "metrics" in stored

    def test_evaluate_no_cache_passes_through(self, tmp_path, monkeypatch):
        """The --no-cache flag should reach run_eval as use_cache=False."""
        root = str(tmp_path)
        monkeypatch.chdir(root)
        _write_analyzed_doc(root, "01HEVAL00000000000000EEEE")

        with _patched_eval_agent(_canned_eval_response):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0},
                    "judge_failures": 0, "judge_per_doc": [],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                result = runner.invoke(main, [
                    "evaluate", "--baseline", "b3", "--candidate", "c3",
                    "--no-cache", "--json",
                ], catch_exceptions=False)

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["cache_used"] is False


class TestHealthModelsFlag:
    def test_health_models_flag_outside_bucket_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["health", "--models"])
            assert result.exit_code == 1
            assert "Not in a knowledge bucket" in result.output

    def test_health_models_json_emits_model_evals_key(self, tmp_path,
                                                      monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        # Build a minimal index so compute_health has something to read.
        conn = init_db(index_path(root))
        index_document(conn, "doc1", "Doc1", None, "web", "r/doc1.md", "x")
        conn.close()

        # Build a fake eval report on disk.
        eval_dir = os.path.join(root, ".kb", "models", "eval")
        os.makedirs(eval_dir, exist_ok=True)
        with open(os.path.join(eval_dir, "cand-x.json"), "w") as f:
            json.dump({
                "model_id": "cand-x",
                "baseline": "base-x",
                "judged_at": "2026-06-15T12:00:00Z",
                "n_docs": 5,
                "metrics": {
                    "concept_jaccard_mean": 0.7,
                    "concept_f1_mean": 0.8,
                    "importance_kl": 0.05,
                    "judge_score_mean": 4.0,
                },
            }, f)

        runner = CliRunner()
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, ["health", "--models", "--json"],
                               catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "model_evals" in data
        assert len(data["model_evals"]) == 1
        assert data["model_evals"][0]["model_id"] == "cand-x"
        m = data["model_evals"][0]["metrics"]
        assert m["concept_jaccard_mean"] == 0.7
        assert m["concept_f1_mean"] == 0.8

    def test_health_models_text_summary(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        conn = init_db(index_path(root))
        index_document(conn, "doc1", "Doc1", None, "web", "r/doc1.md", "x")
        conn.close()
        eval_dir = os.path.join(root, ".kb", "models", "eval")
        os.makedirs(eval_dir, exist_ok=True)
        with open(os.path.join(eval_dir, "cand-z.json"), "w") as f:
            json.dump({
                "model_id": "cand-z",
                "baseline": "base-z",
                "judged_at": "2026-06-15T13:00:00Z",
                "n_docs": 3,
                "metrics": {
                    "concept_jaccard_mean": 0.5,
                    "concept_f1_mean": 0.6,
                    "importance_kl": 0.1,
                    "judge_score_mean": 3.5,
                },
            }, f)

        runner = CliRunner()
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, ["health", "--models"],
                               catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "Model Eval Scores" in result.output
        assert "cand-z" in result.output
        assert "base-z" in result.output

    def test_health_models_text_no_records(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        conn = init_db(index_path(root))
        index_document(conn, "doc1", "Doc1", None, "web", "r/doc1.md", "x")
        conn.close()

        runner = CliRunner()
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, ["health", "--models"],
                               catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "no eval reports found" in result.output


class TestModelsShowEvalScores:
    def test_models_show_eval_block_when_present(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        registry.add("kb-rag-v1", base_model="claude-opus-4-7",
                     dataset_path="d", backend="openai_ft", root=root)
        eval_dir = os.path.join(root, ".kb", "models", "eval")
        os.makedirs(eval_dir, exist_ok=True)
        with open(os.path.join(eval_dir, "kb-rag-v1.json"), "w") as f:
            json.dump({
                "model_id": "kb-rag-v1",
                "baseline": "opus-45",
                "judged_at": "2026-06-15T12:00:00Z",
                "n_docs": 7,
                "metrics": {
                    "concept_jaccard_mean": 0.6,
                    "concept_f1_mean": 0.7,
                    "importance_kl": 0.04,
                    "judge_score_mean": 3.8,
                },
            }, f)

        runner = CliRunner()
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, ["models", "show", "kb-rag-v1"],
                               catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "--- eval scores ---" in result.output
        assert "concept_jaccard_mean: 0.6" in result.output
        assert "judge_score_mean:     3.8" in result.output
        assert "baseline:  opus-45" in result.output

    def test_models_show_json_includes_eval_when_present(self, tmp_path,
                                                         monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        registry.add("kb-rag-v2", base_model="claude-opus-4-7",
                     dataset_path="d", backend="openai_ft", root=root)
        eval_dir = os.path.join(root, ".kb", "models", "eval")
        os.makedirs(eval_dir, exist_ok=True)
        with open(os.path.join(eval_dir, "kb-rag-v2.json"), "w") as f:
            json.dump({
                "model_id": "kb-rag-v2",
                "baseline": "opus-45",
                "judged_at": "2026-06-15T12:00:00Z",
                "n_docs": 2,
                "metrics": {"concept_jaccard_mean": 0.5},
            }, f)

        runner = CliRunner()
        runner.invoke(main, ["init", "."])
        result = runner.invoke(main, ["models", "show", "kb-rag-v2", "--json"],
                               catch_exceptions=False)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["model"]["id"] == "kb-rag-v2"
        assert "eval" in data
        assert data["eval"]["model_id"] == "kb-rag-v2"


# ---------------------------------------------------------------------------
# Phase 13.2 follow-up: kb evaluate extra CLI surface
# ---------------------------------------------------------------------------


class TestEvaluateRequiredFlags:
    def test_evaluate_requires_baseline(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["evaluate", "--candidate", "b"])
            assert result.exit_code == 2  # click missing-option
            assert "--baseline" in result.output

    def test_evaluate_requires_candidate(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, ["evaluate", "--baseline", "a"])
            assert result.exit_code == 2
            assert "--candidate" in result.output

    def test_evaluate_missing_reference_file_errors(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            runner.invoke(main, ["init", "."])
            result = runner.invoke(main, [
                "evaluate",
                "--baseline", "base-x",
                "--candidate", "cand-x",
                "--reference", "/no/such/file.jsonl",
            ])
            # Click validates `exists=True` and exits 2 with usage error.
            assert result.exit_code == 2
            assert "reference" in result.output.lower() or "FILE" in result.output


class TestEvaluateCachingBehavior:
    """Caching guarantees for the ``kb evaluate`` CLI path.

    The first invocation should call ``call_agent`` for each (model, doc)
    pair; the second invocation, given an identical CLI, must be served
    entirely from the on-disk cache at ``.kb/models/eval/cache/<model>/``.
    """

    def _two_docs_setup(self, tmp_path, monkeypatch):
        root = str(tmp_path)
        monkeypatch.chdir(root)
        _write_analyzed_doc(root, "01HEVAL0000000000000CACHE1")
        _write_analyzed_doc(root, "01HEVAL0000000000000CACHE2")

    def test_evaluate_second_invocation_uses_cache(self, tmp_path,
                                                    monkeypatch):
        self._two_docs_setup(tmp_path, monkeypatch)

        def _cached_canned(*args, **kwargs):
            # Accept (prompt, model=...) signature from call_agent.
            return _canned_eval_response(args[0] if args else "")

        # First run — populates cache, no pre-existing cache files.
        with patch("kb.evaluate.call_agent", side_effect=_cached_canned):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 2, "5": 0},
                    "judge_failures": 0,
                    "judge_per_doc": [],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                first = runner.invoke(main, [
                    "evaluate", "--baseline", "cache-base",
                    "--candidate", "cache-cand", "--json",
                ], catch_exceptions=False)
        assert first.exit_code == 0, first.output

        cache_dir = os.path.join(
            str(tmp_path), ".kb", "models", "eval", "cache",
        )
        # Both models have a cache subdir after the first run.
        assert os.path.isdir(os.path.join(cache_dir, "cache-base"))
        assert os.path.isdir(os.path.join(cache_dir, "cache-cand"))

        # Second run — patch call_agent to raise; the cache should
        # bypass it entirely.  (The judge is still mocked, but the
        # analyze path is the one we're proving is cached.)
        def _boom(*args, **kwargs):
            raise AssertionError("call_agent was called; cache miss!")

        with patch("kb.evaluate.call_agent", side_effect=_boom):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 2, "5": 0},
                    "judge_failures": 0, "judge_per_doc": [],
                },
            ):
                second = runner.invoke(main, [
                    "evaluate", "--baseline", "cache-base",
                    "--candidate", "cache-cand", "--json",
                ], catch_exceptions=False)
        assert second.exit_code == 0, second.output
        data = json.loads(second.output)
        assert data["cache_used"] is True
        # Two docs found, both pairs survived the cached replay.
        assert data["n_docs"] == 2

    def test_evaluate_no_cache_flag_bypasses_cache(self, tmp_path,
                                                    monkeypatch):
        self._two_docs_setup(tmp_path, monkeypatch)

        call_count = {"n": 0}

        def _counting_agent(*args, **kwargs):
            call_count["n"] += 1
            return _canned_eval_response(args[0] if args else "")

        # First run with --no-cache to count calls; then run again with
        # the same flag to confirm call_agent fires both times.
        with patch("kb.evaluate.call_agent", side_effect=_counting_agent):
            with patch(
                "kb.evaluate._compute_judge_scores",
                return_value={
                    "judge_score_mean": 4.0, "judge_score_median": 4,
                    "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0},
                    "judge_failures": 0, "judge_per_doc": [],
                },
            ):
                runner = CliRunner()
                runner.invoke(main, ["init", "."])
                first = runner.invoke(main, [
                    "evaluate", "--baseline", "nc-base",
                    "--candidate", "nc-cand",
                    "--no-cache", "--json",
                ], catch_exceptions=False)
                second = runner.invoke(main, [
                    "evaluate", "--baseline", "nc-base",
                    "--candidate", "nc-cand",
                    "--no-cache", "--json",
                ], catch_exceptions=False)
        assert first.exit_code == 0, first.output
        assert second.exit_code == 0, second.output
        first_data = json.loads(first.output)
        second_data = json.loads(second.output)
        assert first_data["cache_used"] is False
        assert second_data["cache_used"] is False
        # Two docs * two models per run * two runs = 8 calls minimum.
        assert call_count["n"] >= 8


# (no extra imports needed at the bottom — see top-of-file imports)
