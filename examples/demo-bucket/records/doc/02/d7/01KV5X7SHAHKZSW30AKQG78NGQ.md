---
id: 01KV5X7SHAHKZSW30AKQG78NGQ
title: What is a vector database?
source_type: web
source_key: url:https://example.com/vector-db-intro
content_hash: sha256:f94d41d947df72cd7d0ecf51122148579e7eb84a2908c1b17bb29f97e9a9843e
created: 2026-06-15T15:08:42.410242+00:00
updated: 2026-06-15T15:08:42.410242+00:00
source: https://example.com/vector-db-intro
concepts:
  - vector-database
  - embeddings
---

A vector database is a storage system optimized for indexing and querying high-dimensional embedding vectors. Unlike relational databases that excel at exact-match lookups and joins, vector databases are built to answer nearest-neighbor queries at scale, returning the k vectors closest to a query vector under some similarity metric.

The basic unit of data is a fixed-length array of floats — typically 128, 384, 768, 1024, or 3072 dimensions depending on the embedding model. Each vector represents some piece of content (a sentence, a paragraph, an image, a user, a product) in a continuous semantic space. Distances in that space are taken to approximate semantic similarity, so 'king' and 'queen' end up near each other even when they share no characters.

Vector databases are the storage layer behind semantic search, recommendation systems, retrieval-augmented generation (RAG), and any application that needs fuzzy matching rather than exact keyword matching. Common open-source options include Milvus, Weaviate, Qdrant, Chroma, and FAISS-as-a-server. pgvector brings vector search to Postgres for smaller-scale needs.

The core operations are insert (upsert a vector with a payload), search (return the k nearest neighbors with optional metadata filters), and delete. Most production systems also support hybrid search that combines vector recall with BM25 keyword scoring, and metadata filtering to restrict the search to a subset of vectors (e.g., only documents from a given tenant or with a given tag).
