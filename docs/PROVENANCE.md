# Evidence and verification

Ingestion binds each extracted assertion to the exact text supplied to
extraction. It stores a SHA-256 source revision, a literal bounded quotation,
its line range/hash and extraction method/model/prompt version. The CLI and
consolidator retain the original input; they do not reread a mutable path at
batch completion to invent support. Missing input remains unverified.

`evidence.status=verified` means the quotation was checked against that input
revision. It does not establish that the source is true or that a paraphrase
is entailed. `assertion_support` distinguishes literal assertion support from
unverified paraphrases. Fabricated or mismatching supplied quotes stay
unverified. Redundant unbounded model quotation fields are removed after
binding; the evidence field owns the bounded literal passage.

Profiles require approved persistent kinds and supported evidence. Numeric
confidence is not manufactured. Source quotation support and operator
correction evidence remain distinct: an operator correction cites its own
action revision and never pretends the old document contained new wording.

`inspect_provenance()` returns the chosen canonical or duplicate occurrence's
own text, source and evidence. By default it reports the stored ingestion
binding and does not open raw source paths. Explicit verification requires
allowed roots and reports verified/changed/missing/unverified. A changed
source never substitutes new text into an old citation.

Filesystem verification uses a nonblocking descriptor, regular-file and
hardlink checks, actual descriptor path containment and a bounded read.
Unsupported platforms fail closed. A missing source does not by itself delete
retained memory. Literal quotes are capped at 4096 UTF-8 bytes with explicit
truncation; omitted text cannot support a claim.

Forgetting records source/range/quotation redaction hashes as well as claim
tombstones. An overlapping quotation in another record cannot retain the
forgotten passage; it becomes unverified with an explicit redaction reason.
These hash-only policies apply again on source replay. Unknown semantic
paraphrases are not claimed to be automatically recognized as equivalent.
