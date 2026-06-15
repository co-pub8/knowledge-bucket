"""Self-iterating feedback loop orchestrator (`kb improve`).

Public API:
    run_improve(root, *, iterations, target_metric, ...) -> dict
        End-to-end orchestrator. Calls ``evaluate.run_eval`` once per
        iteration, decides whether to adopt the candidate as the active
        agent model, and persists a crash-safe summary to
        ``.kb/improve/<run_id>/``.

    list_runs(root, *, limit) -> list[dict]
        List prior improve runs (most recent first).

    get_run(root, run_id) -> dict | None
        Load a single run's full summary.

Helper functions exported for tests and orchestration:
    _pick_baseline, _pick_candidates, _register_candidate_if_needed,
    _decide_adoption, _direction, _persist_iteration, _save_summary,
    _new_run_id, _ensure_improve_dir.

The actual fine-tuning is out of scope: ``kb improve`` assumes each
candidate model is already trained and registered. The orchestrator
focuses on (1) running an evaluation per iteration, (2) comparing the
candidate's target metric to the current best, and (3) flipping the
active model in ``config/kb.yml`` when a candidate wins.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from . import evaluate as _evaluate
from . import models as _models
from .core import (
    IMPROVE_DIR,
    ensure_improve_dir,
    generate_ulid,
    kb_root,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metric direction table
# ---------------------------------------------------------------------------

# Higher is better — the orchestrator adopts the candidate when its value
# exceeds the current best by more than the tolerance.
HIGHER_BETTER: set[str] = {
    "concept_jaccard_mean",
    "concept_f1_mean",
    "concept_precision_mean",
    "concept_recall_mean",
    "judge_score_mean",
}

# Lower is better — adopt when the candidate's value drops below the
# current best by more than the tolerance.
LOWER_BETTER: set[str] = {
    "importance_kl",
    "importance_js",
    "baseline_failure_rate",
    "candidate_failure_rate",
}


def _direction(target_metric: str) -> str:
    """Return "higher" or "lower" for ``target_metric``.

    Raises:
        ValueError: If the metric is not in either direction table.
    """
    if target_metric in HIGHER_BETTER:
        return "higher"
    if target_metric in LOWER_BETTER:
        return "lower"
    raise ValueError(
        f"unknown target_metric {target_metric!r}: not in HIGHER_BETTER or "
        f"LOWER_BETTER. Add it to the direction table in improve.py."
    )


# ---------------------------------------------------------------------------
# Run id and storage helpers
# ---------------------------------------------------------------------------

def _new_run_id() -> str:
    """Return a fresh ULID suitable for an improve run id."""
    return generate_ulid()


def _ensure_improve_dir(root: str, run_id: str) -> str:
    """Create and return the per-run directory path."""
    return ensure_improve_dir(root, run_id)


def _iterations_path(root: str, run_id: str) -> str:
    return os.path.join(root, IMPROVE_DIR, run_id, "iterations.jsonl")


def _summary_path(root: str, run_id: str) -> str:
    return os.path.join(root, IMPROVE_DIR, run_id, "summary.json")


def _persist_iteration(root: str, run_id: str, iteration_data: dict) -> None:
    """Append a single iteration record to ``iterations.jsonl``.

    Each call writes one JSON object per line so the file is grep-friendly
    and can be streamed without parsing the full summary.
    """
    path = _iterations_path(root, run_id)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(iteration_data, ensure_ascii=False) + "\n")


def _save_summary(root: str, run_id: str, summary: dict) -> None:
    """Overwrite ``summary.json`` with the canonical record.

    Called after every iteration so a crash mid-run leaves a recoverable
    artifact. The file is the canonical source for ``list_runs`` and
    ``get_run``; ``iterations.jsonl`` is the streaming sidecar.
    """
    path = _summary_path(root, run_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Baseline / candidate resolution
# ---------------------------------------------------------------------------

def _pick_baseline(root: str, requested: str | None) -> str | None:
    """Resolve the baseline model id.

    Resolution order:
        1. ``requested`` (if non-empty and registered).
        2. ``models.get_default(root)`` — the active agent model.
        3. First registered model sorted by ``created_at`` ascending.
        4. ``None`` (caller raises).

    Returns:
        The baseline id, or ``None`` if nothing is available.
    """
    if requested:
        rec = _models.show(requested, root=root)
        if rec is None:
            return None
        return rec["id"]

    default = _models.get_default(root=root)
    if default is not None:
        return default["id"]

    all_models = _models.list_all(root=root)
    if not all_models:
        return None
    all_models.sort(key=lambda r: r.get("created_at", ""))
    return all_models[0]["id"]


def _pick_candidates(root: str, requested: list[str] | None,
                     baseline_id: str) -> list[str]:
    """Resolve the candidate list.

    Args:
        root: Bucket root.
        requested: Explicit list of candidate ids; if non-empty, validates
            each via ``models.show`` and returns only the registered ones
            in the requested order. Unknown ids are dropped (the caller
            will raise ``ValueError`` if the list becomes empty).
        baseline_id: The resolved baseline id; dropped from the result.

    Returns:
        A list of candidate ids, excluding the baseline. Order from
        ``requested`` is preserved; otherwise the order returned by
        ``models.list_all`` is used.
    """
    if requested:
        out: list[str] = []
        for cid in requested:
            rec = _models.show(cid, root=root)
            if rec is None:
                continue
            out.append(rec["id"])
        return [c for c in out if c != baseline_id]

    return [m["id"] for m in _models.list_all(root=root)
            if m["id"] != baseline_id]


def _register_candidate_if_needed(root: str, candidate_id: str,
                                  notes: str = "") -> dict:
    """Ensure ``candidate_id`` is registered; return its record.

    Idempotent: if the model exists, returns the existing record without
    re-registering. Otherwise, registers it with a stub ``base_model`` and
    ``backend="external"`` so the eval pipeline can resolve the upstream
    id to the candidate id verbatim.
    """
    existing = _models.show(candidate_id, root=root)
    if existing is not None:
        return existing
    return _models.add(
        id=candidate_id,
        base_model="external",
        dataset_path="",
        backend="external",
        notes=notes,
        root=root,
        overwrite=False,
    )


# ---------------------------------------------------------------------------
# Adoption decision
# ---------------------------------------------------------------------------

def _decide_adoption(candidate_value: float, baseline_value: float | None,
                     target_direction: str, tolerance: float
                     ) -> tuple[bool, str]:
    """Decide whether to adopt the candidate based on the target metric.

    Rules:
        * If ``baseline_value`` is ``None`` (no prior eval), adopt
          unconditionally so the loop has a baseline to compare against
          on subsequent iterations.
        * Otherwise compute ``delta = candidate - baseline``.
            * If ``|delta| <= tolerance``, treat as a tie: adopt
              (the user asked for ``tolerance`` slack; be lenient).
            * For "higher" target, adopt when ``delta > 0``.
            * For "lower" target, adopt when ``delta < 0``.

    Args:
        candidate_value: The candidate's score on the target metric.
        baseline_value: The current best's score; ``None`` means no
            prior eval has been recorded.
        target_direction: "higher" or "lower".
        tolerance: Non-negative slack; differences within ``tolerance``
            of zero are treated as ties (and adopted per leniency).

    Returns:
        ``(adopted, reason)`` where ``reason`` is a short human-readable
        explanation suitable for the iteration log.
    """
    if baseline_value is None:
        return True, (
            f"no prior baseline metric recorded; adopting to seed "
            f"({target_direction}-better target)"
        )

    delta = candidate_value - baseline_value
    if abs(delta) <= tolerance:
        return True, (
            f"tied within tolerance "
            f"({candidate_value:.4f} vs {baseline_value:.4f}, "
            f"|delta|={abs(delta):.4f} <= {tolerance})"
        )

    if target_direction == "higher":
        if delta > 0:
            return True, f"improved by {delta:+.4f} (tolerance={tolerance})"
        return False, (
            f"no improvement: {candidate_value:.4f} < {baseline_value:.4f} "
            f"(delta={delta:+.4f})"
        )

    # Lower is better.
    if delta < 0:
        return True, f"reduced by {-delta:+.4f} (tolerance={tolerance})"
    return False, (
        f"no improvement: {candidate_value:.4f} > {baseline_value:.4f} "
        f"(delta={delta:+.4f})"
    )


# ---------------------------------------------------------------------------
# Public API: run_improve
# ---------------------------------------------------------------------------

def run_improve(
    root: str,
    *,
    iterations: int = 3,
    target_metric: str = "concept_jaccard_mean",
    tolerance: float = 0.0,
    baseline: str | None = None,
    candidates: list[str] | None = None,
    judge_model: str | None = None,
    limit: int | None = None,
    max_misses: int = 2,
    run_id: str | None = None,
    use_cache: bool = True,
) -> dict:
    """Run the self-iterating improve loop.

    For each iteration:
        1. Pick a candidate via round-robin over the candidate list.
        2. Register the candidate if it is not yet in the registry.
        3. Call ``evaluate.run_eval`` against the current best.
        4. Decide whether to adopt the candidate as the new active model.
        5. Persist state to ``summary.json`` and ``iterations.jsonl``.

    Aborts (status written to summary):
        * ``aborted_no_candidates`` — no candidates remained after
          filtering out the baseline.
        * ``aborted_no_improvement`` — ``max_misses`` consecutive
          non-adoptions.
        * ``aborted_regression`` — the candidate's value regressed
          beyond tolerance relative to the initial baseline.
        * ``aborted_max_iterations`` — safety fallback if the loop
          exits without writing ``completed`` (should not normally fire).
        * ``completed`` — loop ran to the requested number of iterations.

    Args:
        root: Bucket root.
        iterations: Number of iterations to attempt (>=1).
        target_metric: Metric from the eval report to optimize.
        tolerance: Non-negative slack for adoption and regression checks.
        baseline: Optional explicit baseline id.
        candidates: Optional explicit candidate id list; defaults to all
            registered models minus the baseline.
        judge_model: Optional judge override passed to ``run_eval``.
        limit: Optional doc cap passed to ``run_eval``.
        max_misses: Consecutive non-adoptions before
            ``aborted_no_improvement``.
        run_id: Optional explicit run id; defaults to a new ULID.
        use_cache: When True (default), reuse eval cache.

    Returns:
        The final summary dict (also written to disk).

    Raises:
        ValueError: If baseline or candidate resolution yields nothing.
    """
    if root is None:
        root = kb_root()
    if root is None:
        raise FileNotFoundError("not in a knowledge bucket (kb_root is None)")
    if iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations}")
    if max_misses < 1:
        raise ValueError(f"max_misses must be >= 1, got {max_misses}")
    if tolerance < 0:
        raise ValueError(f"tolerance must be >= 0, got {tolerance}")

    target_direction = _direction(target_metric)

    baseline_id = _pick_baseline(root, baseline)
    if baseline_id is None:
        raise ValueError(
            "No baseline model available. Pass --baseline or register a model "
            "first with 'kb models add'."
        )

    pool = _pick_candidates(root, candidates, baseline_id)
    if not pool:
        # No candidates after filtering; record an aborted run for
        # transparency and raise.
        rid = run_id or _new_run_id()
        _ensure_improve_dir(root, rid)
        summary = _new_summary(rid, baseline_id, target_metric,
                               target_direction, tolerance, iterations,
                               max_misses, judge_model, limit)
        summary["status"] = "aborted_no_candidates"
        summary["finished_at"] = _now_iso()
        summary["error"] = (
            "No candidate models available after filtering out the baseline"
        )
        _save_summary(root, rid, summary)
        raise ValueError(summary["error"])

    rid = run_id or _new_run_id()
    _ensure_improve_dir(root, rid)

    initial_baseline_metric = _load_metric_for_model(
        root, baseline_id, target_metric,
    )

    summary = _new_summary(rid, baseline_id, target_metric,
                           target_direction, tolerance, iterations,
                           max_misses, judge_model, limit)
    summary["initial_baseline_metric"] = initial_baseline_metric
    summary["status"] = "running"
    _save_summary(root, rid, summary)

    current_best_id = baseline_id
    current_best_value: float | None = initial_baseline_metric
    miss_count = 0
    adopted_count = 0
    iterations_log: list[dict] = []

    def _save_running() -> None:
        summary["iterations"] = iterations_log
        summary["adopted_count"] = adopted_count
        _save_summary(root, rid, summary)

    try:
        for iter_idx in range(iterations):
            cand_id = pool[iter_idx % len(pool)]
            _register_candidate_if_needed(
                root, cand_id,
                notes=f"auto-registered by kb improve run {rid}",
            )

            report = _evaluate.run_eval(
                baseline_model=current_best_id,
                candidate_model=cand_id,
                root=root,
                limit=limit,
                judge_model=judge_model,
                use_cache=use_cache,
                workers=4,
            )
            metrics = report.get("metrics") or {}
            candidate_value = metrics.get(target_metric)
            judged_at = report.get("judged_at", _now_iso())
            eval_report_path = (
                f".kb/models/eval/{cand_id}.json"
            )

            iteration: dict[str, Any] = {
                "iteration": iter_idx,
                "candidate_id": cand_id,
                "baseline_id": current_best_id,
                "target_metric": target_metric,
                "candidate_value": candidate_value,
                "baseline_value": current_best_value,
                "judged_at": judged_at,
                "eval_report_path": eval_report_path,
            }

            if candidate_value is None:
                iteration["decision"] = "error"
                iteration["reason"] = (
                    f"target_metric {target_metric!r} missing from eval report"
                )
                miss_count += 1
                iterations_log.append(iteration)
                _persist_iteration(root, rid, iteration)
                _save_running()
                if miss_count >= max_misses:
                    return _finalize(
                        root, rid, summary, current_best_id, iterations_log,
                        adopted_count, miss_count,
                        status_override="aborted_no_improvement",
                    )
                continue

            adopted, reason = _decide_adoption(
                candidate_value, current_best_value,
                target_direction, tolerance,
            )

            if adopted:
                previous_best_id = current_best_id
                current_best_id = cand_id
                current_best_value = candidate_value
                _models.use(cand_id, root=root)
                adopted_count += 1
                miss_count = 0
                iteration["decision"] = "adopt"
                baseline_for_delta = iteration["baseline_value"]
                if baseline_for_delta is None:
                    baseline_for_delta = candidate_value
                delta = candidate_value - baseline_for_delta
                iteration["reason"] = (
                    f"{target_metric} {candidate_value:.4f} "
                    f"vs {baseline_for_delta:.4f} (delta={delta:+.4f})"
                )
                iteration["previous_best_id"] = previous_best_id
            else:
                miss_count += 1
                iteration["decision"] = "skip"
                iteration["reason"] = reason

            iterations_log.append(iteration)
            _persist_iteration(root, rid, iteration)
            _save_running()

            # Regression abort: the candidate performed worse than the
            # baseline we started with, beyond the user's tolerance.
            if initial_baseline_metric is not None:
                regressed_higher = (
                    target_direction == "higher"
                    and candidate_value
                    < initial_baseline_metric - tolerance
                )
                regressed_lower = (
                    target_direction == "lower"
                    and candidate_value
                    > initial_baseline_metric + tolerance
                )
                if regressed_higher or regressed_lower:
                    return _finalize(
                        root, rid, summary, current_best_id, iterations_log,
                        adopted_count, miss_count,
                        status_override="aborted_regression",
                    )

            if miss_count >= max_misses:
                return _finalize(
                    root, rid, summary, current_best_id, iterations_log,
                    adopted_count, miss_count,
                    status_override="aborted_no_improvement",
                )
    except Exception:
        # Crash-safety: rewrite the summary with whatever state we have
        # collected so a follow-up ``kb improve log show`` can show the
        # partial result.
        summary["iterations"] = iterations_log
        summary["adopted_count"] = adopted_count
        summary["missed_count"] = (
            summary.get("missed_count", 0) + miss_count
        )
        summary["status"] = "running"
        summary["error"] = "interrupted"
        _save_summary(root, rid, summary)
        raise

    return _finalize(
        root, rid, summary, current_best_id, iterations_log,
        adopted_count, miss_count, status_override="completed",
    )


# ---------------------------------------------------------------------------
# Public API: list / get
# ---------------------------------------------------------------------------

def list_runs(root: str, *, limit: int | None = None) -> list[dict]:
    """List recent improve runs, most recent first.

    Each entry is the full ``summary.json`` dict (small enough to inline).
    Sorted by ``started_at`` descending.

    Args:
        root: Bucket root.
        limit: Optional cap on the number of runs returned.

    Returns:
        A list of summary dicts. An empty list is returned when no runs
        have been recorded.
    """
    if root is None:
        return []
    base = os.path.join(root, IMPROVE_DIR)
    if not os.path.isdir(base):
        return []
    out: list[dict] = []
    for entry in os.listdir(base):
        summary_file = os.path.join(base, entry, "summary.json")
        if not os.path.isfile(summary_file):
            continue
        try:
            with open(summary_file, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("skipping unreadable run %s: %s", entry, e)
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    if limit is not None:
        out = out[: max(0, int(limit))]
    return out


def get_run(root: str, run_id: str) -> dict | None:
    """Return the full summary for ``run_id``, or ``None`` if missing."""
    if root is None or not run_id:
        return None
    summary_file = _summary_path(root, run_id)
    if not os.path.isfile(summary_file):
        return None
    try:
        with open(summary_file, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return rec if isinstance(rec, dict) else None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _new_summary(run_id: str, baseline_id: str, target_metric: str,
                 target_direction: str, tolerance: float, iterations: int,
                 max_misses: int, judge_model: str | None,
                 limit: int | None) -> dict:
    """Build an empty summary dict in the canonical schema."""
    return {
        "run_id": run_id,
        "started_at": _now_iso(),
        "finished_at": None,
        "status": "running",
        "target_metric": target_metric,
        "target_direction": target_direction,
        "tolerance": tolerance,
        "iterations_requested": iterations,
        "max_misses": max_misses,
        "baseline_id": baseline_id,
        "initial_baseline_metric": None,
        "final_model_id": baseline_id,
        "total_iterations": 0,
        "adopted_count": 0,
        "missed_count": 0,
        "judge_model": judge_model,
        "limit": limit,
        "iterations": [],
    }


def _load_metric_for_model(root: str, model_id: str,
                            target_metric: str) -> float | None:
    """Read ``target_metric`` from the persisted eval report, if any."""
    path = os.path.join(root, _models.MODELS_DIR, _models.EVAL_SUBDIR,
                        f"{model_id}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(rec, dict):
        return None
    metrics = rec.get("metrics") or {}
    val = metrics.get(target_metric)
    if isinstance(val, (int, float)):
        return float(val)
    return None


def _finalize(root: str, run_id: str, summary: dict, final_model_id: str,
              iterations_log: list[dict], adopted_count: int,
              miss_count: int, *, status_override: str) -> dict:
    """Stamp the canonical end-of-run fields onto ``summary`` and persist.

    Returns the summary for caller convenience.
    """
    summary["iterations"] = iterations_log
    summary["adopted_count"] = adopted_count
    summary["missed_count"] = (
        summary.get("missed_count", 0) + miss_count
    )
    summary["total_iterations"] = len(iterations_log)
    summary["final_model_id"] = final_model_id
    summary["status"] = status_override
    summary["finished_at"] = _now_iso()
    _save_summary(root, run_id, summary)
    return summary
