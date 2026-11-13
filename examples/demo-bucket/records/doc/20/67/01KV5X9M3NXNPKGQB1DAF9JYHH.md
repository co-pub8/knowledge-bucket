---
id: 01KV5X9M3NXNPKGQB1DAF9JYHH
title: "Open-source vector DB landscape: Milvus, Weaviate, Qdrant"
source_type: web
source_key: url:https://example.com/vector-db-landscape
content_hash: sha256:591f5fb9df59b4b67e58f63b1d1365b22ba8841baafad865f14f19707b66bb9d
created: 2026-06-15T15:09:42.390053+00:00
updated: 2026-06-15T15:09:42.390053+00:00
source: https://example.com/vector-db-landscape
concepts:
  - milvus
  - weaviate
  - qdrant
---

Three open-source vector databases dominate the production landscape: Milvus, Weaviate, and Qdrant. All three support HNSW, all three support PQ, all three expose a REST or gRPC API, and all three will pass a basic benchmark on a million 768-dimensional vectors. The differences are in ergonomics, scalability, and the surrounding feature set.

Milvus is the heaviest. It is built in C++ and Go, designed for billion-scale deployments, and ships with a multi-component architecture (proxy, coordinator, storage) that you can scale horizontally. The operational cost is high — running a small Milvus cluster takes more memory and babysitting than the other two — but you get horizontal scale for free, including separate nodes for indexing and querying. Pick Milvus when you have a real ops team and need to grow past a few hundred million vectors.

Weaviate is the most API-driven. It is built in Go, exposes a GraphQL interface alongside REST, and bakes in 'modules' for vectorization (it can call OpenAI, Cohere, or local models on your behalf) and 'generative search' (it can run RAG over your data with a single query). The trade-off is that the abstraction layer sometimes hides the underlying index choices, which makes fine-grained tuning harder. Pick Weaviate if your team values developer experience and you want a one-stop shop.

Qdrant is the Rust-based middle ground. It is a single binary, runs comfortably on a laptop or a multi-node cluster, and is famous for its payload filtering performance — Qdrant indexes metadata fields alongside vectors and supports arbitrary boolean filters at near-full recall, which is the main weakness of pure HNSW. Pick Qdrant when your queries look like 'find similar products in category X with price between A and B' and metadata filtering is on the critical path.
