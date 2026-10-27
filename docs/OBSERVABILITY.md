# Local quality and freshness measurements

Version: 1.0.0. Delta: opt-in bounded metrics and operational status.

Enable `--metrics`, TOML `metrics_enabled=true`, or `NAPMEM_METRICS=1` to record
local retrieval and ingestion measurements. No telemetry is transmitted. The
private adjacent metrics JSON accepts only known numbers, booleans, enums and
hashed identifiers. It stores no raw queries, memory text, source paths, model
names or exception messages. Hashes pseudonymize guessable identifiers; file
access controls still matter.

```sh
napmem --pyramid /tmp/napmem-demo/store.json query "preferred editor" --scope project:napmem-demo-alpha --metrics
napmem --pyramid /tmp/napmem-demo/store.json status --scope project:napmem-demo-alpha
napmem --pyramid /tmp/napmem-demo/store.json hook-outcome --success --backend hybrid --result-count 1 --returned-bytes 512
```

`status` combines validated store generation/age, source-registry backlog,
queue state, retained measurements, deletion coverage and an optional explicit
`--mirror-dir`. It reads metadata without source rereads, store creation or
service probes. Invalid/missing components are reported separately. Queue
sampling has an explicit 10,000-row cap. Source lag uses registered mtime;
it is not a measured extraction duration. Unknown freshness stays unknown.

Rates disclose their denominators. Failed retrievals are separate from
successful empty results. Extraction request, validation and fallback stages
are distinct. Returned bytes measure complete CLI JSON plus newline, or the
server JSON-RPC envelope plus newline. The proxy measures its subsequently
appended note/metadata in the response budget; server metrics exclude that
addition. Word-based compression remains an estimate rather than measured
token or monetary savings. Provider token usage and monetary cost remain
unmeasured when an integration supplies no usage observations.

`feedback RECORD_ID useful|wrong|outdated --scope PROJECT` is explicit opt-in.
The CLI checks that the candidate exists in that scope. Feedback keeps the
latest opinion per scoped candidate and stores only hashes. Forgetting removes
matching local feedback. Feedback never adjusts thresholds or approves claims.
Use the fixed evaluation corpus and explicit review for retrieval changes.

Retention defaults to 1,000 events and 30 days. Library callers can choose a
bounded policy. Summaries exclude expired rows without writes. Physical pruning
occurs on the next explicit metrics write. An 8 MiB file cap also applies.
Measurement failures do not fail canonical retrieval or ingestion.

Existing recall hooks and threshold monitors can call `record_hook_outcome` or
the `hook-outcome` command with measured outcomes. This release does not install,
restart or modify those hooks. Their deployed behavior requires separate
acceptance.
