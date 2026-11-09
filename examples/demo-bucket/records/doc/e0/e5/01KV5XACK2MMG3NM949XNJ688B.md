---
id: 01KV5XACK2MMG3NM949XNJ688B
title: "RAG: retrieval-augmented generation explained"
source_type: web
source_key: url:https://example.com/rag-explained
content_hash: sha256:a310133d528b1826be419659b692f93d2283a48086050328f622269b8ef8a49b
created: 2026-06-15T15:10:07.458364+00:00
updated: 2026-06-15T15:10:07.458364+00:00
source: https://example.com/rag-explained
concepts:
  - retrieval-augmented-generation
  - rag-pipeline
---

Retrieval-augmented generation (RAG) is the pattern of fetching relevant context from an external corpus and inserting it into the prompt of a generative model, so the model's answer is grounded in real documents rather than just its training data. It is the dominant architecture for question answering over private or fast-changing knowledge.

The canonical RAG pipeline has four steps. First, an offline indexer splits documents into chunks (typically 200-1000 tokens, with overlap), embeds each chunk with a sentence embedding model, and stores the vectors plus the chunk text in a vector database. Second, at query time, the user question is embedded with the same model. Third, the vector database returns the top-k chunks closest to the question (k is usually 4-20). Fourth, the chunks are concatenated into a prompt template like 'Answer the question using only the following context: ...' and sent to a generative model.

The benefits over fine-tuning are practical: a knowledge base can be updated in seconds by re-indexing, no GPU training is required, and the model never 'forgets' the source material. The limits are also clear. RAG cannot synthesize information across many documents — the model only sees the k chunks, so multi-hop questions often fail. RAG also cannot reason about metadata ('what was the policy in Q1 2024?') unless the chunks have date metadata and the retriever can filter on it.

The state of the art in 2026 adds several layers on top: query rewriting (rewrite the user question to be more retrieval-friendly), hybrid search (combine BM25 with vectors), re-ranking (use a cross-encoder to refine the top-k), and self-RAG / corrective-RAG loops (have the model decide whether it needs more retrieval or can answer). These improvements are additive — each one is worth a few points of accuracy on standard benchmarks.
