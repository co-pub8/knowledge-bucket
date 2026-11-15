---
id: 01KV5X8Y49GM0QFNGN1P0WAXEP
title: Product quantization for compressed vectors
source_type: web
source_key: url:https://example.com/product-quantization
content_hash: sha256:0c31c3beb59147951ef88573e192a6a28abdaecbe764c330e6117d646a4f42ff
created: 2026-06-15T15:09:19.881975+00:00
updated: 2026-06-15T15:09:19.881975+00:00
source: https://example.com/product-quantization
concepts:
  - product-quantization
  - vector-compression
---

Product quantization (PQ) is the workhorse technique for compressing vectors enough to fit billions of them in memory. It trades a small amount of recall for an order-of-magnitude reduction in storage, and it composes cleanly with HNSW.

The algorithm works in two stages. First, split each d-dimensional vector into m sub-vectors of dimension d/m. Second, run k-means clustering on each sub-vector subspace independently, producing m codebooks of k=256 centroids each (so each centroid fits in one byte). To encode a vector, replace every sub-vector with the index of its nearest centroid — the vector is now a sequence of m bytes instead of d floats.

A 768-dimensional float32 vector takes 3072 bytes uncompressed. With m=8 sub-vectors, the same vector takes 8 bytes — a 384x compression. The cost is approximate distance: instead of computing exact L2, the searcher uses a precomputed lookup table of centroid-to-centroid distances to estimate the distance between any two compressed vectors in roughly m lookups and additions.

The catch is that PQ is only accurate when the data clusters well. FAISS and Qdrant offer 'OPQ' (optimized product quantization) and 'PQ with k-means refined by HNSW' as fixes, and recommend training the codebook on a representative sample of at least a few thousand vectors. Residual quantization (RQ) and binary quantization are related techniques with different trade-offs: RQ keeps more accuracy at smaller compression, binary quantization is the most aggressive (32x) and the least accurate, used for re-ranking shortlists rather than full recall.

For most production systems the recipe is: HNSW for the graph, PQ for storage, optional reranker for the final top-k. That stack is what makes billion-scale vector search cheap enough to run on commodity hardware.
