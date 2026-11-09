---
id: 01KV5XAT6JQKDAWZ24D3NYV3X8
title: "Hybrid search: BM25 + vector recall"
source_type: web
source_key: url:https://example.com/hybrid-search
content_hash: sha256:1c642ccbe06e714c47a43f83c1337fe51555acd890d6c9e25e4388deab4a8878
created: 2026-06-15T15:10:21.395017+00:00
updated: 2026-06-15T15:10:21.395017+00:00
source: https://example.com/hybrid-search
concepts:
  - hybrid-search
  - bm25
---

Hybrid search combines two fundamentally different retrieval signals — sparse lexical scoring (BM25) and dense vector similarity — to get the best of both. Pure vector search is great at semantic matches ('vehicle' for 'car') but bad at exact-term matches (a product SKU, a code identifier, a person's name). Pure BM25 is great at exact-term matches but bad at semantic matches. Hybrid search gets the recall of both.

The classic combination is reciprocal rank fusion (RRF). Each retriever returns a ranked list of the top-k documents. The fused score for a document is the sum of 1 / (rank_i + 60) across all retrievers that returned it, with rank_i being the position in retriever i's list (60 is a smoothing constant). The fused list is then sorted by total RRF score. RRF is a strong default because it requires no score calibration — BM25 and cosine similarities live on completely different scales, and RRF sidesteps the question entirely by working on ranks.

The alternative is score-level fusion: normalize each retriever's scores (e.g., to [0, 1] via min-max) and take a weighted sum. This works but is fiddly — the weights are dataset-dependent, and the normalization has to be redone whenever the corpus or query distribution changes. RRF is the safer starting point.

Most modern vector databases (Qdrant, Weaviate, Milvus) ship a hybrid search mode out of the box. Elasticsearch and OpenSearch have had it for a decade under the name 'BM25 + dense_vector'. The pattern is well-tested: hybrid search reliably beats either pure retriever on standard benchmarks (BEIR, MS MARCO), typically by 5-15 nDCG points, and the cost is roughly 2x the latency of either alone because both indexes are queried in parallel.

A practical tip: tune the per-retriever k independently. With RRF, sending 100 candidates from BM25 and 100 from vector search almost always beats sending 20 from each, because the reranker can prune the union.
