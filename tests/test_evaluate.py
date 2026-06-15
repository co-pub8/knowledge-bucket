"""Tests for the evaluation harness (evaluate.py)."""

import json
import math
import os
from unittest.mock import patch

from kb import evaluate as ev
from kb.analyzer import AnalysisResult, ConceptRef

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _result(concepts: list[str], *, importance: float = 0.5,
            summary: str = "a summary") -> AnalysisResult:
    """Build an AnalysisResult with a primary concept list for testing."""
    return AnalysisResult(
        summary=summary,
        importance=importance,
        primary_concepts=[ConceptRef(id=c, label=c) for c in concepts],
        candidate_concepts=[],
    )


def _result_with_candidates(primary: list[str], candidates: list[str],
                            *, importance: float = 0.5,
                            summary: str = "a summary") -> AnalysisResult:
    """Build an AnalysisResult with both primary and candidate concepts."""
    return AnalysisResult(
        summary=summary,
        importance=importance,
        primary_concepts=[ConceptRef(id=c, label=c) for c in primary],
        candidate_concepts=[ConceptRef(id=c, label=c) for c in candidates],
    )


def _init_kb(root: str) -> None:
    """Create the directory layout the eval module needs."""
    from kb.core import ensure_dirs
    ensure_dirs(root)


def _write_doc(root: str, ulid: str, *, body: str = "body",
               with_analysis: bool = True) -> str:
    """Write a stub doc under records/doc/ with optional analysis block."""
    from kb.core import shard_path
    rel = shard_path(ulid, depth=2)
    abs_path = os.path.join(root, "records", "doc", rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    analysis_block = ""
    if with_analysis:
        analysis_block = (
            "analysis:\n  analyzer_version: analyzer_v1\n"
            "  confidence: 0.8\n  importance: 0.5\n"
        )
    text = (
        f"---\nid: {ulid}\ntitle: t{ulid}\nsource_type: web\n"
        f"{analysis_block}---\n\n{body}\n"
    )
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(text)
    return abs_path


# ---------------------------------------------------------------------------
# Metric 1: Jaccard / F1
# ---------------------------------------------------------------------------

class TestConceptJaccardF1:
    def test_jaccard_identical_sets(self):
        a = _result(["a", "b", "c"])
        b = _result(["a", "b", "c"])
        rec = ev._per_doc_jaccard_f1("d1", a, b)
        assert rec["jaccard"] == 1.0
        assert rec["f1"] == 1.0
        assert rec["precision"] == 1.0
        assert rec["recall"] == 1.0

    def test_jaccard_disjoint(self):
        a = _result(["a", "b"])
        b = _result(["c", "d"])
        rec = ev._per_doc_jaccard_f1("d1", a, b)
        assert rec["jaccard"] == 0.0
        assert rec["f1"] == 0.0
        assert rec["precision"] == 0.0
        assert rec["recall"] == 0.0

    def test_jaccard_subset(self):
        # A = {a, b}, B = {a, b, c} — candidate is a superset.
        a = _result(["a", "b"])
        b = _result(["a", "b", "c"])
        rec = ev._per_doc_jaccard_f1("d1", a, b)
        # inter = {a,b} (2), union = {a,b,c} (3) → jaccard = 2/3
        assert math.isclose(rec["jaccard"], 2 / 3)
        # precision = 2/3, recall = 1.0 → f1 = 2*(2/3)*1 / (2/3 + 1) = 0.8
        assert math.isclose(rec["f1"], 0.8)
        assert math.isclose(rec["precision"], 2 / 3)
        assert rec["recall"] == 1.0

    def test_jaccard_both_empty(self):
        a = _result([])
        b = _result([])
        rec = ev._per_doc_jaccard_f1("d1", a, b)
        assert rec["jaccard"] == 1.0  # both empty = perfect match

    def test_compute_concept_metrics_aggregates_means(self):
        # Three pairs: identical, disjoint, subset.
        pairs = [
            ("d1", _result(["a", "b"]), _result(["a", "b"])),
            ("d2", _result(["a", "b"]), _result(["c", "d"])),
            ("d3", _result(["a", "b"]), _result(["a", "b", "c"])),
        ]
        m = ev._compute_concept_metrics(pairs)
        assert m["per_doc"] and len(m["per_doc"]) == 3
        # Identical: jaccard=1, f1=1; disjoint: 0,0; subset: 2/3, 0.8
        assert math.isclose(m["concept_jaccard_mean"], (1 + 0 + 2 / 3) / 3)
        assert math.isclose(m["concept_f1_mean"], (1 + 0 + 0.8) / 3)


# ---------------------------------------------------------------------------
# Metric 2: Importance KL
# ---------------------------------------------------------------------------

class TestImportanceKL:
    def test_identical_distributions(self):
        a = [_result(["x"], importance=v) for v in (0.1, 0.3, 0.7)]
        b = [_result(["x"], importance=v) for v in (0.2, 0.4, 0.6)]
        out = ev._compute_importance_kl(a, b)
        # Two PMFs built from the same data shape; not necessarily identical
        # bucket counts but should be close.
        assert out["importance_kl"] >= 0.0
        assert 0.0 <= out["importance_js"] <= math.log(2) + 1e-9
        assert len(out["importance_histogram_baseline"]) == ev._IMPORTANCE_BINS
        assert len(out["importance_histogram_candidate"]) == ev._IMPORTANCE_BINS

    def test_different_distributions(self):
        a = [_result(["x"], importance=0.05), _result(["x"], importance=0.05)]
        b = [_result(["x"], importance=0.95), _result(["x"], importance=0.95)]
        out = ev._compute_importance_kl(a, b)
        # Heavily mass in opposite ends → KL must be > 0.
        assert out["importance_kl"] > 0.0
        assert out["importance_js"] > 0.0

    def test_histogram_to_pmf_uniform_when_empty(self):
        pmf = ev._histogram_to_pmf([0, 0, 0])
        assert all(math.isclose(x, 1 / 3, rel_tol=1e-9) for x in pmf)


# ---------------------------------------------------------------------------
# Metric 4: Failure detection
# ---------------------------------------------------------------------------

class TestFailureRates:
    def test_failure_detection_empty_summary(self):
        r = AnalysisResult(summary="", importance=0.5,
                           primary_concepts=[ConceptRef(id="x", label="x")])
        assert ev._is_failure(r)
        assert ev._failure_reason(r) == "empty summary"

    def test_failure_detection_importance_out_of_range(self):
        r = AnalysisResult(summary="ok", importance=1.5,
                           primary_concepts=[ConceptRef(id="x", label="x")])
        assert ev._is_failure(r)
        assert "importance" in ev._failure_reason(r)

    def test_failure_detection_no_concepts(self):
        r = AnalysisResult(summary="ok", importance=0.5)
        assert ev._is_failure(r)
        assert "concept" in ev._failure_reason(r)

    def test_failure_detection_healthy(self):
        r = AnalysisResult(summary="ok", importance=0.5,
                           primary_concepts=[ConceptRef(id="x", label="x")])
        assert not ev._is_failure(r)

    def test_failure_rates_delta(self):
        # Baseline: 1 of 2 failed. Candidate: 0 of 2 failed.
        baseline = [
            ("d1", _result(["a"])),  # ok
            ("d2", _result(["a"], summary="")),  # failed (empty summary)
        ]
        candidate = [
            ("d1", _result(["a"])),
            ("d2", _result(["a"])),
        ]
        rates = ev._compute_failure_rates(list(zip(
            [d for d, _ in baseline],
            [b for _d, b in baseline],
            [c for _d, c in candidate],
        )))
        assert rates["baseline_failure_rate"] == 0.5
        assert rates["candidate_failure_rate"] == 0.0
        assert rates["failure_rate_delta"] == -0.5
        assert any(f["doc_id"] == "d2" and f["model"] == "baseline"
                   for f in rates["failures"])


# ---------------------------------------------------------------------------
# Metric 5: Reference
# ---------------------------------------------------------------------------

class TestReferenceMetrics:
    def test_reference_accuracy_and_f1(self, tmp_path):
        ref_path = tmp_path / "ref.jsonl"
        ref_path.write_text(
            json.dumps({"doc_id": "d1", "expected_concepts": ["a", "b"]}) + "\n"
            + json.dumps({"doc_id": "d2", "expected_concepts": ["a"]}) + "\n"
        )
        pairs = [
            # d1: exact match → correct, f1 = 1.0
            ("d1", _result(["a", "b"]), _result(["a", "b"])),
            # d2: partial overlap with expected {a}; candidate = {a, c}
            ("d2", _result(["a", "b"]), _result(["a", "c"])),
        ]
        m = ev._compute_reference_metrics(pairs, str(ref_path))
        assert m["reference_accuracy"] == 0.5  # 1 of 2 exact
        # f1 for d2: pred={a,c}, expected={a}; inter={a}; p=1/2, r=1 → 2/3
        assert math.isclose(m["reference_macro_f1"], (1.0 + 2 / 3) / 2)
        assert m["reference_n_matched"] == 2
        assert m["reference_n_skipped"] == 0

    def test_reference_skips_missing_docs(self, tmp_path):
        ref_path = tmp_path / "ref.jsonl"
        ref_path.write_text(
            json.dumps({"doc_id": "d1", "expected_concepts": ["a"]}) + "\n"
        )
        pairs = [
            ("d1", _result(["a"]), _result(["a"])),
            ("d2", _result(["a"]), _result(["a"])),  # not in reference
        ]
        m = ev._compute_reference_metrics(pairs, str(ref_path))
        assert m["reference_n_matched"] == 1
        assert m["reference_n_skipped"] == 1
        assert m["reference_accuracy"] == 1.0  # only d1 considered


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

class TestJudgePrompt:
    def test_judge_prompt_loads_via_importlib_resources(self):
        # Should be readable via the package; raise FileNotFoundError if missing.
        text = ev.load_prompt(ev.JUDGE_PROMPT_FILE)
        assert "Rubric" in text
        assert "JSON" in text or "json" in text

    def test_build_judge_prompt_substitutes_fields(self):
        body = "the source text"
        base = "baseline summary"
        cand = "candidate summary"
        prompt = ev.build_judge_prompt(body, base, cand)
        assert body in prompt
        assert base in prompt
        assert cand in prompt
        # Make sure the placeholders themselves are gone.
        assert "<DOCUMENT_BODY>" not in prompt
        assert "<BASELINE_SUMMARY>" not in prompt
        assert "<CANDIDATE_SUMMARY>" not in prompt
        # Should truncate very long bodies.
        long_prompt = ev.build_judge_prompt("x" * 10000, "b", "c")
        assert len(long_prompt) < len("x" * 10000) + 5000


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

class TestCaching:
    def test_analyze_with_model_caches_results(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _write_doc(root, "01HEVALTEST000000000000000")
        _write_doc(root, "01HEVALTEST000000000000001")

        # Mock call_agent to return a canned analysis JSON.
        canned = json.dumps({
            "title": "t", "summary": "ok", "why_important": "x",
            "key_points": [],
            "primary_concepts": [{"id": "rag", "label": "rag"}],
            "candidate_concepts": [],
            "display_tags": [], "entities": [],
            "confidence": 0.9, "importance": 0.5,
        })
        with patch("kb.evaluate.call_agent", return_value=canned) as mock_agent:
            docs = ev.discover_analyzed_docs(root)
            first = ev._analyze_docs_with_model(root, "m", docs, use_cache=True)
            n_first = mock_agent.call_count
        assert n_first == len(docs)
        # Second pass: cache hits, no agent calls.
        with patch("kb.evaluate.call_agent", return_value=canned) as mock_agent2:
            second = ev._analyze_docs_with_model(root, "m", docs, use_cache=True)
            assert mock_agent2.call_count == 0
        # Same doc_id keys, same importance values.
        assert set(first.keys()) == set(second.keys())
        for doc_id in first:
            assert first[doc_id].importance == second[doc_id].importance

    def test_no_cache_forces_rerun(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _write_doc(root, "01HEVALTEST000000000000002")

        canned = json.dumps({
            "title": "t", "summary": "ok", "why_important": "x",
            "key_points": [],
            "primary_concepts": [{"id": "rag", "label": "rag"}],
            "candidate_concepts": [], "display_tags": [], "entities": [],
            "confidence": 0.9, "importance": 0.5,
        })
        docs = ev.discover_analyzed_docs(root)
        with patch("kb.evaluate.call_agent", return_value=canned) as m1:
            ev._analyze_docs_with_model(root, "m", docs, use_cache=False)
        with patch("kb.evaluate.call_agent", return_value=canned) as m2:
            ev._analyze_docs_with_model(root, "m", docs, use_cache=False)
        assert m1.call_count == len(docs)
        assert m2.call_count == len(docs)  # rerun because no cache


# ---------------------------------------------------------------------------
# Public run_eval
# ---------------------------------------------------------------------------

class TestRunEval:
    def _patched_agent(self, importance_values: dict[str, float] | None = None,
                       summary: str = "ok"):
        """Return a context manager that mocks call_agent with a canned response.

        The mocked call_agent inspects the doc body (or doc id) to pick an
        importance value when a mapping is provided. Otherwise it returns a
        constant response.
        """
        import re as _re

        def _make_response(prompt: str) -> str:
            m = _re.search(r"^Title:\s*(\S+)", prompt, _re.MULTILINE)
            title = m.group(1) if m else ""
            imp = 0.5
            if importance_values and title:
                # Title seeds the doc id suffix; match by substring.
                for k, v in importance_values.items():
                    if k in title:
                        imp = v
                        break
            return json.dumps({
                "title": title or "x", "summary": summary,
                "why_important": "x", "key_points": [],
                "primary_concepts": [{"id": "rag", "label": "rag"}],
                "candidate_concepts": [],
                "display_tags": [], "entities": [],
                "confidence": 0.9, "importance": imp,
            })

        return patch("kb.evaluate.call_agent", side_effect=_make_response)

    def test_run_eval_returns_report_dict(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        for ulid in ("01HEVAL00000000000000AAAA", "01HEVAL00000000000000BBBB"):
            _write_doc(root, ulid)

        with self._patched_agent():
            with patch("kb.evaluate._compute_judge_scores",
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
                       }):
                report = ev.run_eval(
                    baseline_model="baseline-x",
                    candidate_model="candidate-y",
                    root=root,
                    limit=None,
                    reference_path=None,
                    use_cache=True,
                    judge_model=None,
                    workers=1,
                )

        assert report["baseline"] == "baseline-x"
        assert report["candidate"] == "candidate-y"
        assert report["n_docs"] == 2
        # Headline metrics present.
        m = report["metrics"]
        for k in ("concept_jaccard_mean", "concept_f1_mean",
                  "importance_kl", "importance_js",
                  "baseline_failure_rate", "candidate_failure_rate"):
            assert k in m, f"missing metric: {k}"
        # per-doc records present.
        assert len(report["per_doc"]) == 2

    def test_run_eval_saves_to_models_eval_dir(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _write_doc(root, "01HEVAL00000000000000CCCC")

        with self._patched_agent():
            with patch("kb.evaluate._compute_judge_scores",
                       return_value={
                           "judge_score_mean": 3.0, "judge_score_median": 3,
                           "judge_score_dist": {"1": 0, "2": 0, "3": 1, "4": 0, "5": 0},
                           "judge_failures": 0, "judge_per_doc": [],
                       }):
                ev.run_eval(
                    baseline_model="base-z",
                    candidate_model="cand-z",
                    root=root, limit=None, reference_path=None,
                    use_cache=True, judge_model=None, workers=1,
                )

        eval_file = os.path.join(root, ".kb", "models", "eval", "cand-z.json")
        assert os.path.isfile(eval_file)
        with open(eval_file, encoding="utf-8") as f:
            stored = json.load(f)
        assert stored["model_id"] == "cand-z"
        assert stored["baseline"] == "base-z"
        assert stored["candidate"] == "cand-z"
        assert "metrics" in stored
        assert "per_doc" in stored
        assert "failures" in stored
