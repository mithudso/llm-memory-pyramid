# NapMem CLI and configuration

Version: 1.0.0. Delta: one portable offline entrypoint.

`napmem --help` lists commands. Global settings also work after a subcommand.
CLI settings override environment variables, then TOML, then offline defaults.
The default store lives in the platform's user data directory. No command
defaults to writing the example store in this checkout. `init` preserves an
existing store. `demo` ingests synthetic sessions in separate named scopes.

```sh
napmem --pyramid /tmp/napmem-demo/store.json init
napmem --pyramid /tmp/napmem-demo/store.json demo
napmem --pyramid /tmp/napmem-demo/store.json query "preferred editor" --scope project:napmem-demo-alpha
napmem --pyramid /tmp/napmem-demo/store.json doctor
napmem --pyramid /tmp/napmem-demo/store.json jobs list
napmem --pyramid /tmp/napmem-demo/store.json snapshot export /tmp/napmem-demo/backup
napmem --pyramid /tmp/napmem-demo/store.json snapshot restore /tmp/napmem-demo/backup
napmem eval --eval-mode hybrid --split heldout
```

`query` returns compact bounded JSON. Set `--as-of`, `--top-k`, `--max-bytes`
and `--max-tokens` as needed. Tokens are a disclosed byte-based estimate.
Named scopes include explicitly global records. Unscoped queries include
legacy and global records; `--scope '*'` is an explicit cross-scope query.

`inspect --view review` opens the scoped extraction queue. Other terminal views
include profiles, conflicts, stale evidence, timeline and project handoff.
`diff BEFORE AFTER` compares two explicit source revisions. See [the inspector
guide](INSPECTOR.md) for correction and pagination behavior.

`ingest /absolute/source.md --scope project:name` records an explicit source.
`--enqueue` captures a durable job. `jobs run --commit` runs queued heuristic
work. Anthropic `jobs submit` and `jobs collect` are separate online commands.
`control --help` lists preview, generation-check and persistent review/correction
options. Model output cannot set operator authority or approved review state.

Select a config with `--config /absolute/config.toml` or `NAPMEM_CONFIG`.
Otherwise the standard user configuration location is inspected if present.
Paths in TOML resolve relative to the configuration file:

```toml
[napmem]
mode = "offline"
pyramid = "store.json"
scope = "project:example"
source_roots = ["sources"]
embedding_backend = "hashed"
extraction = "heuristic"
```

Environment equivalents include `NAPMEM_PYRAMID`, `NAPMEM_MODE`, `NAPMEM_SCOPE`,
`NAPMEM_SOURCE_ROOTS` (OS path separator), `NAPMEM_EMBED_BACKEND` and
`NAPMEM_EXTRACTION`. No dotenv file is implicitly loaded.

`doctor` reads local configuration and store metadata only. It neither creates
stores nor imports or probes a model client. Explicit `doctor --probe` requires
local/remote mode and an explicit HTTP(S) Ollama URL. Its result states what was
tested. Local/remote modes permit configured online integrations; they do not
automatically turn them on. Ollama queries need an explicit URL and embedding
model; chat extraction also needs an explicit chat model. Anthropic extraction
needs the optional SDK, SDK-supported credentials and an explicit model.
