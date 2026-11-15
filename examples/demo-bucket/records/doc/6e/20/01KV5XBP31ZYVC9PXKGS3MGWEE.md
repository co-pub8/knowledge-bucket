---
id: 01KV5XBP31ZYVC9PXKGS3MGWEE
title: "Evaluating retrieval quality: NDCG and Recall@k"
source_type: web
source_key: url:https://example.com/retrieval-evaluation
content_hash: sha256:7ade889332731ca82658474bb6a067d677efaad77b4d27b7f9dc5e8ff5ec6252
created: 2026-06-15T15:10:49.953701+00:00
updated: 2026-06-15T15:10:49.953701+00:00
source: https://example.com/retrieval-evaluation
concepts:
  - retrieval-evaluation
  - ndcg
---

A retrieval system that nobody can measure is a retrieval system that nobody can improve. The two metrics that dominate retrieval evaluation are Recall@k and NDCG@k, and understanding their difference is the difference between debugging a search system and guessing.

Recall@k asks: of the documents labeled as relevant in the test set, what fraction appear in the top-k results? It is a coverage metric — it tells you whether the retriever can find the right documents at all. Recall is what you want to optimize when the retrieved documents are passed to a downstream reranker or reader, because the pipeline only succeeds if the relevant documents survive the first stage. The ceiling is the recall of the labeled set itself, so a perfect reranker can only help if the retriever's recall is high.

NDCG@k (normalized discounted cumulative gain) asks: how well-ranked are the relevant documents in the top-k? It uses graded relevance labels (0/1/2/3) and a logarithmic discount so that a relevant document at position 1 contributes more than a relevant document at position 10. NDCG is what you want to optimize when the user sees the top-k directly (a search results page) and you care about the order, not just the set. It is bounded in [0, 1] and is normalized by the ideal ranking, so scores are comparable across queries.

The two metrics often disagree. A retriever that always returns 1 relevant document at position 1 has perfect NDCG@1 but possibly terrible Recall@1000. A retriever that returns all relevant documents in random order has great Recall but NDCG near zero. The right metric depends on the downstream task: RAG pipelines care about Recall@100 (does the context window contain the answer?), search engines care about NDCG@10 (is the right result on the first page?).

Other useful metrics: MRR (mean reciprocal rank) for the 'first relevant document' position, MAP (mean average precision) for binary-relevance ranking, and the BEIR / MTEB benchmark suites for standardized cross-system comparison. Always evaluate on a held-out test set with human-labeled relevance — automatic metrics on click data are noisy because clicks conflate relevance with position bias.
