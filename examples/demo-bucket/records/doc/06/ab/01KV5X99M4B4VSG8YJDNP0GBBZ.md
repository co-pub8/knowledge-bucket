---
id: 01KV5X99M4B4VSG8YJDNP0GBBZ
title: "FAISS: Facebook AI Similarity Search"
source_type: web
source_key: url:https://example.com/faiss-overview
content_hash: sha256:7c7bf9bc93c994e75f5f8ddcc844aa42a07cddafeda5563aae67631932b7c64e
created: 2026-06-15T15:09:31.652274+00:00
updated: 2026-06-15T15:09:31.652274+00:00
source: https://example.com/faiss-overview
concepts:
  - faiss
  - vector-index
---

FAISS is the de-facto reference implementation of vector indexing algorithms, originally developed at Facebook AI Research and now maintained by Meta as open source. It is not a database — it is a C++ library with Python bindings that provides implementations of HNSW, IVF, PQ, and several dozen other index types under a unified interface.

The library exposes a flat (brute-force) index, an IVF (inverted file) index that partitions vectors into Voronoi cells and only searches the nearest cells, an HNSW graph index, and the famous 'IVF-PQ' combination that powers billion-scale search. Every index type implements the same four operations: train (build the codebook or graph), add (insert vectors), search (return top-k), and reconstruct (recover the original vector from a compressed representation).

FAISS runs in-process, so there is no server. That makes it fast and easy to embed inside a Python application, but also means you give up the distributed features that a real database provides: replication, persistence, query routing, and concurrent writes. The common pattern is to use FAISS as a library while building the surrounding service (snapshots, sharding, payload filtering) yourself, or to use one of the server wrappers like Qdrant or Milvus that embed FAISS-like indexes.

The most underrated feature is the GPU implementation, which gives 10-100x speedups for both index building and search on a single GPU. For batch workloads (re-indexing a million vectors overnight, computing embeddings for a corpus) the GPU path is dramatically faster than CPU. The CPU path is competitive on its own, though, and is what most production deployments use for online serving.

A common mistake is reaching for FAISS when the dataset is small (under 100k vectors) and would be served perfectly well by a flat index. FAISS's complexity earns its keep only at scale.
