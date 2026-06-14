"""Model registry: CRUD for fine-tuned model metadata.

Public API:
    add(id, base_model, dataset_path, backend, notes=None) -> dict
    list_all() -> list[dict]
    show(model_id) -> dict | None
    use(model_id) -> None
    get_default() -> dict | None
    eval_record(model_id, eval_data) -> None

Storage:
    .kb/models/<id>.json       — one file per registered model
    .kb/models/eval/<id>.json  — one file per model eval results

The module is purely file I/O; it does not invoke any LLM and is safe to
import from any context (cli, analyzer, web). Callers are responsible for
providing a bucket ``root``; helpers inside this module resolve it lazily
so the module can also be called from places where the bucket root is
already known.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

from .core import AGENT_MODEL_KEY, get_config_value, kb_root, set_config_value

logger = logging.getLogger(__name__)

# Slug rule from the design: [a-z0-9][a-z0-9_-]{0,63}. Hyphen and underscore
# allowed after the first character; uppercase and whitespace forbidden.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Closed set of backends; informational only (determines the next training
# command) but enforced so a typo doesn't silently sneak into the registry.
VALID_BACKENDS = ("openai_ft", "local_lora", "unsloth", "external")

# Storage layout. Kept as module constants so callers can introspect them
# in tests without hardcoding paths.
MODELS_DIR = ".kb/models"
EVAL_SUBDIR = "eval"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add(
    id: str,
    base_model: str,
    dataset_path: str,
    backend: str,
    notes: str | None = None,
    *,
    root: str | None = None,
    overwrite: bool = False,
    display_name: str = "",
    provider_model_id: str = "",
    provider_job_id: str = "",
    tags: list[str] | None = None,
    extra: dict | None = None,
) -> dict:
    """Register a fine-tuned model and write ``.kb/models/<id>.json``.

    Args:
        id: Slug for the model. Must match the slug regex; also used as
            the filename.
        base_model: Upstream model id used for fine-tuning (the one
            ``analyzer`` will request when this model is active).
        dataset_path: Path to the training dataset, relative to ``root``
            when possible.
        backend: One of ``VALID_BACKENDS``.
        notes: Free-form notes persisted into the model file.
        root: Bucket root. Defaults to ``kb_root()`` when not provided.
        overwrite: Replace an existing model with the same id.
        display_name: Human-readable label.
        provider_model_id: Provider-returned model id (e.g. ``ft:...``).
        provider_job_id: Provider-returned job id.
        tags: List of free-form tag strings.
        extra: Additional JSON-serializable fields to merge into the
            record (e.g. ``hyperparams``, ``eval_scores``). Keys that the
            canonical schema manages are ignored; everything else is kept.

    Returns:
        The full record dict that was written to disk.

    Raises:
        ValueError: If ``id`` is not a valid slug, ``backend`` is not in
            the closed set, or a model with the same id exists and
            ``overwrite`` is not set.
        FileNotFoundError: If ``root`` cannot be resolved.
    """
    if not _SLUG_RE.match(id):
        raise ValueError(
            f"invalid model id {id!r}: must match [a-z0-9][a-z0-9_-]{{0,63}}"
        )
    if backend not in VALID_BACKENDS:
        raise ValueError(
            f"backend must be one of {VALID_BACKENDS}, got {backend!r}"
        )
    if root is None:
        root = kb_root()
    if root is None:
        raise FileNotFoundError("not in a knowledge bucket (kb_root is None)")

    target = _model_path(root, id)
    if os.path.exists(target) and not overwrite:
        raise ValueError(
            f"model {id!r} already exists at {target}; "
            f"pass overwrite=True to replace"
        )

    now = _now_iso()
    record: dict[str, Any] = {
        "id": id,
        "display_name": display_name or id,
        "base_model": base_model,
        "backend": backend,
        "created_at": now,
        "updated_at": now,
        "dataset_path": dataset_path,
        "notes": notes or "",
        "tags": list(tags or []),
    }
    if provider_model_id:
        record["provider_model_id"] = provider_model_id
    if provider_job_id:
        record["provider_job_id"] = provider_job_id
    if extra:
        for k, v in extra.items():
            if k in record:
                continue
            record[k] = v

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


def list_all(*, root: str | None = None, tag: str | None = None) -> list[dict]:
    """Return every registered model.

    Args:
        root: Bucket root. Defaults to ``kb_root()``.
        tag: If provided, only models whose ``tags`` list contains this
            string are returned.

    Returns:
        A list of model record dicts, sorted by ``id`` for deterministic
        output. An empty list is returned when the bucket has no models
        or when the models directory does not exist.
    """
    root = root or kb_root()
    if root is None:
        return []
    models_dir = os.path.join(root, MODELS_DIR)
    if not os.path.isdir(models_dir):
        return []
    out: list[dict] = []
    for entry in sorted(os.listdir(models_dir)):
        if not entry.endswith(".json"):
            continue
        path = os.path.join(models_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("skipping unreadable model file %s: %s", path, e)
            continue
        if not isinstance(rec, dict):
            continue
        if tag is not None:
            tags = rec.get("tags") or []
            if not isinstance(tags, list) or tag not in tags:
                continue
        out.append(rec)
    out.sort(key=lambda r: r.get("id", ""))
    return out


def show(model_id: str, *, root: str | None = None) -> dict | None:
    """Return the record for ``model_id``, or ``None`` if it does not exist."""
    root = root or kb_root()
    if root is None:
        return None
    path = _model_path(root, model_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    return rec


def use(model_id: str, *, root: str | None = None) -> None:
    """Mark ``model_id`` as the active agent model.

    Writes ``agent_model: <id>`` to config/kb.yml. Raises if the model is
    not registered — use ``get_default()`` to read the current value.

    Raises:
        FileNotFoundError: If the model is not registered or ``root`` is
            not a bucket.
    """
    root = root or kb_root()
    if root is None:
        raise FileNotFoundError("not in a knowledge bucket (kb_root is None)")
    if show(model_id, root=root) is None:
        raise FileNotFoundError(
            f"model {model_id!r} is not registered; run 'kb models add' first"
        )
    set_config_value(root, AGENT_MODEL_KEY, model_id)


def get_default(*, root: str | None = None) -> dict | None:
    """Return the model record currently marked active in kb.yml.

    Returns ``None`` when no model is active, when the configured id is
    empty, or when the configured id is not registered (dangling config).
    """
    root = root or kb_root()
    if root is None:
        return None
    active = get_config_value(root, AGENT_MODEL_KEY, default="")
    if not active:
        return None
    rec = show(active, root=root)
    if rec is None:
        logger.warning(
            "config/kb.yml names agent_model=%r but no such model is registered",
            active,
        )
    return rec


def eval_record(
    model_id: str,
    eval_data: dict,
    *,
    root: str | None = None,
    overwrite: bool = True,
) -> dict:
    """Persist eval results for ``model_id`` to ``.kb/models/eval/<id>.json``.

    The eval file is intentionally separate from the model metadata file:
    the model record holds identifying info, the eval file holds the
    empirical results. This keeps re-runs of the same eval from clobbering
    the registration entry.

    Args:
        model_id: Slug of the registered model.
        eval_data: Free-form dict (e.g. ``{"val_pairs": 62, "rougeL": 0.78}``).
        root: Bucket root. Defaults to ``kb_root()``.
        overwrite: When True, replace any existing eval file. When False,
            merge with the existing record (new keys win).

    Returns:
        The eval record that was written.
    """
    root = root or kb_root()
    if root is None:
        raise FileNotFoundError("not in a knowledge bucket (kb_root is None)")
    path = _eval_path(root, model_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    record: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            try:
                record = json.load(f) or {}
            except json.JSONDecodeError:
                record = {}
    if overwrite:
        record = dict(eval_data)
    else:
        record.update(eval_data)
    record["model_id"] = model_id
    record["recorded_at"] = _now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model_path(root: str, model_id: str) -> str:
    return os.path.join(root, MODELS_DIR, f"{model_id}.json")


def _eval_path(root: str, model_id: str) -> str:
    return os.path.join(root, MODELS_DIR, EVAL_SUBDIR, f"{model_id}.json")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
