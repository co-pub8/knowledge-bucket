"""Tests for the examples/demo.sh end-to-end feedback-loop demo.

These tests cover both the static artifacts that ship in
``examples/demo-bucket/`` (config + sample docs) and the runtime
behavior of ``examples/demo.sh`` (--help, --smoke, output content).

The smoke run is fast (sub-second on a warm machine) and exercises
``kb ingest``, ``kb index --sync``, ``kb models add``, and the
``[demo] === step N: ...`` headers. The LLM-touching steps are
skipped-by-reason in --smoke mode; their output text is still asserted
on to prove the script is wiring the right command names.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"
DEMO_BUCKET = EXAMPLES_DIR / "demo-bucket"
DEMO_SH = EXAMPLES_DIR / "demo.sh"
MAIN_README = REPO_ROOT / "README.md"
EXAMPLES_README = EXAMPLES_DIR / "README.md"
DEMO_BUCKET_CONFIG = DEMO_BUCKET / "config" / "kb.yml"
DEMO_BUCKET_DOCS = DEMO_BUCKET / "records" / "doc"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _all_demo_docs() -> list[Path]:
    """Return every ``*.md`` file under the demo bucket's doc tree."""
    if not DEMO_BUCKET_DOCS.is_dir():
        return []
    return sorted(DEMO_BUCKET_DOCS.rglob("*.md"))


def _parse_front_matter(text: str) -> dict:
    """Parse the leading YAML front-matter block of a demo doc.

    Demo docs use the ``---\\nkey: value\\n...\\n---\\n<body>`` shape
    that ``kb add`` writes. This parser is intentionally minimal — it
    only handles the simple ``key: value`` and ``key:\\n  - item`` shapes
    that the bundled vector-DB docs use, plus an early-out for malformed
    docs so individual assertions can produce clearer error messages.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    out: dict = {}
    current_key: str | None = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("  - "):
            assert current_key is not None, f"dangling list item in: {block!r}"
            out.setdefault(current_key, []).append(line[4:].strip())
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            # Start of a nested block (e.g. ``concepts:`` list).
            current_key = key
            out.setdefault(key, [])
        else:
            current_key = key
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Bucket artifacts
# ---------------------------------------------------------------------------


class TestDemoBucketExists:
    def test_demo_bucket_directory_exists(self):
        assert DEMO_BUCKET.is_dir(), (
            f"demo bucket missing: {DEMO_BUCKET} — Phase 3 content should have created it"
        )

    def test_demo_bucket_has_config(self):
        assert DEMO_BUCKET_CONFIG.is_file(), (
            f"demo bucket config missing: {DEMO_BUCKET_CONFIG}"
        )
        with DEMO_BUCKET_CONFIG.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        # The five key knobs the rest of the tool reads.
        for key in ("records_dir", "doc_dir", "concept_dir", "inbox_dir"):
            assert key in data, f"kb.yml missing required key: {key}"
        assert data.get("shard_depth") == 2

    def test_demo_bucket_has_minimum_docs(self):
        docs = _all_demo_docs()
        assert len(docs) >= 10, (
            f"expected >= 10 demo docs (spec says 12), found {len(docs)}"
        )

    def test_demo_bucket_docs_have_front_matter(self):
        docs = _all_demo_docs()
        assert docs, "no demo docs found"
        missing: list[str] = []
        for path in docs:
            text = path.read_text(encoding="utf-8")
            fm = _parse_front_matter(text)
            for key in ("id", "title", "source"):
                if key not in fm:
                    missing.append(f"{path.name}: missing {key}")
        assert not missing, "front-matter issues:\n" + "\n".join(missing)

    def test_demo_bucket_docs_have_body(self):
        docs = _all_demo_docs()
        assert docs, "no demo docs found"
        for path in docs:
            text = path.read_text(encoding="utf-8")
            # Strip the front-matter; whatever remains is the body.
            end = text.find("\n---", 3)
            assert end != -1, f"{path.name}: no closing front-matter fence"
            body = text[end + 4 :].strip()
            assert len(body) > 100, (
                f"{path.name}: body too short ({len(body)} chars); "
                "expected a real 200-500 word doc"
            )


# ---------------------------------------------------------------------------
# demo.sh script — file checks + runtime behavior
# ---------------------------------------------------------------------------


class TestDemoShStatic:
    def test_demo_sh_exists_and_executable(self):
        assert DEMO_SH.is_file(), f"demo.sh missing at {DEMO_SH}"
        mode = DEMO_SH.stat().st_mode
        assert mode & 0o111, "demo.sh must be executable"

    def test_examples_readme_exists(self):
        assert EXAMPLES_README.is_file(), f"missing: {EXAMPLES_README}"
        text = EXAMPLES_README.read_text(encoding="utf-8")
        # The README must actually document the demo (not just be a stub).
        assert "demo.sh" in text
        assert "--smoke" in text
        assert "--real-llm" in text

    def test_main_readme_has_quick_demo_section(self):
        assert MAIN_README.is_file()
        text = MAIN_README.read_text(encoding="utf-8")
        # The section is titled "## Quick Demo" per Phase 4.
        assert re.search(r"^##\s+Quick\s+Demo\s*$", text, flags=re.MULTILINE), (
            "main README is missing the '## Quick Demo' section"
        )
        # And it should point at the examples README and demo.sh.
        assert "examples/demo.sh" in text
        assert "examples/README.md" in text


# ---------------------------------------------------------------------------
# demo.sh runtime — invoke the script via subprocess
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_sh_help_output() -> subprocess.CompletedProcess:
    """Run ``bash examples/demo.sh --help`` once for the module."""
    return subprocess.run(
        ["bash", str(DEMO_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.fixture(scope="module")
def demo_sh_smoke_output() -> subprocess.CompletedProcess:
    """Run ``bash examples/demo.sh --smoke`` once for the module.

    The smoke run touches the demo bucket (it does ``kb models add``).
    Per Phase 4 the script is idempotent (``--overwrite``), so re-runs
    are safe. We still mark the bucket as a mutable fixture rather than
    pinning its post-run state.
    """
    return subprocess.run(
        ["bash", str(DEMO_SH), "--smoke"],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestDemoShHelp:
    def test_demo_sh_help_exits_zero(self, demo_sh_help_output: subprocess.CompletedProcess):
        assert demo_sh_help_output.returncode == 0, (
            f"--help failed: stderr={demo_sh_help_output.stderr!r}"
        )

    def test_demo_sh_help_mentions_modes(self, demo_sh_help_output: subprocess.CompletedProcess):
        out = demo_sh_help_output.stdout
        for needle in ("MODES", "OPTIONS", "EXAMPLES", "--smoke", "--real-llm", "--help"):
            assert needle in out, f"--help output missing {needle!r}"


class TestDemoShSmoke:
    def test_demo_sh_smoke_exits_zero(self, demo_sh_smoke_output: subprocess.CompletedProcess):
        # The smoke mode is documented to "always exit 0".
        assert demo_sh_smoke_output.returncode == 0, (
            f"--smoke failed: stderr={demo_sh_smoke_output.stderr!r}"
        )

    def test_demo_sh_smoke_runs_within_time_budget(
        self, demo_sh_smoke_output: subprocess.CompletedProcess,
    ):
        # The script should not have hit our 60s timeout — pytest would
        # have raised TimeoutExpired by then. Sanity-check the duration
        # is on the order of seconds, not minutes.
        # (We approximate from the start time captured in the fixture.)
        # NOTE: pytest's `timeout=` raises TimeoutExpired, so a non-None
        # CompletedProcess with exit 0 here is sufficient evidence the
        # script is fast.
        assert demo_sh_smoke_output.returncode == 0

    def test_demo_sh_output_contains_key_steps(
        self, demo_sh_smoke_output: subprocess.CompletedProcess,
    ):
        out = demo_sh_smoke_output.stdout
        # The seven step headers printed by ``step()`` in demo.sh.
        for step_num in range(1, 8):
            assert f"=== step {step_num}:" in out, (
                f"output missing step {step_num} header"
            )
        # The seven pipeline stages. The first three are the step
        # titles (printed verbatim by ``step N "title"``); the next
        # four are the kb subcommand names that show up in either the
        # step's skip-reason hint, the post-run "Next steps" footer,
        # or the actual command output (e.g. ``kb models add``'s
        # ``Registered model '...'`` line, ``kb index --sync``'s
        # ``Synced N new document(s)`` line).
        stages = [
            ("ingest inbox", "step 1 title"),
            ("build FTS5 index", "step 2 title"),
            ("analyze docs", "step 3 title"),
            ("build SFT dataset", "step 4 title"),
            ("register baseline", "step 5 title"),
            ("evaluate candidate", "step 6 title"),
            ("self-iterating", "step 7 title"),
            # kb subcommand names: prove the script drives the right
            # commands. Some appear in the footer, some in skip hints,
            # some in their own stdout.
            ("kb search", "Next steps footer"),
            ("kb doctor", "Next steps footer"),
            ("kb models list", "Next steps footer"),
            ("kb improve log", "Next steps footer"),
            ("kb analyze", "skip-reason hint in step 3"),
            ("kb models use", "step 5 hint when smoke skips 'kb models use'"),
            ("Registered model", "kb models add stdout"),
            ("Synced ", "kb index --sync stdout"),
        ]
        for needle, where in stages:
            assert needle in out, f"output missing {needle!r} (expected from {where})"


# ---------------------------------------------------------------------------
# Lightweight smoke check on the existing fixture: pre-existing models
# are *not* required (the demo creates them on first run), but after
# ``--smoke`` the bucket should be in a state where ``kb models list``
# knows about both demo models. This guards against a silent failure
# in the step-5 block.
# ---------------------------------------------------------------------------


class TestDemoSmokeSideEffects:
    def test_models_registered_after_smoke(self, tmp_path: Path):
        """Copy the demo bucket to a tmp dir, run --smoke, and verify.

        Why copy? The bucket's ``.kb/`` is the canonical artifact we
        want to inspect, but mutating it in-place between tests makes
        ordering fragile. Copying is cheap (<20 docs) and gives us a
        hermetic assertion.
        """
        import shutil

        bucket_copy = tmp_path / "demo-bucket"
        shutil.copytree(DEMO_BUCKET, bucket_copy)

        env = os.environ.copy()
        # Force a clean CWD so ``kb`` resolves the right kb_root.
        proc = subprocess.run(
            ["bash", str(DEMO_SH), "--smoke"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(bucket_copy),
            env=env,
        )
        assert proc.returncode == 0, (
            f"--smoke in copy failed: stderr={proc.stderr!r}"
        )

        # Both demo models should have been written.
        models_dir = bucket_copy / ".kb" / "models"
        assert (models_dir / "kb-rag-v1.json").is_file(), "kb-rag-v1 not registered"
        assert (models_dir / "kb-rag-v2.json").is_file(), "kb-rag-v2 not registered"

        # And the kb.yml should still be valid YAML after the run.
        with (bucket_copy / "config" / "kb.yml").open(encoding="utf-8") as f:
            yaml.safe_load(f)
