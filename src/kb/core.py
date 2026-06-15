"""Core utilities: ULID generation, hash-sharded paths, directory layout."""

import hashlib
import os
import random
import time

import yaml

RECORDS_DIR = "records"
DOC_DIR = "doc"
CONCEPT_DIR = "concept"
CONFIG_DIR = "config"
INBOX_DIR = "inbox"

CONFIG_FILENAME = "kb.yml"

# Top-level keys persisted in config/kb.yml. Kept as constants so callers and
# tests don't depend on string literals scattered across the codebase.
AGENT_MODEL_KEY = "agent_model"

DEFAULT_CONFIG = """\
# Knowledge Bucket configuration
records_dir: records
doc_dir: doc
concept_dir: concept
inbox_dir: inbox
shard_depth: 2  # hex chars per directory level
agent_model: ""
"""

DEFAULT_ALIASES = """\
# Concept aliases: normalize variant spellings to canonical form.
aliases:
  rag: retrieval-augmented-generation
  retrieval augmented generation: retrieval-augmented-generation
  retrieval-augmented-generation: retrieval-augmented-generation
  graph rag: graph-rag
  graphrag: graph-rag
  llm: large-language-model
  large language model: large-language-model
"""

DEFAULT_STOP_CONCEPTS = """\
# Stop concepts: too generic for document-document linking.
stop_concepts:
  - ai
  - artificial-intelligence
  - programming
  - software
  - web
  - article
  - research
  - paper
  - github
  - python
  - javascript
"""

DEFAULT_TAXONOMY = """\
# Virtual collections: concept-based and source-type-based views (GOAL.md section 19).
# These are SQL views, not physical folders.
virtual_collections:
  papers:
    label: Papers
    include_types:
      - paper

  github_repos:
    label: GitHub Repos
    include_types:
      - git_repo
      - repo

  pdfs:
    label: PDFs
    include_types:
      - pdf
"""


_last_ulid_ms: int = 0
_last_ulid_rand: int = 0


def generate_ulid() -> str:
    """Generate a monotonic ULID (26 chars, Crockford Base32).

    Guarantees sortability: if called multiple times within the same
    millisecond, the random component is incremented instead of re-sampled.
    """
    global _last_ulid_ms, _last_ulid_rand
    encoding = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    now_ms = int(time.time() * 1000)

    if now_ms <= _last_ulid_ms:
        now_ms = _last_ulid_ms
        _last_ulid_rand += 1
        rand = _last_ulid_rand
    else:
        _last_ulid_ms = now_ms
        rand = random.SystemRandom().getrandbits(80)
        _last_ulid_rand = rand

    # 10-char time component
    t = now_ms
    time_chars = []
    for _ in range(10):
        time_chars.append(encoding[t & 0x1F])
        t >>= 5
    time_part = "".join(reversed(time_chars))

    # 16-char random component
    rand_chars = []
    for _ in range(16):
        rand_chars.append(encoding[rand & 0x1F])
        rand >>= 5
    rand_part = "".join(reversed(rand_chars))

    return time_part + rand_part


def shard_path(ulid: str, depth: int = 2) -> str:
    """Compute hash-sharded directory path from a ULID.

    Returns relative path like 'ab/cd/<ulid>.md' under records/doc/.
    Uses sha256(ulid) for even distribution, not the ULID itself,
    so physical layout is independent of time ordering.
    """
    h = hashlib.sha256(ulid.encode()).hexdigest()
    parts = []
    for i in range(depth):
        parts.append(h[i * 2 : (i + 1) * 2])
    return os.path.join(*parts, f"{ulid}.md")


def yaml_scalar(value: str) -> str:
    """Render a string as a YAML-safe scalar.

    Quotes values that would break unquoted YAML. The real breaker is a
    ``: `` (colon-space) sequence or a value that looks like another mapping
    key; URLs like ``https://x`` are safe unquoted and stay that way.
    """
    if value is None:
        return "null"
    s = str(value)
    needs_quote = (
        not s
        or ": " in s
        or s.endswith(":")
        or s[0] in "-?{\"'[]{}#&*!|>%@`,"
        or s.endswith(" ")
        or "\n" in s
    )
    if needs_quote:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def kb_root() -> str | None:
    """Find the knowledge bucket root by walking up from cwd looking for config/kb.yml."""
    cur = os.path.realpath(os.getcwd())
    while True:
        candidate = os.path.join(cur, CONFIG_DIR, CONFIG_FILENAME)
        if os.path.exists(candidate):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def ensure_dirs(root: str) -> None:
    """Create the standard directory structure under root."""
    for d in [
        os.path.join(root, RECORDS_DIR, DOC_DIR),
        os.path.join(root, RECORDS_DIR, CONCEPT_DIR),
        os.path.join(root, CONFIG_DIR),
        os.path.join(root, INBOX_DIR),
    ]:
        os.makedirs(d, exist_ok=True)


# Optional storage directories created on demand by Phase 13.1+ code paths.
# Kept as module constants (not added to ``ensure_dirs``) so users who never
# use fine-tuning don't see empty .kb/models/ and .kb/finetune/ dirs after
# ``kb init``.
MODELS_DIR = ".kb/models"
FINETUNE_DIR = ".kb/finetune"
IMPROVE_DIR = ".kb/improve"


def ensure_models_dirs(root: str) -> None:
    """Create the fine-tuning storage directories under root.

    Safe to call repeatedly; existing dirs are left untouched. Called by
    ``kb init`` (idempotent) and by the relevant subcommands on demand.
    """
    for d in [os.path.join(root, MODELS_DIR),
              os.path.join(root, FINETUNE_DIR)]:
        os.makedirs(d, exist_ok=True)


def ensure_improve_dir(root: str, run_id: str) -> str:
    """Create the per-run storage directory for ``kb improve``.

    Returns the absolute path of the created directory. Each ``kb improve``
    invocation gets its own subdirectory under ``.kb/improve/<run_id>/`` to
    hold the run summary and append-only iteration log.
    """
    path = os.path.join(root, IMPROVE_DIR, run_id)
    os.makedirs(path, exist_ok=True)
    return path


def _config_path(root: str) -> str:
    return os.path.join(root, CONFIG_DIR, CONFIG_FILENAME)


def get_config_value(root: str, key: str, default: str | None = None) -> str | None:
    """Read a scalar top-level value from config/kb.yml.

    Returns ``default`` when the file is missing, empty, or the key is absent.
    The existing config file holds string scalars (records_dir, shard_depth,
    user_interests block, etc.); non-string values are stringified so callers
    always get a consistent ``str | None`` shape.
    """
    path = _config_path(root)
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if key not in data:
        return default
    val = data[key]
    if val is None:
        return default
    if isinstance(val, str):
        return val
    return str(val)


def set_config_value(root: str, key: str, value: str) -> None:
    """Set a scalar top-level value in config/kb.yml, preserving other keys.

    Creates the file (and its parent directory) if it does not exist.
    The previous file is read in full, the key is updated, and the file is
    re-written via ``yaml.safe_dump`` so the rest of the config survives.
    """
    path = _config_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data[key] = value
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True,
                       sort_keys=False)
