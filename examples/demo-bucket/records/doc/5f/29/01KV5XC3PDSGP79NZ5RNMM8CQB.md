---
id: 01KV5XC3PDSGP79NZ5RNMM8CQB
title: Chunking strategies for RAG pipelines
source_type: web
source_key: url:https://example.com/chunking-strategies
content_hash: sha256:cd7026182e30f1b418d5396d20d968d45e9313e363fb8b592ea44d8be55d9c52
created: 2026-06-15T15:11:03.885966+00:00
updated: 2026-06-15T15:11:03.885966+00:00
source: https://example.com/chunking-strategies
concepts:
  - text-chunking
  - rag-pipeline
---

The chunking strategy is one of the most underappreciated knobs in a RAG pipeline. A bad chunker can drop Recall@10 by 30 points even with a perfect embedding model and a perfect vector database, because the 'right' answer for a question is often spread across a paragraph, a section boundary, or a code-block-plus-comment pair.

The simplest approach is fixed-size chunking: split every document into N-token windows with M-token overlap. This is fast, predictable, and what most production systems default to. Typical values are 500 tokens with 50-token overlap for prose, 200 tokens with 20-token overlap for code. The overlap is essential — without it, a sentence that spans a chunk boundary loses its context. The downside is that chunk boundaries are arbitrary and can split mid-thought.

Sentence or paragraph chunking respects document structure. Split on sentence boundaries (using a sentence tokenizer), group into N-sentence windows, and never split mid-sentence. This is better for prose but worse for tables and code, which do not have natural sentence boundaries.

Semantic chunking is the most ambitious approach. Embed every sentence, then greedily merge adjacent sentences until the cosine distance between the merged chunk and the next sentence exceeds a threshold. The result is chunks that correspond to topical shifts in the document. It is more expensive (you have to embed every sentence) and more variable (the threshold is dataset-specific) but produces chunks that are coherent enough to be retrieved as units.

A common pattern is hierarchical chunking: index small chunks (200 tokens) for high recall, and store parent chunks (1000 tokens) as the unit returned to the model. The retriever finds the small chunk; the system passes the parent chunk as context. This gives the recall of small chunks and the coherence of large chunks, and is what LangChain's ParentDocumentRetriever and LlamaIndex's auto-merging retriever implement.

For code, prefer AST-aware chunking that splits on function or class boundaries. For tables, prefer row-level chunking. For mixed documents, default to 500-token windows with 50-token overlap until you have evidence that something better helps. Measure on a labeled set, not on vibes.
