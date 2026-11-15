---
id: 01KV5X8518KBTKFS1HNFX8GERE
title: Cosine similarity vs dot product
source_type: web
source_key: url:https://example.com/cosine-vs-dot
content_hash: sha256:4afcab3fd468e455a88064d89200e34a6077259b88f8fdd7fb4c47fdcb8a2fa2
created: 2026-06-15T15:08:54.184568+00:00
updated: 2026-06-15T15:08:54.184568+00:00
source: https://example.com/cosine-vs-dot
concepts:
  - cosine-similarity
  - vector-search
---

Two similarity functions dominate vector search: dot product and cosine similarity. They look similar but answer different questions and behave differently when vector norms vary.

Dot product is the raw sum of element-wise products: sum(a_i * b_i). It rewards vectors that point in the same direction AND have large magnitudes. If one vector has been scaled up (e.g., a longer document, a higher-norm embedding) the dot product grows with it. This is exactly what you want for some models — OpenAI's text-embedding-3 and many LLM-derived embeddings are trained so that magnitude carries information about confidence or document length.

Cosine similarity is the dot product normalized by the L2 norms of both vectors: dot(a, b) / (||a|| * ||b||). The output lives in [-1, 1] and is invariant to scaling, so two vectors that point in the same direction score 1.0 regardless of magnitude. Cosine is the default for most embedding models (SBERT, sentence-transformers, many BERT variants) and the right choice when magnitude is not meaningful.

Euclidean distance (L2) is another common choice, equivalent to dot product up to a constant when vectors are unit-normalized. Most vector databases let you pick the metric at index creation; the choice should match how the embedding model was trained. Switching the metric after the fact silently degrades recall without producing errors, which is one of the most common production bugs in retrieval systems.

A practical rule: if you are unsure, use cosine similarity with vectors that have been L2-normalized, because then cosine and dot product collapse to the same computation and you can swap backends without changing the math.
