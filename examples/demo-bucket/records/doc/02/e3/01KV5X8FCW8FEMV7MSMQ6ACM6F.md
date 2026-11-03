---
id: 01KV5X8FCW8FEMV7MSMQ6ACM6F
title: "HNSW: Hierarchical Navigable Small World graphs"
source_type: web
source_key: url:https://example.com/hnsw-explained
content_hash: sha256:bd4d5d08a9b77408d78bda38bfdc323a7ed789e7293463472653eb28d9f81c0b
created: 2026-06-15T15:09:04.796715+00:00
updated: 2026-06-15T15:09:04.796715+00:00
source: https://example.com/hnsw-explained
concepts:
  - hnsw
  - approximate-nearest-neighbors
---

HNSW is the dominant graph-based index for approximate nearest neighbor (ANN) search in production vector databases. It powers the default index in Weaviate, Qdrant, Milvus, and pgvector, and is the reason billion-scale vector search is feasible in milliseconds on a single machine.

The intuition comes from two earlier ideas. A 'small world' graph is one where any two nodes are connected by a short path — like the classic six-degrees-of-separation result. A 'navigable' graph is one where a greedy local search (always step to the closest neighbor) reliably reaches near-optimal nodes. HNSW layers these two ideas by stacking multiple small-world graphs at different scales.

At the top is a sparse layer with long-range connections — you jump across the dataset in a few steps. At the bottom is a dense layer with short-range connections — you refine the search to the exact neighborhood. Search starts at the top, greedily descends, then drops into the next layer down, and repeats. Insertions pick a level for the new node by flipping a coin, then walk the layers above to find the entry point before inserting at the chosen level and below.

The result is logarithmic search time on well-behaved data. The trade-offs are memory (the graph has to be held in RAM, with roughly 2-4x the storage of the raw vectors) and the lack of true deletion (deleted nodes are masked, so long-running indexes accumulate dead entries and need periodic rebuilds). HNSW also does not support exact filtering on a payload attribute — it can pre-filter or post-filter, but not both efficiently, which is the main reason hybrid search is a hard problem.
