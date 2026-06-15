# Demo Bucket

A pre-populated knowledge bucket for `kb-tools` demos and quickstarts.

## Contents

- `config/kb.yml` — bucket configuration (records_dir, doc_dir, concept_dir, inbox_dir, shard_depth, agent_model)
- `records/doc/<shard>/<shard>/<ulid>.md` — 12 sample documents on **vector databases and embeddings**, written via `kb add`
- `inbox/` — empty (drop new files here and run `kb ingest` to add them)
- `.kb/` — empty; built on demand by `kb init` / `demo.sh`

## Domain

The sample documents cover the working vocabulary of a vector-search engineer:
vector databases, cosine similarity, HNSW, product quantization, FAISS,
Milvus/Weaviate/Qdrant, embedding models, RAG, hybrid search, cross-encoder
re-ranking, retrieval evaluation, and chunking strategies.

This domain was chosen because it is one a `kb-tools` user is likely to know
something about already — the demos are more interesting when the reader can
eyeball whether the extracted concepts and summaries are correct.

## Usage

```bash
cd examples/demo-bucket
kb doctor          # verify the bucket is healthy
kb search "HNSW"   # search the docs (FTS5)
kb concepts        # list extracted concepts
kb improve run     # run a self-iterating improve cycle on the bucket
```

To start from a clean state:

```bash
rm -rf .kb records/doc && kb init . && kb add ...   # or use demo.sh
```

## What is NOT pre-built

These files are computed at demo time so the demo is the thing that builds them:

- `.kb/improve/*/` (per-run, fresh each demo)
- `.kb/training/sft-dataset/all.jsonl` (built by `kb sft`)
- `.kb/models/<model_id>.json` (model registry)
- `.kb/models/eval/*.json` (evaluation cache)
- `.kb/index.db` (FTS5 search index)

A pre-built `index.db` can be added later for a true "clone and immediately
search" experience; for now `demo.sh` builds it in seconds.
