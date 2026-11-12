# Caching and optimization

The canonical JSON store is durable memory, not a disposable cache. Whole-operation
writer locks and generation/fingerprint checks protect same-host writers.

| Layer | Identity and invalidation |
|---|---|
| Source registry (`.sources.json`) | Stable path/device/inode/creation identity; missing files retain metadata. Unsupported creation identity requires an explicit session mapping after rename. |
| Sweep watermark (`.sweepstate.json`) | Persistent content digest and mtime; unchanged sources skip extraction only while their session remains in the canonical store. Invalid state is disposable. |
| Embedding cache (`.embindex.json`) | Exact input hash and backend/model/dimensions. Explicit authoritative rebuild clears removed records; scope-filtered queries retain other scopes' cached vectors. Stale canonical fingerprints refuse writes. |
| Retrieval working data | Offline BM25/sparse TF-IDF over eligible records. No default model discovery or embedding cache writes in `query()`. |
| Job SQLite database | Durable leased work, not a cache. Terminal jobs clear source/result payloads. Unknown submission outcomes require operator reconciliation. |

Budget pruning preserves complete entries. Heap ordering and binary search avoid
repeatedly serializing every remaining item for each deletion. Portable export
probes small groups before binary search, so tiny budgets do not first materialize
half the store. Literal numeric/path matching rejects identifier prefixes while
ordinary acronym morphology remains lexical approximation.

The JSON store still rewrites the complete snapshot on commit. Scope, source and
privacy controls stay authoritative. Real embeddings, model quality and production
performance were not benchmarked. For safe profiling, use synthetic stores with
`NAPMEM_EMBED_BACKEND=hashed`, an empty data/config home and network isolation;
run the ordinary commands in [Testing](TESTING.md) under that boundary.
