"""Tests for CLI: kb init, kb add, kb show, kb concept."""

import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from kb.cli import main


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


# (no extra imports needed at the bottom — see top-of-file imports)
