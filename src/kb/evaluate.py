"""Evaluation harness: compare a candidate model against a baseline.

Compares two models (or two upstream ids) on the same set of analyzed
documents and produces a structured eval report. The four headline metrics are:

  1. Concept overlap (Jaccard + F1 over primary + candidate concept ids)
  2. Importance KL divergence (10-bin bucketized histogram)
  3. LLM-as-judge score (1-5, optional but recommended)
  4. Failure rate (per-model; lists the failing doc ids)

Optionally a JSONL reference file provides ground truth for accuracy / F1 /
summary-BLEU metrics.

Per-(model, doc) analysis results are cached on disk so repeat evaluations
of the same model are O(1) reads. The cache is independent from the live
document front matter (which only holds the active model's analysis).
"""

import hashlib
import json
import logging
import math
import os
import random
import re
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from .analyzer import (
    AnalysisResult,
    ConceptRef,
    EntityRef,
    _extract_json,
    build_analysis_prompt,
    call_agent,
    parse_analysis_response,
)
from .core import DOC_DIR, RECORDS_DIR, ensure_models_dirs
from .index import _FM_RE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVAL_CACHE_DIR = ".kb/models/eval/cache"
JUDGE_PROMPT_FILE = "eval_judge.md"
_BODY_MAX_CHARS = 4000          # truncation cap for the judge prompt
_ANALYSIS_BODY_MAX_CHARS = 8000  # matches analyzer.analyze_document's cap
_IMPORTANCE_BINS = 10           # [0.0, 0.1) ... [0.9, 1.0]
_EPS = 1e-10                    # smoothing for KL/JS computations


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(filename: str) -> str:
    """Load a prompt template from the bundled kb.prompts package.

    Args:
        filename: The .md filename inside the package (e.g. ``"eval_judge.md"``).

    Returns:
        The full text of the prompt, decoded as UTF-8.

    Raises:
        FileNotFoundError: If the file does not exist in the package.
    """
    return resources.files("kb.prompts").joinpath(filename).read_text(encoding="utf-8")


def build_judge_prompt(doc_body: str, baseline_summary: str,
                       candidate_summary: str) -> str:
    """Compose the LLM-as-judge prompt from the loaded template.

    Truncates the document body to ``_BODY_MAX_CHARS`` so the prompt fits
    within the agent proxy's command-line budget. The rubric and output
    format come from ``eval_judge.md``; the body and summaries are
    substituted in.

    Args:
        doc_body: The full document body (post front matter).
        baseline_summary: The baseline model's summary.
        candidate_summary: The candidate model's summary.

    Returns:
        A single string ready to send to ``call_agent``.
    """
    template = load_prompt(JUDGE_PROMPT_FILE)
    truncated_body = doc_body[:_BODY_MAX_CHARS]
    return (
        template
        .replace("<DOCUMENT_BODY>", truncated_body)
        .replace("<BASELINE_SUMMARY>", baseline_summary)
        .replace("<CANDIDATE_SUMMARY>", candidate_summary)
    )


# ---------------------------------------------------------------------------
# Failure detection
# ---------------------------------------------------------------------------

def _is_failure(result: AnalysisResult) -> bool:
    """Return True if the analysis result is unusable for comparison.

    A failure means at least one of:
      (a) summary is empty after strip
      (b) importance is outside [0.0, 1.0]
      (c) both concept lists are empty
    """
    if not (result.summary or "").strip():
        return True
    if not (0.0 <= float(result.importance) <= 1.0):
        return True
    if not result.all_concept_ids():
        return True
    return False


def _failure_reason(result: AnalysisResult) -> str:
    """Return a short human-readable reason for a failed analysis."""
    if not (result.summary or "").strip():
        return "empty summary"
    if not (0.0 <= float(result.importance) <= 1.0):
        return f"importance out of range: {result.importance}"
    if not result.all_concept_ids():
        return "no concepts"
    return ""


# ---------------------------------------------------------------------------
# Metric 1: Concept overlap (Jaccard + F1)
# ---------------------------------------------------------------------------

def _concept_sets(result: AnalysisResult) -> set[str]:
    """Return the set of concept ids (primary + candidate) from a result.

    Concept ids are slug-normalized (lowercase, hyphens) by the analyzer,
    so we just use them as-is for set ops.
    """
    return set(result.all_concept_ids())


def _per_doc_jaccard_f1(doc_id: str, baseline: AnalysisResult,
                        candidate: AnalysisResult) -> dict[str, Any]:
    """Compute per-doc concept overlap metrics between two analyses."""
    a = _concept_sets(baseline)
    b = _concept_sets(candidate)
    inter = a & b
    union = a | b
    jaccard = (len(inter) / len(union)) if union else 1.0
    precision = (len(inter) / len(b)) if b else 1.0
    recall = (len(inter) / len(a)) if a else 1.0
    denom = precision + recall
    f1 = (2 * precision * recall / denom) if denom else 0.0
    return {
        "doc_id": doc_id,
        "jaccard": jaccard,
        "f1": f1,
        "precision": precision,
        "recall": recall,
        "A": sorted(a),
        "B": sorted(b),
        "inter": sorted(inter),
    }


def _compute_concept_metrics(
    pairs: list[tuple[str, AnalysisResult, AnalysisResult]],
) -> dict[str, Any]:
    """Compute Jaccard + F1 metrics across the (baseline, candidate) pairs.

    Args:
        pairs: List of (doc_id, baseline, candidate) tuples.

    Returns:
        A dict with per-doc records and the four global means.
    """
    per_doc: list[dict[str, Any]] = []
    for doc_id, baseline, candidate in pairs:
        per_doc.append(_per_doc_jaccard_f1(doc_id, baseline, candidate))

    if not per_doc:
        return {
            "concept_jaccard_mean": 0.0,
            "concept_f1_mean": 0.0,
            "concept_precision_mean": 0.0,
            "concept_recall_mean": 0.0,
            "per_doc": [],
        }

    return {
        "concept_jaccard_mean": _mean(d["jaccard"] for d in per_doc),
        "concept_f1_mean": _mean(d["f1"] for d in per_doc),
        "concept_precision_mean": _mean(d["precision"] for d in per_doc),
        "concept_recall_mean": _mean(d["recall"] for d in per_doc),
        "per_doc": per_doc,
    }


# ---------------------------------------------------------------------------
# Metric 2: Importance KL divergence
# ---------------------------------------------------------------------------

def _bucket_importance(values: list[float]) -> list[int]:
    """Bucket importance values into ``_IMPORTANCE_BINS`` equal-width bins.

    Args:
        values: Continuous importance scores in [0.0, 1.0].

    Returns:
        A list of length ``_IMPORTANCE_BINS`` with the count in each bin.
        Values above 1.0 are clamped to the last bin; values below 0.0
        are clamped to the first.
    """
    counts = [0] * _IMPORTANCE_BINS
    for v in values:
        # Clamp to [0, 1] then map to a bin index.
        clamped = max(0.0, min(1.0, float(v)))
        if clamped >= 1.0:
            idx = _IMPORTANCE_BINS - 1
        else:
            idx = int(clamped * _IMPORTANCE_BINS)
        if 0 <= idx < _IMPORTANCE_BINS:
            counts[idx] += 1
    return counts


def _histogram_to_pmf(counts: list[int]) -> list[float]:
    """Normalize a histogram to a probability mass function.

    Returns a uniform 1/N distribution when the total count is zero, so
    downstream KL/JS calls don't divide by zero.
    """
    total = sum(counts)
    n = len(counts)
    if total == 0:
        return [1.0 / n] * n
    return [c / total for c in counts]


def _kl_divergence(p: list[float], q: list[float]) -> float:
    """Compute KL(p || q) with smoothing for zero entries in q.

    Returns a non-negative float. Zero entries in p contribute 0 to the
    sum regardless of q. The smoothing term keeps the calculation
    numerically stable when q has zero mass in a bin.
    """
    total = 0.0
    for pi, qi in zip(p, q):
        if pi <= 0.0:
            continue
        total += pi * math.log(pi / max(qi, _EPS))
    return max(0.0, total)


def _js_divergence(p: list[float], q: list[float]) -> float:
    """Compute the symmetric Jensen-Shannon divergence, bounded in [0, log 2]."""
    m = [(pi + qi) / 2 for pi, qi in zip(p, q)]
    return 0.5 * (_kl_divergence(p, m) + _kl_divergence(q, m))


def _compute_importance_kl(
    baseline_results: list[AnalysisResult],
    candidate_results: list[AnalysisResult],
) -> dict[str, Any]:
    """Compute importance distribution KL/JS divergence between two models.

    Returns:
        A dict with raw bucket counts for both models plus the KL and JS
        divergences. Both divergences are 0.0 when the two distributions
        are identical.
    """
    b_values = [float(r.importance) for r in baseline_results]
    c_values = [float(r.importance) for r in candidate_results]
    b_counts = _bucket_importance(b_values)
    c_counts = _bucket_importance(c_values)
    p = _histogram_to_pmf(b_counts)
    q = _histogram_to_pmf(c_counts)
    return {
        "importance_kl": _kl_divergence(p, q),
        "importance_js": _js_divergence(p, q),
        "importance_histogram_baseline": b_counts,
        "importance_histogram_candidate": c_counts,
    }


# ---------------------------------------------------------------------------
# Metric 3: LLM-as-judge
# ---------------------------------------------------------------------------

def _judge_one(
    doc_id: str,
    doc_body: str,
    baseline_summary: str,
    candidate_summary: str,
    judge_model: str | None,
) -> tuple[str, int | None, str] | None:
    """Run the judge for a single doc and parse the response.

    Args:
        doc_id: The document's ULID (for logging/tracing).
        doc_body: The full document body (truncated internally).
        baseline_summary: The baseline model's summary.
        candidate_summary: The candidate model's summary.
        judge_model: Optional model id override for the judge LLM.

    Returns:
        ``(doc_id, score, reasoning)`` on success; ``(doc_id, None, "")`` when
        either summary is empty (cannot judge); raises on parse/agent errors.
    """
    if not (baseline_summary or "").strip() or not (candidate_summary or "").strip():
        return (doc_id, None, "")
    prompt = build_judge_prompt(doc_body, baseline_summary, candidate_summary)
    raw = call_agent(prompt, model=judge_model)
    data = json.loads(_extract_json(raw))
    score = int(data.get("score"))
    if score not in (1, 2, 3, 4, 5):
        raise ValueError(f"judge returned out-of-range score: {score}")
    reasoning = str(data.get("reasoning", ""))
    return (doc_id, score, reasoning)


def _compute_judge_scores(
    pairs: list[tuple[str, AnalysisResult, AnalysisResult, str]],
    judge_model: str | None,
    workers: int = 4,
) -> dict[str, Any]:
    """Compute LLM-as-judge scores across the (baseline, candidate, body) pairs.

    Each pair is a separate agent call. Run them in parallel via a thread
    pool; aggregate scores at the end.

    Args:
        pairs: List of (doc_id, baseline_result, candidate_result, body).
        judge_model: Optional model id override.
        workers: Parallel worker count for the agent calls.

    Returns:
        A dict with mean, median, distribution (1-5 count), failures count,
        and a per-doc list of (doc_id, score, reasoning).
    """
    if not pairs:
        return {
            "judge_score_mean": None,
            "judge_score_median": None,
            "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
            "judge_failures": 0,
            "judge_per_doc": [],
        }

    def _run(item):
        doc_id, baseline, candidate, body = item
        try:
            return _judge_one(doc_id, body, baseline.summary,
                              candidate.summary, judge_model)
        except Exception as e:  # noqa: BLE001
            logger.warning("judge failed for %s: %s", doc_id, e)
            return (doc_id, None, str(e))

    results: list[tuple[str, int | None, str]] = []
    if workers <= 1:
        results = [_run(p) for p in pairs]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run, p) for p in pairs]
            for fut in as_completed(futures):
                results.append(fut.result())

    scores: list[int] = []
    per_doc: list[dict[str, Any]] = []
    failures = 0
    for doc_id, score, reasoning in results:
        per_doc.append({"doc_id": doc_id, "score": score,
                        "reasoning": reasoning})
        if score is None:
            failures += 1
        else:
            scores.append(score)

    dist = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
    for s in scores:
        dist[str(s)] += 1

    return {
        "judge_score_mean": (statistics.mean(scores) if scores else None),
        "judge_score_median": (statistics.median(scores) if scores else None),
        "judge_score_dist": dist,
        "judge_failures": failures,
        "judge_per_doc": per_doc,
    }


# ---------------------------------------------------------------------------
# Metric 4: Failure rates
# ---------------------------------------------------------------------------

def _compute_failure_rates(
    pairs: list[tuple[str, AnalysisResult, AnalysisResult]],
) -> dict[str, Any]:
    """Compute per-model failure rates and a delta.

    A failed run produces no usable comparison; the delta (candidate - baseline)
    is negative when the candidate is more reliable than the baseline.
    """
    if not pairs:
        return {
            "baseline_failure_rate": 0.0,
            "candidate_failure_rate": 0.0,
            "failure_rate_delta": 0.0,
            "failures": [],
        }
    b_fails = [(d, "baseline", _failure_reason(b))
               for d, b, _c in pairs if _is_failure(b)]
    c_fails = [(d, "candidate", _failure_reason(c))
               for d, _b, c in pairs if _is_failure(c)]
    all_fails = b_fails + c_fails
    n = len(pairs)
    return {
        "baseline_failure_rate": len(b_fails) / n,
        "candidate_failure_rate": len(c_fails) / n,
        "failure_rate_delta": (len(c_fails) - len(b_fails)) / n,
        "failures": [{"doc_id": d, "model": m, "reason": r}
                     for d, m, r in all_fails],
    }


# ---------------------------------------------------------------------------
# Optional Metric 5: Reference (ground truth)
# ---------------------------------------------------------------------------

def _load_reference(path: str) -> dict[str, dict[str, Any]]:
    """Load a JSONL reference file keyed by doc_id.

    Each line is a JSON object with at least ``doc_id``; optional fields are
    ``expected_concepts`` (list of strings/slugs), ``expected_importance``
    (float), and ``expected_summary`` (str).
    """
    out: dict[str, dict[str, Any]] = {}
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"reference line {ln}: invalid JSON: {e}") from e
            if "doc_id" not in rec:
                raise ValueError(f"reference line {ln}: missing doc_id")
            out[str(rec["doc_id"])] = rec
    return out


def _concept_set_from_strings(items: list[Any]) -> set[str]:
    """Normalize a list of strings/dicts to a set of slug-style ids.

    Strings are slug-normalized to match ``Analyzer._parse_concept_list``;
    dicts with an ``id`` field use that id directly.
    """
    out: set[str] = set()
    for item in items:
        if isinstance(item, dict):
            cid = str(item.get("id", "")).strip()
            if cid:
                out.add(cid)
        elif isinstance(item, str):
            slug = item.lower().replace(" ", "-").strip()
            if slug:
                out.add(slug)
    return out


def _per_doc_reference_f1(candidate: AnalysisResult,
                          expected: set[str]) -> float:
    """Compute concept-level F1 between a candidate and a reference set."""
    pred = _concept_sets(candidate)
    if not expected and not pred:
        return 1.0
    if not expected or not pred:
        return 0.0
    inter = pred & expected
    precision = len(inter) / len(pred)
    recall = len(inter) / len(expected)
    denom = precision + recall
    return (2 * precision * recall / denom) if denom else 0.0


def _corpus_bleu(candidates: list[str], references: list[str]) -> float:
    """Compute a tiny corpus-level BLEU (unigram + bigram precision, brevity penalty).

    No NLTK dependency. Returns a value in [0, 1] clamped. We use a smooth
    method (+1 to numerator and denominator) so empty references don't crash.
    """
    if not candidates or not references or len(candidates) != len(references):
        return 0.0

    def ngrams(tokens: list[str], n: int) -> list[tuple[str, ...]]:
        return [tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]

    def _tok(s: str) -> list[str]:
        return re.findall(r"\w+", s.lower())

    smooth = 1
    total_clip = 0
    total_count = 0
    cand_len = 0
    ref_len = 0
    for cand, ref in zip(candidates, references):
        ct = _tok(cand)
        rt = _tok(ref)
        cand_len += len(ct)
        ref_len += len(rt)
        for n in (1, 2):
            c_ng = ngrams(ct, n)
            r_ng = ngrams(rt, n)
            if not c_ng:
                continue
            r_counts: dict[tuple[str, ...], int] = {}
            for g in r_ng:
                r_counts[g] = r_counts.get(g, 0) + 1
            clipped: dict[tuple[str, ...], int] = {}
            for g in c_ng:
                clipped[g] = clipped.get(g, 0) + 1
            for g, cnt in clipped.items():
                r_counts[g] = r_counts.get(g, 0) - cnt
            clip_total = sum(max(0, r_counts.get(g, 0)) for g in clipped)
            total_clip += sum(c for g, c in clipped.items()) - clip_total
            total_count += sum(c for g, c in clipped.items())

    if total_count == 0 or cand_len == 0 or ref_len == 0:
        return 0.0
    prec_num = total_clip + smooth
    prec_den = total_count + smooth
    # Average of unigram + bigram precision (n=2 micro-average).
    p = prec_num / prec_den
    bp = min(1.0, math.exp(1 - ref_len / cand_len)) if cand_len > 0 else 0.0
    bleu = bp * p
    return max(0.0, min(1.0, bleu))


def _compute_reference_metrics(
    pairs: list[tuple[str, AnalysisResult, AnalysisResult]],
    reference_path: str,
) -> dict[str, Any]:
    """Compare candidate results against a JSONL reference file.

    Args:
        pairs: The (doc_id, baseline, candidate) tuples from the eval run.
        reference_path: Path to a JSONL file with ground truth records.

    Returns:
        A dict with reference_accuracy, reference_macro_f1, and optional
        reference_summary_bleu. ``reference_n_skipped`` counts docs in
        the eval that have no reference entry.
    """
    ref = _load_reference(reference_path)

    matched = 0
    skipped = 0
    correct = 0
    f1s: list[float] = []
    cand_summaries: list[str] = []
    ref_summaries: list[str] = []

    for doc_id, _baseline, candidate in pairs:
        rec = ref.get(doc_id)
        if rec is None:
            skipped += 1
            continue
        matched += 1
        expected = _concept_set_from_strings(rec.get("expected_concepts", []))
        pred = _concept_sets(candidate)
        if pred == expected:
            correct += 1
        f1s.append(_per_doc_reference_f1(candidate, expected))
        if rec.get("expected_summary") and candidate.summary:
            ref_summaries.append(str(rec["expected_summary"]))
            cand_summaries.append(candidate.summary)

    return {
        "reference_accuracy": (correct / matched) if matched else None,
        "reference_macro_f1": _mean(f1s) if f1s else None,
        "reference_summary_bleu": (_corpus_bleu(cand_summaries, ref_summaries)
                                   if cand_summaries else None),
        "reference_n_matched": matched,
        "reference_n_skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Per-model analysis with on-disk cache
# ---------------------------------------------------------------------------

def _cache_path(root: str, model: str, doc_id: str) -> str:
    return os.path.join(root, EVAL_CACHE_DIR, model, f"{doc_id}.json")


def _load_cached(root: str, model: str, doc_id: str) -> AnalysisResult | None:
    path = _cache_path(root, model, doc_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("unreadable eval cache %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    return _result_from_dict(data)


def _save_cached(root: str, model: str, doc_id: str,
                 result: AnalysisResult) -> None:
    path = _cache_path(root, model, doc_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_result_to_dict(result), f, ensure_ascii=False, indent=2)


def _result_to_dict(result: AnalysisResult) -> dict[str, Any]:
    """Serialize an AnalysisResult to a JSON-safe dict for caching."""
    return {
        "title": result.title,
        "summary": result.summary,
        "why_important": result.why_important,
        "key_points": list(result.key_points),
        "primary_concepts": [{"id": c.id, "label": c.label}
                             for c in result.primary_concepts],
        "candidate_concepts": [{"id": c.id, "label": c.label}
                               for c in result.candidate_concepts],
        "display_tags": list(result.display_tags),
        "entities": [{"id": e.id, "label": e.label} for e in result.entities],
        "confidence": result.confidence,
        "importance": result.importance,
    }


def _result_from_dict(data: dict[str, Any]) -> AnalysisResult:
    """Rehydrate an AnalysisResult from its cached dict form."""
    return AnalysisResult(
        title=str(data.get("title", "")),
        summary=str(data.get("summary", "")),
        why_important=str(data.get("why_important", "")),
        key_points=list(data.get("key_points", [])),
        primary_concepts=[ConceptRef(id=c.get("id", ""), label=c.get("label", ""))
                          for c in data.get("primary_concepts", [])],
        candidate_concepts=[ConceptRef(id=c.get("id", ""), label=c.get("label", ""))
                            for c in data.get("candidate_concepts", [])],
        display_tags=list(data.get("display_tags", [])),
        entities=[EntityRef(id=e.get("id", ""), label=e.get("label", ""))
                  for e in data.get("entities", [])],
        confidence=float(data.get("confidence", 0.0)),
        importance=float(data.get("importance", 0.0)),
    )


def _analyze_via_model(doc_path: str, model: str) -> AnalysisResult:
    """Run the analyzer prompt for a single doc, addressed at ``model``.

    This is a thin wrapper over the analyzer's prompt + agent flow that
    overrides the model id. It does NOT call ``apply_analysis_to_doc`` —
    the cache run is read-only with respect to the live front matter.
    """
    with open(doc_path, encoding="utf-8") as f:
        text = f.read()

    m = _FM_RE.match(text)
    meta_text = m.group(1) if m else ""
    body = m.group(2).strip() if m else text
    if len(body) > _ANALYSIS_BODY_MAX_CHARS:
        body = body[:_ANALYSIS_BODY_MAX_CHARS] + "\n\n[... truncated for analysis ...]"

    def _fm(key: str, default: str = "") -> str:
        for ln in meta_text.split("\n"):
            if ln.startswith(f"{key}:"):
                return ln.split(":", 1)[1].strip().strip('"')
        return default

    title = _fm("title")
    source_type = _fm("source_type", "web")
    source_url = _fm("source") or None
    prompt = build_analysis_prompt(source_type, title, body, source_url)
    raw = call_agent(prompt, model=model)
    return parse_analysis_response(raw)


def _analyze_docs_with_model(
    root: str,
    model: str,
    doc_paths: list[str],
    use_cache: bool = True,
) -> dict[str, AnalysisResult]:
    """Run (or load from cache) the analysis for each doc with the given model.

    Args:
        root: Bucket root; the cache lives under ``.kb/models/eval/cache/``.
        model: The model id to invoke (raw upstream id or registered slug;
            see ``_resolve_upstream_id`` for slug resolution).
        doc_paths: Absolute paths to ``records/doc/**/*.md`` files.
        use_cache: When True, skip calls whose result is already cached.

    Returns:
        A mapping of ``doc_id`` -> ``AnalysisResult``. Doc ids are derived
        from the file's front-matter ``id`` field; if absent, the file
        stem is used as a fallback.
    """
    results: dict[str, AnalysisResult] = {}
    misses: list[tuple[str, str]] = []  # (doc_id, doc_path)
    for path in doc_paths:
        doc_id = _doc_id_from_path(path)
        if not doc_id:
            continue
        if use_cache:
            cached = _load_cached(root, model, doc_id)
            if cached is not None:
                results[doc_id] = cached
                continue
        misses.append((doc_id, path))

    for doc_id, path in misses:
        try:
            r = _analyze_via_model(path, model)
        except Exception as e:  # noqa: BLE001 — surface to caller
            logger.warning("analyze_via_model failed for %s (%s): %s",
                           doc_id, path, e)
            r = AnalysisResult()  # empty result; will count as failure
        # Only cache usable results so a transient LLM failure does not
        # poison the cache for subsequent runs.
        if not _is_failure(r):
            _save_cached(root, model, doc_id, r)
        results[doc_id] = r
    return results


# ---------------------------------------------------------------------------
# Document discovery and sampling
# ---------------------------------------------------------------------------

def _doc_id_from_path(path: str) -> str:
    """Extract the doc id from a record's front matter (fallback: filename)."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    m = re.search(r"^id:\s*(\S+)", text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return os.path.splitext(os.path.basename(path))[0]


def _has_analysis(path: str) -> bool:
    """Return True if the doc has an analysis.confidence in its front matter."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return False
    m = _FM_RE.match(text)
    if not m:
        return False
    meta = m.group(1)
    # Look for `analysis:` block containing a `confidence:` line.
    in_analysis = False
    for ln in meta.split("\n"):
        if ln.startswith("analysis:"):
            in_analysis = True
            continue
        if in_analysis:
            if not ln.startswith(" "):
                in_analysis = False
                continue
            if ln.strip().startswith("confidence:"):
                return True
    return False


def discover_analyzed_docs(root: str) -> list[str]:
    """Walk ``records/doc/`` and return paths to docs with an analysis block.

    Un-analyzed docs are skipped because comparing a model run against
    no analysis produces no signal. Paths are returned in deterministic
    order (sorted) so a downstream sample is stable before seeding.
    """
    doc_dir = os.path.join(root, RECORDS_DIR, DOC_DIR)
    out: list[str] = []
    for dp, _dn, fns in os.walk(doc_dir):
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(dp, fn)
            if _has_analysis(p):
                out.append(p)
    out.sort()
    return out


def _stable_sample(paths: list[str], limit: int, seed_key: str) -> list[str]:
    """Sample up to ``limit`` paths using a seed derived from ``seed_key``.

    The seed is ``sha256(seed_key)[:8]`` interpreted as a 32-bit int so
    repeat runs with the same seed_key return the same sample.
    """
    if limit is None or limit >= len(paths):
        return paths
    digest = hashlib.sha256(seed_key.encode()).digest()[:4]
    seed = int.from_bytes(digest, "big")
    rng = random.Random(seed)
    sample = list(paths)
    rng.shuffle(sample)
    return sample[:limit]


# ---------------------------------------------------------------------------
# Doc-body reader (for the judge)
# ---------------------------------------------------------------------------

def _doc_body(path: str) -> str:
    """Return the doc body (post front matter) for the judge prompt."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    m = _FM_RE.match(text)
    if not m:
        return text
    return m.group(2).strip()


# ---------------------------------------------------------------------------
# Model id resolution
# ---------------------------------------------------------------------------

def _resolve_upstream_id(model_ref: str, root: str) -> str:
    """Resolve a CLI model reference to an upstream model id.

    If ``model_ref`` matches a registered model id, return its
    ``base_model``. Otherwise return ``model_ref`` unchanged (treat it
    as a raw upstream id the proxy can handle directly).
    """
    try:
        from . import models as _models
        rec = _models.show(model_ref, root=root)
        if rec and rec.get("base_model"):
            return rec["base_model"]
    except Exception:  # noqa: BLE001
        pass
    return model_ref


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------

def _save_eval_report(root: str, model_id: str, report: dict[str, Any]) -> None:
    """Persist the eval report via ``models.eval_record``."""
    from . import models as _models

    ensure_models_dirs(root)
    _models.eval_record(model_id, report, root=root, overwrite=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_eval(
    baseline_model: str,
    candidate_model: str,
    root: str,
    limit: int | None = None,
    reference_path: str | None = None,
    use_cache: bool = True,
    judge_model: str | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    """Run a full eval of ``candidate_model`` against ``baseline_model``.

    Args:
        baseline_model: Either a registered model slug or a raw upstream id.
        candidate_model: Same shape as ``baseline_model``.
        root: Bucket root. Used for both the doc tree and the cache.
        limit: Optional cap on doc count. The sample is deterministic
            given the (baseline, candidate) pair.
        reference_path: Optional JSONL file with ground truth.
        use_cache: When True, reuse cached per-(model, doc) analyses.
        judge_model: Optional model id override for the LLM judge.
        workers: Parallel worker count for LLM calls (analyze + judge).

    Returns:
        The full eval report dict (also written to
        ``.kb/models/eval/<candidate>.json`` via ``_save_eval_report``).
    """
    if root is None:
        raise FileNotFoundError("not in a knowledge bucket (kb_root is None)")

    baseline_id = _resolve_upstream_id(baseline_model, root)
    candidate_id = _resolve_upstream_id(candidate_model, root)

    docs = discover_analyzed_docs(root)
    seed_key = f"{baseline_id}|{candidate_id}"
    if limit is not None:
        docs = _stable_sample(docs, limit, seed_key)

    if not docs:
        return _empty_report(baseline_model, candidate_model, baseline_id,
                             candidate_id, judge_model, limit,
                             reference_path, use_cache)

    # Build a doc_id -> body map for the judge prompt.
    bodies: dict[str, str] = {(_doc_id_from_path(p)): _doc_body(p) for p in docs}

    baseline_results = _analyze_docs_with_model(root, baseline_id, docs,
                                                use_cache=use_cache)
    candidate_results = _analyze_docs_with_model(root, candidate_id, docs,
                                                 use_cache=use_cache)

    # Align pairs on doc_id; skip docs missing from either side.
    pairs: list[tuple[str, AnalysisResult, AnalysisResult]] = []
    for path in docs:
        doc_id = _doc_id_from_path(path)
        if doc_id in baseline_results and doc_id in candidate_results:
            pairs.append((doc_id, baseline_results[doc_id],
                          candidate_results[doc_id]))

    concept = _compute_concept_metrics(pairs)
    importance = _compute_importance_kl(
        [b for _d, b, _c in pairs], [c for _d, _b, c in pairs])
    failures = _compute_failure_rates(pairs)

    judge_pairs: list[tuple[str, AnalysisResult, AnalysisResult, str]] = [
        (d, b, c, bodies.get(d, "")) for d, b, c in pairs
    ]
    judge = _compute_judge_scores(judge_pairs, judge_model=judge_model,
                                  workers=workers)

    metrics: dict[str, Any] = {
        "concept_jaccard_mean": concept["concept_jaccard_mean"],
        "concept_f1_mean": concept["concept_f1_mean"],
        "concept_precision_mean": concept["concept_precision_mean"],
        "concept_recall_mean": concept["concept_recall_mean"],
        **importance,
        "judge_score_mean": judge["judge_score_mean"],
        "judge_score_median": judge["judge_score_median"],
        "judge_score_dist": judge["judge_score_dist"],
        "judge_failures": judge["judge_failures"],
        **failures,
    }
    if reference_path:
        ref_metrics = _compute_reference_metrics(pairs, reference_path)
        metrics.update(ref_metrics)
    else:
        metrics.update({
            "reference_accuracy": None,
            "reference_macro_f1": None,
            "reference_summary_bleu": None,
            "reference_n_matched": 0,
            "reference_n_skipped": 0,
        })

    per_doc = _merge_per_doc(concept["per_doc"], judge["judge_per_doc"],
                             baseline_results, candidate_results)

    report: dict[str, Any] = {
        "model_id": candidate_model,
        "baseline": baseline_model,
        "candidate": candidate_model,
        "baseline_resolved": baseline_id,
        "candidate_resolved": candidate_id,
        "judge_model": judge_model,
        "n_docs": len(pairs),
        "limit": limit,
        "reference_path": reference_path,
        "cache_used": use_cache,
        "judged_at": _now_iso(),
        "metrics": _round_metrics(metrics),
        "per_doc": per_doc,
        "failures": failures["failures"],
    }

    _save_eval_report(root, candidate_model, report)
    return report


# ---------------------------------------------------------------------------
# Helpers used by the public API
# ---------------------------------------------------------------------------

def _empty_report(
    baseline_model: str,
    candidate_model: str,
    baseline_id: str,
    candidate_id: str,
    judge_model: str | None,
    limit: int | None,
    reference_path: str | None,
    use_cache: bool,
) -> dict[str, Any]:
    return {
        "model_id": candidate_model,
        "baseline": baseline_model,
        "candidate": candidate_model,
        "baseline_resolved": baseline_id,
        "candidate_resolved": candidate_id,
        "judge_model": judge_model,
        "n_docs": 0,
        "limit": limit,
        "reference_path": reference_path,
        "cache_used": use_cache,
        "judged_at": _now_iso(),
        "metrics": _round_metrics({
            "concept_jaccard_mean": 0.0,
            "concept_f1_mean": 0.0,
            "concept_precision_mean": 0.0,
            "concept_recall_mean": 0.0,
            "importance_kl": 0.0,
            "importance_js": 0.0,
            "importance_histogram_baseline": [0] * _IMPORTANCE_BINS,
            "importance_histogram_candidate": [0] * _IMPORTANCE_BINS,
            "judge_score_mean": None,
            "judge_score_median": None,
            "judge_score_dist": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0},
            "judge_failures": 0,
            "baseline_failure_rate": 0.0,
            "candidate_failure_rate": 0.0,
            "failure_rate_delta": 0.0,
            "reference_accuracy": None,
            "reference_macro_f1": None,
            "reference_summary_bleu": None,
            "reference_n_matched": 0,
            "reference_n_skipped": 0,
        }),
        "per_doc": [],
        "failures": [],
    }


def _merge_per_doc(
    concept_per_doc: list[dict[str, Any]],
    judge_per_doc: list[dict[str, Any]],
    baseline_results: dict[str, AnalysisResult],
    candidate_results: dict[str, AnalysisResult],
) -> list[dict[str, Any]]:
    """Combine concept + judge + failure info into a per-doc record list."""
    judge_by_id: dict[str, dict[str, Any]] = {
        p["doc_id"]: p for p in judge_per_doc
    }
    out: list[dict[str, Any]] = []
    for cpd in concept_per_doc:
        doc_id = cpd["doc_id"]
        b = baseline_results.get(doc_id)
        c = candidate_results.get(doc_id)
        jp = judge_by_id.get(doc_id, {})
        out.append({
            "doc_id": doc_id,
            "concept_jaccard": cpd["jaccard"],
            "concept_f1": cpd["f1"],
            "baseline_concepts": cpd["A"],
            "candidate_concepts": cpd["B"],
            "baseline_importance": (float(b.importance) if b else None),
            "candidate_importance": (float(c.importance) if c else None),
            "judge_score": jp.get("score"),
            "judge_reasoning": jp.get("reasoning", ""),
            "baseline_failed": _is_failure(b) if b else True,
            "candidate_failed": _is_failure(c) if c else True,
        })
    return out


def _round_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Round numeric metrics to 4 decimals; keep the schema otherwise intact."""
    out: dict[str, Any] = {}
    for k, v in metrics.items():
        if isinstance(v, float):
            out[k] = round(v, 4)
        else:
            out[k] = v
    return out


def _mean(values) -> float:
    """Arithmetic mean of a non-empty iterable; 0.0 for an empty input."""
    items = list(values)
    if not items:
        return 0.0
    return sum(items) / len(items)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
