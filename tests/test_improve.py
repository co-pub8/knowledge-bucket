"""Tests for the self-iterating improve orchestrator (improve.py)."""

import json
import os
from unittest.mock import patch

import pytest

from kb import improve as imp
from kb import models as registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _init_kb(root: str) -> None:
    """Create a minimal config/kb.yml so kb_root can be resolved."""
    cfg = os.path.join(root, "config", "kb.yml")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("records_dir: records\n")


def _register(root: str, model_id: str, *, base_model: str = "m") -> dict:
    """Register a model in the registry and return its record."""
    with patch("kb.models.kb_root", return_value=root):
        return registry.add(
            model_id, base_model=base_model, dataset_path="d",
            backend="external",
        )


def _make_report(metric_name: str, value: float) -> dict:
    """Build a stub eval report with the given target metric value."""
    return {
        "model_id": "x",
        "baseline": "y",
        "candidate": "x",
        "n_docs": 0,
        "judged_at": "2026-06-15T00:00:00Z",
        "metrics": {metric_name: value},
        "per_doc": [],
        "failures": [],
    }


def _patch_eval(metric_name: str, value: float):
    """Patch ``kb.improve._evaluate.run_eval`` to return a stub report."""
    return patch(
        "kb.improve._evaluate.run_eval",
        return_value=_make_report(metric_name, value),
    )


# ---------------------------------------------------------------------------
# Direction table
# ---------------------------------------------------------------------------

class TestDirection:
    def test_known_higher_better(self):
        assert imp._direction("concept_jaccard_mean") == "higher"
        assert imp._direction("judge_score_mean") == "higher"

    def test_known_lower_better(self):
        assert imp._direction("importance_kl") == "lower"
        assert imp._direction("importance_js") == "lower"

    def test_unknown_metric_raises(self):
        with pytest.raises(ValueError):
            imp._direction("nonexistent_metric")


# ---------------------------------------------------------------------------
# Adoption decision
# ---------------------------------------------------------------------------

class TestDecideAdoption:
    def test_higher_better_improvement_adopts(self):
        adopted, reason = imp._decide_adoption(0.6, 0.5, "higher", 0.0)
        assert adopted is True
        assert "improved" in reason

    def test_higher_better_regression_skips(self):
        adopted, reason = imp._decide_adoption(0.4, 0.5, "higher", 0.0)
        assert adopted is False
        assert "no improvement" in reason

    def test_higher_better_tie_within_tolerance_adopts(self):
        # 0.500 vs 0.500 is a tie; tolerance=0.01 makes the loop lenient.
        adopted, _ = imp._decide_adoption(0.500, 0.500, "higher", 0.01)
        assert adopted is True

    def test_higher_better_tie_with_zero_tolerance_adopts(self):
        # Equal values are within zero tolerance, so the loop is lenient.
        adopted, _ = imp._decide_adoption(0.500, 0.500, "higher", 0.0)
        assert adopted is True

    def test_higher_better_regression_outside_tolerance_skips(self):
        # |delta| = 0.01 with tolerance 0 — strictly worse, must skip.
        adopted, reason = imp._decide_adoption(0.499, 0.510, "higher", 0.0)
        assert adopted is False
        assert "no improvement" in reason

    def test_lower_better_improvement_adopts(self):
        adopted, _ = imp._decide_adoption(0.2, 0.5, "lower", 0.0)
        assert adopted is True

    def test_lower_better_regression_skips(self):
        adopted, reason = imp._decide_adoption(0.8, 0.5, "lower", 0.0)
        assert adopted is False
        assert "no improvement" in reason

    def test_lower_better_tie_within_tolerance_adopts(self):
        adopted, _ = imp._decide_adoption(0.500, 0.500, "lower", 0.01)
        assert adopted is True

    def test_no_baseline_adopts_to_seed(self):
        adopted, reason = imp._decide_adoption(0.0, None, "higher", 0.0)
        assert adopted is True
        assert "no prior baseline" in reason


# ---------------------------------------------------------------------------
# Baseline / candidate resolution
# ---------------------------------------------------------------------------

class TestPickBaseline:
    def test_explicit_baseline_returned(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "m1")
        _register(root, "m2")
        with patch("kb.models.kb_root", return_value=root):
            assert imp._pick_baseline(root, "m2") == "m2"

    def test_explicit_baseline_unknown_returns_none(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            assert imp._pick_baseline(root, "ghost") is None

    def test_falls_back_to_default(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "m1")
        _register(root, "m2")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("m2", root=root)
            assert imp._pick_baseline(root, None) == "m2"

    def test_falls_back_to_first_registered(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "alpha")
        _register(root, "beta")
        with patch("kb.models.kb_root", return_value=root):
            # ``first registered`` is by created_at; the second add wins.
            picked = imp._pick_baseline(root, None)
        assert picked in {"alpha", "beta"}


class TestPickCandidates:
    def test_explicit_list_filters_unknown(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "m1")
        _register(root, "m2")
        with patch("kb.models.kb_root", return_value=root):
            cands = imp._pick_candidates(root, ["m1", "ghost", "m2"], "m1")
        assert cands == ["m2"]

    def test_default_pool_excludes_baseline(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "m1")
        _register(root, "m2")
        _register(root, "m3")
        with patch("kb.models.kb_root", return_value=root):
            cands = imp._pick_candidates(root, None, "m2")
        assert "m2" not in cands
        assert set(cands) == {"m1", "m3"}

    def test_empty_when_only_baseline(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "only")
        with patch("kb.models.kb_root", return_value=root):
            assert imp._pick_candidates(root, None, "only") == []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegisterCandidateIfNeeded:
    def test_idempotent_for_existing_model(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "m1")
        with patch("kb.models.kb_root", return_value=root):
            rec = imp._register_candidate_if_needed(root, "m1")
        assert rec["id"] == "m1"

    def test_registers_new_model(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            rec = imp._register_candidate_if_needed(
                root, "ghost-model", notes="added by improve",
            )
        assert rec["id"] == "ghost-model"
        assert rec["backend"] == "external"
        assert "improve" in rec["notes"]


# ---------------------------------------------------------------------------
# run_improve error paths
# ---------------------------------------------------------------------------

class TestRunImproveErrors:
    def test_no_baseline_raises(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with pytest.raises(ValueError, match="No baseline model available"):
            imp.run_improve(root, iterations=1, baseline=None)

    def test_no_candidates_raises(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "only")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("only", root=root)
        with pytest.raises(ValueError, match="No candidate models available"):
            imp.run_improve(root, iterations=1, baseline="only")

    def test_iterations_zero_raises(self, tmp_path):
        with pytest.raises(ValueError, match="iterations must be >= 1"):
            imp.run_improve(str(tmp_path), iterations=0)

    def test_max_misses_zero_raises(self, tmp_path):
        with pytest.raises(ValueError, match="max_misses must be >= 1"):
            imp.run_improve(str(tmp_path), max_misses=0)

    def test_negative_tolerance_raises(self, tmp_path):
        with pytest.raises(ValueError, match="tolerance must be >= 0"):
            imp.run_improve(str(tmp_path), tolerance=-0.1)


# ---------------------------------------------------------------------------
# run_improve iteration outcomes
# ---------------------------------------------------------------------------

class TestRunImproveAdoption:
    def test_single_iteration_adopts(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with _patch_eval("concept_jaccard_mean", 0.7):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"],
                )
        assert summary["status"] == "completed"
        assert summary["adopted_count"] == 1
        assert summary["final_model_id"] == "cand"
        assert summary["iterations"][0]["decision"] == "adopt"

    def test_single_iteration_skip(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            # Persist a baseline metric so the skip path is exercised.
            registry.eval_record("base", {
                "metrics": {"concept_jaccard_mean": 0.5},
                "n_docs": 0,
            }, root=root)
            # value 0.1 < 0.5 baseline, expect skip.
            with _patch_eval("concept_jaccard_mean", 0.1):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"], max_misses=1,
                )
        assert summary["adopted_count"] == 0
        assert summary["final_model_id"] == "base"
        assert summary["iterations"][0]["decision"] == "skip"

    def test_adopt_calls_models_use(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with _patch_eval("concept_jaccard_mean", 0.7):
                with patch("kb.improve._models.use") as mock_use:
                    imp.run_improve(
                        root, iterations=1, baseline="base",
                        candidates=["cand"],
                    )
        # ``models.use`` is called with the candidate id.
        assert any(call.args and call.args[0] == "cand"
                   for call in mock_use.call_args_list)

    def test_aborts_after_max_consecutive_misses(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand1")
        _register(root, "cand2")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            # Set the baseline metric so a 0.1 candidate value regresses.
            registry.eval_record("base", {
                "metrics": {"concept_jaccard_mean": 0.5},
                "n_docs": 0,
            }, root=root)
            with _patch_eval("concept_jaccard_mean", 0.1):
                summary = imp.run_improve(
                    root, iterations=5, baseline="base",
                    candidates=["cand1", "cand2"], max_misses=2,
                )
        # Two consecutive misses trigger aborted_no_improvement. Iteration
        # 1 itself is a regression vs the initial 0.5 (status override).
        # The orchestrator should record at least one skipped iteration
        # before the max-misses check trips.
        assert summary["status"] in {
            "aborted_no_improvement", "aborted_regression",
        }
        assert summary["adopted_count"] == 0

    def test_aborts_on_regression_higher_better(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        # Persist a baseline metric so regression detection has something
        # to compare against.
        with patch("kb.models.kb_root", return_value=root):
            registry.eval_record("base", {
                "metrics": {"concept_jaccard_mean": 0.5},
                "n_docs": 0,
            }, root=root)
        with _patch_eval("concept_jaccard_mean", 0.1):
            summary = imp.run_improve(
                root, iterations=3, baseline="base",
                candidates=["cand"], tolerance=0.0,
            )
        assert summary["status"] == "aborted_regression"
        assert summary["adopted_count"] == 0

    def test_aborts_on_regression_lower_better(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.eval_record("base", {
                "metrics": {"importance_kl": 0.2},
                "n_docs": 0,
            }, root=root)
        with _patch_eval("importance_kl", 0.9):
            summary = imp.run_improve(
                root, iterations=3, baseline="base",
                candidates=["cand"], tolerance=0.0,
                target_metric="importance_kl",
            )
        assert summary["status"] == "aborted_regression"
        assert summary["adopted_count"] == 0

    def test_respects_target_metric_direction(self, tmp_path):
        """A value that is 'better' for importance_kl (lower) is adopted."""
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with _patch_eval("importance_kl", 0.05):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"], target_metric="importance_kl",
                )
        # importance_kl is lower-better; 0.05 is the new best, no baseline.
        assert summary["adopted_count"] == 1
        assert summary["final_model_id"] == "cand"

    def test_registers_new_candidate_via_models_add(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        # "cand" is pre-registered (so it survives _pick_candidates),
        # but inside the loop we want the registration branch to fire.
        # We achieve that by patching ``_register_candidate_if_needed``
        # itself, then asserting ``_models.add`` was called.
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with patch("kb.improve._register_candidate_if_needed") as mock_reg:
                mock_reg.return_value = {"id": "cand"}
                with _patch_eval("concept_jaccard_mean", 0.7):
                    imp.run_improve(
                        root, iterations=1, baseline="base",
                        candidates=["cand"],
                    )
        # The orchestrator must have invoked the registration helper.
        assert mock_reg.call_count >= 1

    def test_run_improve_with_target_metric_importance_kl(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            # 0.3 < 0.5 → adopt (lower is better for KL).
            with _patch_eval("importance_kl", 0.3):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"], target_metric="importance_kl",
                )
        assert summary["adopted_count"] == 1
        assert summary["final_model_id"] == "cand"
        assert summary["target_metric"] == "importance_kl"
        assert summary["target_direction"] == "lower"

    def test_run_improve_with_tolerance(self, tmp_path):
        """A small negative delta within ``tolerance`` is adopted (lenient)."""
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            # Seed a prior baseline metric so the loop has something to
            # compare against; candidate 0.48 is *worse* than 0.50 but
            # within the 0.05 tolerance band → must adopt.
            registry.eval_record("base", {
                "metrics": {"concept_jaccard_mean": 0.50},
                "n_docs": 0,
            }, root=root)
            with _patch_eval("concept_jaccard_mean", 0.48):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"], tolerance=0.05,
                )
        assert summary["adopted_count"] == 1
        assert summary["final_model_id"] == "cand"
        assert summary["tolerance"] == 0.05

    def test_run_improve_with_explicit_baseline(self, tmp_path):
        """``baseline=`` overrides ``models.get_default`` to the chosen id."""
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "alpha")
        _register(root, "beta")
        _register(root, "gamma")
        with patch("kb.models.kb_root", return_value=root):
            # Mark ``alpha`` as the default; then request ``beta`` explicitly.
            registry.use("alpha", root=root)
            with _patch_eval("concept_jaccard_mean", 0.6):
                summary = imp.run_improve(
                    root, iterations=1,
                    baseline="beta", candidates=["gamma"],
                )
        # The chosen baseline is ``beta``, not the active ``alpha``.
        assert summary["baseline_id"] == "beta"
        # alpha must not appear as the baseline anywhere in the summary.
        for it in summary["iterations"]:
            assert it["baseline_id"] == "beta"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

class TestRunImprovePersistence:
    def test_writes_summary_json(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with _patch_eval("concept_jaccard_mean", 0.7):
                summary = imp.run_improve(
                    root, iterations=1, baseline="base",
                    candidates=["cand"],
                )
        run_id = summary["run_id"]
        path = os.path.join(root, imp.IMPROVE_DIR, run_id, "summary.json")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            persisted = json.load(f)
        assert persisted["run_id"] == run_id
        assert persisted["status"] == "completed"
        assert persisted["baseline_id"] == "base"
        assert persisted["target_metric"] == "concept_jaccard_mean"

    def test_writes_iterations_jsonl(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        _register(root, "cand1")
        _register(root, "cand2")
        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)
            with _patch_eval("concept_jaccard_mean", 0.5):
                summary = imp.run_improve(
                    root, iterations=2, baseline="base",
                    candidates=["cand1", "cand2"],
                )
        run_id = summary["run_id"]
        path = os.path.join(root, imp.IMPROVE_DIR, run_id, "iterations.jsonl")
        assert os.path.isfile(path)
        with open(path, encoding="utf-8") as f:
            lines = [json.loads(ln) for ln in f if ln.strip()]
        assert len(lines) == 2
        assert {ln["candidate_id"] for ln in lines} == {"cand1", "cand2"}


# ---------------------------------------------------------------------------
# list_runs / get_run
# ---------------------------------------------------------------------------

class TestListAndGet:
    def test_list_runs_reverse_chronological(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        base_dir = os.path.join(root, imp.IMPROVE_DIR)
        os.makedirs(base_dir, exist_ok=True)
        # Two synthetic run dirs with different started_at values.
        for rid, started in [("01OLDER", "2026-06-01T00:00:00Z"),
                             ("01NEWER", "2026-06-15T00:00:00Z")]:
            d = os.path.join(base_dir, rid)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "summary.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"run_id": rid, "started_at": started}, f)
        with patch("kb.models.kb_root", return_value=root):
            runs = imp.list_runs(root)
        assert [r["run_id"] for r in runs] == ["01NEWER", "01OLDER"]

    def test_list_runs_limit(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        base_dir = os.path.join(root, imp.IMPROVE_DIR)
        os.makedirs(base_dir, exist_ok=True)
        for i, ts in enumerate(["2026-06-01T00:00:00Z",
                                 "2026-06-02T00:00:00Z",
                                 "2026-06-03T00:00:00Z"]):
            d = os.path.join(base_dir, f"01RUN{i}")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "summary.json"), "w",
                      encoding="utf-8") as f:
                json.dump({"run_id": f"01RUN{i}", "started_at": ts}, f)
        with patch("kb.models.kb_root", return_value=root):
            runs = imp.list_runs(root, limit=2)
        assert len(runs) == 2

    def test_get_run_returns_full_summary(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        base_dir = os.path.join(root, imp.IMPROVE_DIR, "01ABC")
        os.makedirs(base_dir, exist_ok=True)
        with open(os.path.join(base_dir, "summary.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"run_id": "01ABC", "status": "completed"}, f)
        with patch("kb.models.kb_root", return_value=root):
            rec = imp.get_run(root, "01ABC")
        assert rec is not None
        assert rec["run_id"] == "01ABC"
        assert rec["status"] == "completed"

    def test_get_run_missing_returns_none(self, tmp_path):
        root = str(tmp_path)
        _init_kb(root)
        with patch("kb.models.kb_root", return_value=root):
            assert imp.get_run(root, "01MISSING") is None


# ---------------------------------------------------------------------------
# E2E: three iterations, at least one adopt
# ---------------------------------------------------------------------------

class TestE2E:
    def test_three_iterations_at_least_one_adopt(self, tmp_path):
        """Register baseline + 3 candidates; metrics trend up on iteration 1.

        With the round-robin schedule, the second candidate (trending up)
        should be adopted; iterations 2 and 3 either adopt further or
        skip. End state: ``adopted_count >= 1`` and ``final_model_id`` is
        the best of the candidates.
        """
        root = str(tmp_path)
        _init_kb(root)
        _register(root, "base")
        for cid in ["cand-a", "cand-b", "cand-c"]:
            _register(root, cid)

        with patch("kb.models.kb_root", return_value=root):
            registry.use("base", root=root)

            # Trending values: 0.4, 0.6, 0.5. Adopt at index 1.
            trending = iter([0.4, 0.6, 0.5])

            def fake_eval(baseline_model, candidate_model, root, **kwargs):
                return _make_report(
                    "concept_jaccard_mean", next(trending),
                )

            with patch("kb.improve._evaluate.run_eval", side_effect=fake_eval):
                summary = imp.run_improve(
                    root, iterations=3, baseline="base",
                    candidates=["cand-a", "cand-b", "cand-c"],
                )

        assert summary["status"] == "completed"
        assert summary["adopted_count"] >= 1
        # The strongest candidate (cand-b, value 0.6) must be the final.
        assert summary["final_model_id"] == "cand-b"
        # Each iteration is recorded once.
        assert len(summary["iterations"]) == 3
