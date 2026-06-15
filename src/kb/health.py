"""Graph health metrics for knowledge bucket."""

import json
import os
import sqlite3
from typing import Any

from .core import DOC_DIR, RECORDS_DIR
from .graph import compute_hub_threshold, init_graph_tables
from .index import _FM_RE, index_path


def compute_health(root: str, *, with_models: bool = False) -> dict:
    """Compute graph health metrics from the index database.

    Args:
        root: Bucket root path.
        with_models: When True, also gather eval reports from
            ``.kb/models/eval/*.json`` and add a ``model_evals`` key to
            the report. The key is always present (an empty list) so
            downstream consumers don't need to special-case "missing".

    Returns:
        A dict with overview stats, distributions, and quality indicators.
        When ``with_models=True`` the returned dict also includes
        ``model_evals`` (a list of {model_id, baseline, judged_at,
        n_docs, metrics} records sorted by ``judged_at`` desc).
    """
    db_path = index_path(root)
    if not os.path.exists(db_path):
        return {"error": "No index database found. Run 'kb graph build' first."}

    conn = sqlite3.connect(db_path)
    try:
        report = _gather_metrics(conn, root)
    finally:
        conn.close()

    if with_models:
        report["model_evals"] = _gather_model_evals(root)
    return report


def _gather_metrics(conn: sqlite3.Connection, root: str) -> dict:
    init_graph_tables(conn)
    # Overview counts
    total_docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
    total_concepts = conn.execute(
        "SELECT COUNT(*) FROM concepts WHERE is_stop = 0"
    ).fetchone()[0]
    total_edges = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'related'"
    ).fetchone()[0]
    concept_edges = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE edge_type = 'cooccurrence'"
    ).fetchone()[0]

    # Orphan documents: docs with no concepts
    orphan_docs = conn.execute(
        "SELECT COUNT(*) FROM docs d "
        "WHERE d.id NOT IN (SELECT DISTINCT doc_id FROM doc_concepts)"
    ).fetchone()[0]

    # Isolated docs: docs with no edges to other docs
    isolated_docs = conn.execute(
        "SELECT COUNT(*) FROM docs d "
        "WHERE d.id NOT IN (SELECT DISTINCT src_id FROM edges WHERE edge_type = 'related') "
        "AND d.id NOT IN (SELECT DISTINCT dst_id FROM edges WHERE edge_type = 'related')"
    ).fetchone()[0]

    # Source type breakdown
    source_types = {}
    for row in conn.execute(
        "SELECT source_type, COUNT(*) FROM docs GROUP BY source_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        source_types[row[0]] = row[1]

    # Importance distribution
    importance_buckets = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    for row in conn.execute("SELECT importance FROM doc_stats").fetchall():
        imp = row[0]
        if imp >= 0.7:
            importance_buckets["high"] += 1
        elif imp >= 0.4:
            importance_buckets["medium"] += 1
        elif imp > 0.0:
            importance_buckets["low"] += 1
        else:
            importance_buckets["unscored"] += 1
    importance_buckets["unscored"] += max(0, total_docs - conn.execute(
        "SELECT COUNT(*) FROM doc_stats"
    ).fetchone()[0])

    # Top concepts by document frequency
    top_concepts = []
    for row in conn.execute(
        "SELECT concept_id, label, df FROM concepts "
        "WHERE is_stop = 0 AND df > 0 "
        "ORDER BY df DESC LIMIT 20"
    ).fetchall():
        top_concepts.append({"id": row[0], "label": row[1], "df": row[2]})

    # Concepts with high df but no note file
    concept_dir = os.path.join(root, RECORDS_DIR, "concept")
    concepts_missing_notes = 0
    for row in conn.execute(
        "SELECT concept_id FROM concepts WHERE is_stop = 0 AND df >= 2"
    ).fetchall():
        note_path = os.path.join(concept_dir, f"{row[0]}.md")
        if not os.path.exists(note_path):
            concepts_missing_notes += 1

    # Average concepts per document
    avg_concepts = conn.execute(
        "SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM doc_concepts GROUP BY doc_id)"
    ).fetchone()[0] or 0.0

    # Average edges per document
    avg_edges = conn.execute(
        "SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM edges "
        "WHERE edge_type = 'related' GROUP BY src_id)"
    ).fetchone()[0] or 0.0

    # Connectivity ratio: docs that have at least one edge
    connected_docs = total_docs - isolated_docs
    connectivity_ratio = connected_docs / total_docs if total_docs > 0 else 0.0

    # Hub concepts: concepts exceeding dynamic hub threshold (GOAL.md section 10)
    hub_threshold = compute_hub_threshold(conn)
    hub_concepts = []
    for row in conn.execute(
        "SELECT concept_id, label, df FROM concepts "
        "WHERE is_stop = 0 AND df > ? "
        "ORDER BY df DESC LIMIT 20",
        (hub_threshold,),
    ).fetchall():
        hub_concepts.append({"id": row[0], "label": row[1], "df": row[2]})

    # Duplicate rate: scan documents for duplicate content_hash (GOAL.md section 23)
    doc_dir = os.path.join(root, RECORDS_DIR, DOC_DIR)
    hash_to_count: dict[str, int] = {}
    for dirpath, _dirnames, filenames in os.walk(doc_dir):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            filepath = os.path.join(dirpath, fn)
            try:
                with open(filepath) as f:
                    text = f.read()
            except OSError:
                continue
            m = _FM_RE.match(text)
            if m:
                for line in m.group(1).split("\n"):
                    if line.startswith("content_hash:"):
                        ch = line.split(":", 1)[1].strip()
                        hash_to_count[ch] = hash_to_count.get(ch, 0) + 1
                        break

    duplicate_docs = sum(c - 1 for c in hash_to_count.values() if c > 1)
    duplicate_rate = round(duplicate_docs / total_docs, 4) if total_docs > 0 else 0.0

    # Max degree: most related-edges any single document participates in (section 23)
    max_degree = conn.execute(
        "SELECT MAX(degree) FROM ("
        "  SELECT id, SUM(cnt) as degree FROM ("
        "    SELECT src_id as id, COUNT(*) as cnt FROM edges "
        "    WHERE edge_type = 'related' GROUP BY src_id"
        "    UNION ALL"
        "    SELECT dst_id as id, COUNT(*) as cnt FROM edges "
        "    WHERE edge_type = 'related' GROUP BY dst_id"
        "  ) GROUP BY id"
        ")"
    ).fetchone()[0] or 0

    return {
        "overview": {
            "total_documents": total_docs,
            "total_concepts": total_concepts,
            "total_edges": total_edges,
            "concept_edges": concept_edges,
            "orphan_documents": orphan_docs,
            "isolated_documents": isolated_docs,
            "hub_threshold": hub_threshold,
        },
        "source_types": source_types,
        "importance_distribution": importance_buckets,
        "top_concepts": top_concepts,
        "hub_concepts": hub_concepts,
        "concepts_missing_notes": concepts_missing_notes,
        "metrics": {
            "avg_concepts_per_doc": round(avg_concepts, 2),
            "avg_edges_per_doc": round(avg_edges, 2),
            "connectivity_ratio": round(connectivity_ratio, 3),
            "duplicate_rate": duplicate_rate,
            "max_degree": max_degree,
        },
    }


# ---------------------------------------------------------------------------
# Model eval reports (Phase 13.2)
# ---------------------------------------------------------------------------

# Headline metrics surfaced per eval record. These are the four metrics
# the eval pipeline always computes; reference_* are excluded because
# they are not part of every run.
_HEADLINE_METRICS = (
    "concept_jaccard_mean",
    "concept_f1_mean",
    "importance_kl",
    "judge_score_mean",
)


def _gather_model_evals(root: str) -> list[dict[str, Any]]:
    """Read ``.kb/models/eval/*.json`` and return a summary list.

    Each entry has the shape:
        ``{model_id, baseline, judged_at, n_docs, metrics}``

    where ``metrics`` is itself a dict with the four headline metrics
    (``concept_jaccard_mean``, ``concept_f1_mean``, ``importance_kl``,
    ``judge_score_mean``). Records are sorted by ``judged_at`` desc
    (most recent first); entries with no ``judged_at`` sort to the end.

    An empty list is returned when the directory is missing or contains
    no readable JSON files.
    """
    eval_dir = os.path.join(root, ".kb", "models", "eval")
    if not os.path.isdir(eval_dir):
        return []

    out: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(eval_dir)):
        if not entry.endswith(".json"):
            continue
        path = os.path.join(eval_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            # Skip unreadable files but keep the rest.
            import logging
            logging.getLogger(__name__).warning(
                "skipping unreadable eval file %s: %s", path, e)
            continue
        if not isinstance(rec, dict):
            continue
        model_id = rec.get("model_id") or os.path.splitext(entry)[0]
        all_metrics = rec.get("metrics") or {}
        metrics = {k: all_metrics.get(k) for k in _HEADLINE_METRICS}
        out.append({
            "model_id": model_id,
            "baseline": rec.get("baseline"),
            "judged_at": rec.get("judged_at"),
            "n_docs": rec.get("n_docs"),
            "metrics": metrics,
        })

    out.sort(key=lambda r: r.get("judged_at") or "", reverse=True)
    return out
