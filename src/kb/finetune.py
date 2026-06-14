"""Fine-tuning dataset preparation and job submission.

Public API:
    prepare(dataset_path, output_dir, format) -> dict
        Convert an SFT JSONL into HF / OpenAI / Alpaca format. Streams
        records through the matching converter and returns a summary with
        counts and output paths.

    submit(dataset_path, base_model, backend) -> dict
        Record a fine-tune run under .kb/finetune/<job_id>/. Pure file I/O —
        does not invoke any external training process. The actual training
        call is delegated to OpenAI / local trainers / HTTP endpoints and
        is out of scope for this module.

The module never calls subprocess; it only writes JSONL files and a
job directory. CLI commands and orchestration code in cli.py consume the
return values.
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from .core import generate_ulid

logger = logging.getLogger(__name__)

# Public format identifiers. Keep in sync with the format converters below.
SUPPORTED_FORMATS = ("hf", "openai", "alpaca")

# Backend identifiers accepted by ``submit`` — informational only, but kept
# as a closed set so the recorded job.json is predictable.
SUPPORTED_BACKENDS = ("openai_ft", "local_lora", "unsloth", "external")

# Where submit() drops the per-job record. Kept as a literal (not a constant
# in core.py) because the public API in this phase is the function, not the
# directory path. Integration phase may promote to core.FINETUNE_DIR.
_DEFAULT_FINETUNE_DIR = ".kb/finetune"


# ---------------------------------------------------------------------------
# Record converters (private)
# ---------------------------------------------------------------------------

_META_KEYS = ("_source_doc", "_difficulty", "_tags")


def _split_messages(messages: list[dict]) -> tuple[str | None, str, str]:
    """Return (system, user, assistant) from an OpenAI-format messages list.

    Skips entries with unexpected shapes; missing roles default to empty
    strings. The training data we produce always has exactly one of each,
    but downstream consumers may not.
    """
    system: str | None = None
    user = ""
    assistant = ""
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content", "")
        if role == "system" and system is None:
            system = content
        elif role == "user" and not user:
            user = content
        elif role == "assistant" and not assistant:
            assistant = content
    return system, user, assistant


def _extract_meta(record: dict) -> dict:
    """Pull the kb-specific metadata fields off a record, in canonical form."""
    out: dict[str, Any] = {}
    if "_source_doc" in record:
        out["source_doc"] = record["_source_doc"]
    if "_difficulty" in record:
        out["difficulty"] = record["_difficulty"]
    if "_tags" in record:
        out["tags"] = record["_tags"]
    return out


def to_hf(record: dict) -> dict:
    """Convert a record to the HF datasets format.

    Drops the ``_`` prefix on metadata (datasets treats underscore-prefixed
    keys as private), keeps ``system`` as a top-level field for trainers
    that want a separate column, and keeps the user/assistant pair in
    ``messages`` so a Trainer can index into roles.
    """
    messages = record.get("messages") or []
    system, user, assistant = _split_messages(messages)
    out: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "system": system,
    }
    out.update(_extract_meta(record))
    return out


def to_openai(record: dict) -> dict:
    """Convert a record to OpenAI fine-tune JSONL format.

    OpenAI's fine-tuning endpoint only honors the ``messages`` key; extra
    fields at the top level are ignored (with a noisy warning). Strip
    everything else so the file is clean.
    """
    messages = record.get("messages") or []
    _, user, assistant = _split_messages(messages)
    out: dict[str, Any] = {
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }
    # Preserve a system prompt verbatim if one was present in the source.
    if messages:
        for m in messages:
            if isinstance(m, dict) and m.get("role") == "system":
                out["messages"].insert(
                    0, {"role": "system", "content": m.get("content", "")}
                )
                break
    # Defensive: if the source had no user/assistant, keep the original
    # messages list (still dict-shaped) so the data isn't silently emptied.
    if not user and not assistant:
        out["messages"] = [m for m in messages if isinstance(m, dict)]
    return out


def to_alpaca(record: dict) -> dict:
    """Convert a record to Alpaca JSONL format.

    ``instruction`` = system + "\\n\\n" + user so the model sees the system
    prompt during training, matching how the OpenAI format conditions it.
    Dropped metadata goes into a single ``_kb_meta`` field that most Alpaca
    trainers ignore.
    """
    messages = record.get("messages") or []
    system, user, assistant = _split_messages(messages)
    if system:
        instruction = f"{system}\n\n{user}".strip()
    else:
        instruction = user
    meta = _extract_meta(record)
    out: dict[str, Any] = {
        "instruction": instruction,
        "input": "",
        "output": assistant,
    }
    if meta:
        out["_kb_meta"] = meta
    return out


_CONVERTERS = {
    "hf": to_hf,
    "openai": to_openai,
    "alpaca": to_alpaca,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def prepare(dataset_path: str, output_dir: str, format: str) -> dict:
    """Convert a JSONL dataset into the requested fine-tune format.

    Args:
        dataset_path: Path to the source JSONL. The file must exist.
        output_dir: Directory to write the converted file(s) into. Created
            if it does not exist.
        format: One of "hf", "openai", "alpaca".

    Returns:
        Dict with keys: ``format``, ``source``, ``output_dir``, ``count``,
        ``output_path``, ``had_meta`` (whether any source record carried
        kb-specific metadata).
    """
    if format not in _CONVERTERS:
        raise ValueError(
            f"format must be one of {SUPPORTED_FORMATS}, got {format!r}"
        )
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    os.makedirs(output_dir, exist_ok=True)
    converter = _CONVERTERS[format]

    out_name = _output_filename(dataset_path, format)
    out_path = os.path.join(output_dir, out_name)

    count = 0
    had_meta = False
    with open(dataset_path, encoding="utf-8") as src, \
            open(out_path, "w", encoding="utf-8") as dst:
        for ln in src:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError as e:
                logger.warning("skipping malformed JSONL line: %s", e)
                continue
            if not isinstance(rec, dict):
                logger.warning("skipping non-object JSONL line")
                continue
            if any(k in rec for k in _META_KEYS):
                had_meta = True
            out = converter(rec)
            dst.write(json.dumps(out, ensure_ascii=False) + "\n")
            count += 1

    return {
        "format": format,
        "source": dataset_path,
        "output_dir": output_dir,
        "output_path": out_path,
        "count": count,
        "had_meta": had_meta,
    }


def submit(
    dataset_path: str,
    base_model: str,
    backend: str,
    *,
    output_model_id: str | None = None,
    hyperparams: dict | None = None,
    notes: str = "",
    finetune_dir: str | None = None,
    root: str | None = None,
) -> dict:
    """Record a fine-tune run under .kb/finetune/<job_id>/.

    The actual training call is delegated to an external system (OpenAI,
    local trainer, HTTP endpoint). This function only persists the
    canonical record and a short README describing how to launch the job.

    Args:
        dataset_path: Path to the dataset that will be (or was) used.
        base_model: Upstream model id being fine-tuned from.
        backend: One of ``SUPPORTED_BACKENDS``.
        output_model_id: Slug under which the resulting model will be
            registered. Optional — the user may register later via
            ``kb models add --from-job <job_id>``.
        hyperparams: Optional dict of training hyperparameters stored on
            the job record (n_epochs, lr, batch_size, lora, lora_r, ...).
        notes: Free-form notes persisted into job.json.
        finetune_dir: Override the output directory (defaults to
            ``.kb/finetune``). If ``root`` is provided, the directory is
            resolved as ``<root>/.kb/finetune``; otherwise ``finetune_dir``
            is treated as an absolute path.
        root: Bucket root, used to resolve the default finetune dir.

    Returns:
        Dict with keys: ``job_id``, ``workdir``, ``job_path``,
        ``status_path``, ``readme_path``, ``config_snapshot_path``,
        ``base_model``, ``backend``, ``dataset_path``,
        ``output_model_id``, ``hyperparams``, ``notes``, ``command_hint``,
        ``created_at``.
    """
    if backend not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"backend must be one of {SUPPORTED_BACKENDS}, got {backend!r}"
        )
    if not dataset_path:
        raise ValueError("dataset_path is required")
    if not base_model:
        raise ValueError("base_model is required")

    if finetune_dir is None:
        if root is None:
            raise ValueError("either finetune_dir or root must be provided")
        finetune_dir = os.path.join(root, _DEFAULT_FINETUNE_DIR)

    hp = dict(hyperparams or {})
    job_id = generate_ulid()
    created_at = _now_iso()
    workdir = os.path.join(finetune_dir, job_id)
    os.makedirs(workdir, exist_ok=True)

    job = {
        "job_id": job_id,
        "created_at": created_at,
        "status": "submitted",
        "base_model": base_model,
        "backend": backend,
        "dataset": {
            "path": dataset_path,
            "format": _infer_input_format(dataset_path),
        },
        "hyperparams": hp,
        "output_model_id": output_model_id,
        "notes": notes,
        "command_hint": _command_hint(backend, base_model, dataset_path),
    }

    job_path = os.path.join(workdir, "job.json")
    config_snapshot_path = os.path.join(workdir, "config.json")
    readme_path = os.path.join(workdir, "README.md")
    status_path = os.path.join(workdir, "status.log")

    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)

    # config.json snapshots the resolved config so a future orchestrator can
    # replay the job without re-deriving values from the user.
    snapshot = {
        "job_id": job_id,
        "base_model": base_model,
        "backend": backend,
        "hyperparams": hp,
        "dataset_path": dataset_path,
        "output_model_id": output_model_id,
    }
    with open(config_snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    readme = _build_readme(job)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)

    with open(status_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"ts": created_at, "event": "submitted",
                            "by": "user"}, ensure_ascii=False) + "\n")

    return {
        "job_id": job_id,
        "workdir": workdir,
        "job_path": job_path,
        "status_path": status_path,
        "readme_path": readme_path,
        "config_snapshot_path": config_snapshot_path,
        "base_model": base_model,
        "backend": backend,
        "dataset_path": dataset_path,
        "output_model_id": output_model_id,
        "hyperparams": hp,
        "notes": notes,
        "command_hint": job["command_hint"],
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _output_filename(dataset_path: str, fmt: str) -> str:
    base = os.path.basename(dataset_path)
    stem, ext = os.path.splitext(base)
    if not stem:
        stem = "dataset"
    return f"{stem}.{fmt}{ext or '.jsonl'}"


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _infer_input_format(dataset_path: str) -> str:
    """Best-effort guess of the input format from the filename suffix."""
    name = os.path.basename(dataset_path).lower()
    if name.endswith(".alpaca.jsonl"):
        return "alpaca"
    if name.endswith(".openai.jsonl"):
        return "openai"
    if name.endswith(".hf.jsonl"):
        return "hf"
    return "openai"


def _command_hint(backend: str, base_model: str, dataset_path: str) -> str:
    """Generate a copy-pasteable command hint for the chosen backend."""
    if backend == "openai_ft":
        return (
            f"openai api fine_tuning.jobs.create "
            f"-f {dataset_path} -m {base_model}"
        )
    if backend == "local_lora":
        return (
            f"python -m kb.train.lora --base {base_model} "
            f"--data {dataset_path}"
        )
    if backend == "unsloth":
        return (
            f"python -m kb.train.unsloth --base {base_model} "
            f"--data {dataset_path}"
        )
    return f"# backend={backend}: run your trainer against {dataset_path}"


def _build_readme(job: dict) -> str:
    out_model = job.get("output_model_id") or "<output_model_id>"
    return (
        f"# Fine-tune job {job['job_id']}\n\n"
        f"- created_at: {job['created_at']}\n"
        f"- base_model: {job['base_model']}\n"
        f"- backend: {job['backend']}\n"
        f"- dataset: {job['dataset']['path']} ({job['dataset']['format']})\n"
        f"- output_model_id: {out_model}\n"
        f"- hyperparams: {json.dumps(job['hyperparams'], ensure_ascii=False)}\n\n"
        f"## Run the training job\n\n"
        f"```\n{job['command_hint']}\n```\n\n"
        f"## Register the result\n\n"
        f"Once the trainer reports success, register the resulting model:\n\n"
        f"```\n"
        f"kb models add {out_model} \\\n"
        f"  --base-model {job['base_model']} \\\n"
        f"  --backend {job['backend']} \\\n"
        f"  --from-job {job['job_id']}\n"
        f"```\n"
    )
