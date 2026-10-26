# Code-deep-optimizer review — 2026-10-26

Package delta: 0.1.0 → 0.1.1. Workflow delta: v1.6.0 → v1.7.0. Scope: nine original runtime modules, three original test modules and the sweep wrapper; new maintenance/test code also received final review. No file-count truncation.

## Per-iteration severity

| Iteration | Critical | High | Medium | Low/Nit | Outcome |
|---|---:|---:|---:|---:|---|
| 1 | 2 | 14 | 11 | 0 counted | Fixed; first independent gate found 2 High and 5 Medium residuals |
| 2 | 0 | 2 | 5 | 0 counted | Fixed; second independent gate found one further Medium; targeted correction verified |

## Findings

F01–F27 evidence lines refer to baseline 1f3d21d; F28–F34 refer to the iteration-1 candidate; F35 refers to the iteration-2 candidate. The snapshot preserves both versions. Reproduction tests failed before their fixes and passed afterward.

| ID | Pass | Evidence | Severity | Finding | Fix | Status |
|---|---|---|---|---|---|---|
| F01 | C1/S3 | /Users/mitch/dev/llm-memory-pyramid/scripts/run-naptime.sh:77 | Critical | Refused source deleted an operator plain file | Remove only symlinks; fixture preserves operator text | Fixed |
| F02 | C1/S1 | /Users/mitch/dev/llm-memory-pyramid/scripts/run-naptime.sh:90 | Critical | Destination directory symlink redirected ln into unrelated data | ln -sfn replaces link; fixture preserves outside file | Fixed |
| F03 | C1/C2 | /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:276 | High | Reasserted record kept stale payload and derived topic | Refresh current payload while preserving identity and duplicate wording | Fixed |
| F04 | S2/S3 | /Users/mitch/dev/llm-memory-pyramid/semantic_index.py:208 | High | Malformed cache entries crashed or poisoned scoring | Validate structure, finite numeric vectors and dimensions; re-embed safely | Fixed |
| F05 | C1 | /Users/mitch/dev/llm-memory-pyramid/semantic_index.py:237 | Medium | Deletion-only/empty rebuild left stale vectors on disk | Prune independently and persist an empty rebuild | Fixed |
| F06 | C2 | /Users/mitch/dev/llm-memory-pyramid/semantic_index.py:71 | Medium | Normalized hash reused embeddings for different exact input | Hash exact backend input | Fixed |
| F07 | C2/S3 | /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py:74 | Medium | Negative result count used Python slicing semantics | Validate positive nonbool integer at public APIs and MCP | Fixed |
| F08 | S2 | /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:258 | High | SDK constructor failure bypassed extraction fallback | Construct client within guarded batch boundary | Fixed |
| F09 | S3 | /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:176 | Medium | Wrong-shaped valid sweep JSON raised AttributeError | Validate envelope and entries, emit metadata-only warnings | Fixed |
| F10 | C1 | /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:214 | High | Watermark suppressed recovery of missing/empty store | Trust state only for sources present in loaded pyramid | Fixed |
| F11 | S1/S5 | /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py:111 | High | Validation warnings exposed rejected memory payloads | Log unit positions and fixed categories only | Fixed |
| F12 | C1/S3 | /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py:120 | High | Global think-tag removal corrupted JSON string content | Strip only leading reasoning preamble | Fixed |
| F13 | C2/S2 | /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py:147 | Medium | Missing model benched every model on same live URL | Use shared pool health to separate host and model failures | Fixed |
| F14 | C1 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:149 | High | Mirror transfer ignored configured remote basename | Copy configured store and its cache to fixed local names | Fixed |
| F15 | P2 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:153 | High | Concurrent transfers shared a truncatable temporary inode | Unique temporary file per transfer, atomic replacement | Fixed |
| F16 | S2 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:190 | High | Invalid backend UTF-8 bypassed lifecycle callback | Bounded binary reader, finally cleanup and one exit callback | Fixed |
| F17 | P2/S2 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:355 | High | Blocking pipe write held proxy state lock | Bounded queue and nonblocking writes with deadlines | Fixed |
| F18 | S2/S3 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:197 | High | Decoder integer/depth errors ended serving loop | Bounded parse errors and continued serving | Fixed |
| F19 | C2 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:131 | Medium | Notifications emitted unmatched replies and executed tools | Ignore request-only notification methods without side effects | Fixed |
| F20 | S3 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:189 | Medium | Input limit was applied after allocating complete line | Read and drain in bounded chunks, validate UTF-8 byte length | Fixed |
| F21 | C2/S3 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py:118 | Medium | Malformed protocol envelopes/IDs/params were accepted | Validate supported MCP envelope and normalize error IDs | Fixed |
| F22 | S1/P1 | /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py:63 | High | Unmatched bracket runs caused quadratic regex work | Do not restart matches within a bracket run; child deadline regression | Fixed |
| F23 | S2/T1 | /Users/mitch/dev/llm-memory-pyramid/test_napmem_extensions.py:34 | High | Tests could probe operator-configured model endpoints | Reject network by default; explicit transport fakes | Fixed |
| F24 | T4 | /Users/mitch/dev/llm-memory-pyramid/test_napmem_extensions.py:144 | Medium | Tests erased caller embedding environment | Restore complete previous values with patch.dict cleanup | Fixed |
| F25 | T1 | /Users/mitch/dev/llm-memory-pyramid/test_napmem_failover.py:90 | Medium | Replay test passed without handshake replay | Strict fallback requires initialize and initialized notification | Fixed |
| F26 | C1/S2 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:249 | High | Failed primary spawn did not attempt local backend | Enter normal failover path after spawn failure | Fixed |
| F27 | M4 | /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py:11 | Medium | Extraction-mode module docs described obsolete chain | Document Anthropic/Ollama/heuristic paths | Fixed |
| F28 | C1/C2 | /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:291 | High | Same-session duplicate IDs changed on no-op re-ingest | Reclaim every surviving occurrence using ordered queues | Fixed |
| F29 | S2 | /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py:179 | Medium | Index initialization escaped best-effort dedup fallback | Guard initialization/import and lookup; avoid needless initialization | Fixed |
| F30 | S2 | /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py:170 | High | Statistics could block on raw source replaced by FIFO | Open nonblocking, fstat regular file, close FD and disclose unavailable sources | Fixed |
| F31 | S1/S3 | /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py:76 | Medium | Unicode line separators escaped metadata boundary | Neutralize all splitlines separators | Fixed |
| F32 | P2/S3 | /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py:458 | Medium | Invalid IDs could remain pending indefinitely | Reject invalid IDs before tracking/forwarding | Fixed |
| F33 | C1/S3 | /Users/mitch/dev/llm-memory-pyramid/semantic_index.py:321 | Medium | Finite vectors could yield nonfinite similarity scores | Check shared cosine results and trigger disclosed fallback | Fixed |
| F34 | S2 | /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py:66 | Medium | Decoder limits bypassed per-file extraction fallback | Convert decoder ValueError/RecursionError to ExtractionError | Fixed |
| F35 | S2 | /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py:90 | Medium | Ollama wrapper parser depth error bypassed per-file fallback | Catch decoder RecursionError; strict parser rejects and heuristic/later files survive | Fixed |

A proposed per-session catch around failed store writes was rejected: the distiller mutates in-memory state before saving. Continuing without transactional rollback could persist failed state. Fatal batch write errors remain explicit and documented; no unsafe recovery was introduced.

## Verify gate

| Command | Baseline | Final | Verdict |
|---|---|---|---|
| `NAPMEM_EMBED_BACKEND=hashed python3 -m unittest discover -s . -p "test_*.py"` in project venv | 66 pass after declared dependency install | 111 pass on Python 3.12 | PASS |
| `python3 -m compileall -q .` | Pass | Pass | PASS |
| `ruff check .` | Existing UTC-alias finding; prior CI also failed dependency auth | Explicit repo rules and UTC fix pass | PASS |
| `bash -n scripts/run-naptime.sh` | Pass | Pass | PASS |
| `python3 scripts/repo_docs.py --check` | No checker; stale map | Exact generated content checked | PASS |

No held-out benchmark evaluation set exists. Empirical champion tracking did not engage and no champion was persisted. No new feature phase or advisory track ran.

## Activated skills

- repo-bootstrapper 5.4.1: established Python repository standards and documentation drift.
- code-deep-optimizer 1.16.0: all 18 structural passes and two independent gates.
- lang-python: runtime/API/resource review.
- security-review with its security-reviewer reference: prompt boundaries, memory privacy, input and filesystem safety.
- software-engineering-patterns reviewer/coding-standards references: correctness, maintainability and meaningful tests.
- llms-txt-tooling / crawl-repo-to-llms: static external dossier without index probes or target execution.
- Memory-central: 11 convention rows consulted and checked against current repo; no project lesson file was present.

## Per-file diff preview

Previews are capped to 16 changed lines per file. Git preserves the complete patch; generated documentation is summarized in the bootstrap audit.

### /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/llm_extraction_prompts.py

+++ /Users/mitch/dev/llm-memory-pyramid/llm_extraction_prompts.py

@@ -62,3 +62,5 @@

         import re
-        _SENTINEL_RUN_RE = re.compile(r"<{2,}RAW_MEMORY_SOURCE>{2,}")
+        # Do not retry the greedy prefix at every position within an
+        # unmatched '<' run; that makes an unanchored substitution quadratic.
+        _SENTINEL_RUN_RE = re.compile(r"(?<!<)<{2,}RAW_MEMORY_SOURCE>{2,}")
     value = _SENTINEL_RUN_RE.sub("[SENTINEL-REDACTED]", value)
@@ -73,3 +75,3 @@

     # would let a hostile filename smuggle instruction lines into the prompt.
-    return _neutralize_sentinel(value.replace("\r", " ").replace("\n", " "))
+    return _neutralize_sentinel(" ".join(value.splitlines()))

```

### /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/llm_extractor.py

+++ /Users/mitch/dev/llm-memory-pyramid/llm_extractor.py

@@ -10,3 +10,3 @@


-Requires the `anthropic` package (the repo's only optional dependency):
+Requires the optional `anthropic` package:
     pip install anthropic
@@ -65,3 +65,5 @@

         units = json.loads(text)
-    except json.JSONDecodeError as exc:
+    except (ValueError, RecursionError) as exc:
+        # JSONDecodeError is a ValueError, but decoder resource limits (large
+        # integer literals and nesting depth) raise these broader exceptions.
         raise ExtractionError(f"Extractor did not return valid JSON: {exc}") from exc
@@ -77,3 +79,3 @@

     if unit.get("type") not in UNIT_TYPES:
```
Preview truncated: 43 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/memory_pyramid_distiller.py

+++ /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py

@@ -22,3 +22,4 @@

 import sys
-from datetime import datetime, timezone
+from collections import deque
+from datetime import UTC, datetime
 from typing import Any
@@ -34,3 +35,3 @@

 def _utcnow() -> str:
-    return datetime.now(timezone.utc).isoformat()
+    return datetime.now(UTC).isoformat()

@@ -178,4 +179,2 @@


-        index = self._get_semantic_index()
```
Preview truncated: 92 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/napmem_mcp_failover.py

+++ /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_failover.py

@@ -46,4 +46,7 @@

 import os
+import queue
+import select
 import subprocess
 import sys
+import tempfile
 import threading
@@ -52,2 +55,4 @@

 from typing import Any
+
+from napmem_mcp_server import MAX_LINE_BYTES, bounded_lines

@@ -148,3 +153,2 @@

```
Preview truncated: 251 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/napmem_mcp_server.py

+++ /Users/mitch/dev/llm-memory-pyramid/napmem_mcp_server.py

@@ -33,3 +33,3 @@


-SERVER_INFO = {"name": "napmem", "version": "1.1.0"}
+SERVER_INFO = {"name": "napmem", "version": "1.1.1"}
 PROTOCOL_VERSION = "2025-06-18"
@@ -54,3 +54,3 @@

                              "description": "Embedding cosine search over records."},
-                "top_k": {"type": "integer", "description": "Result count (semantic mode)."},
+                "top_k": {"type": "integer", "minimum": 1, "description": "Result count (semantic mode)."},
             },
@@ -89,2 +89,36 @@


+def bounded_lines(stdin):
+    """Yield bounded UTF-8 lines, or None after draining an invalid line.
```
Preview truncated: 143 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/napmem_retrieval_agent.py

+++ /Users/mitch/dev/llm-memory-pyramid/napmem_retrieval_agent.py

@@ -18,2 +18,3 @@

 import os
+import stat
 from typing import Any
@@ -79,2 +80,4 @@

         """
+        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
+            raise ValueError("top_k must be a positive integer")
         records = self.data.get("memory_records", [])
@@ -157,3 +160,3 @@


-        The comparison only covers sessions whose raw file is still readable:
+        The comparison only covers readable regular source files:
         counting every distilled record against a partial raw baseline would
```
Preview truncated: 34 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/naptime_consolidator.py

+++ /Users/mitch/dev/llm-memory-pyramid/naptime_consolidator.py

@@ -11,5 +11,5 @@

 Extraction modes (--extraction):
-  auto      (default) LLM extraction when the `anthropic` package is
-            importable, heuristic otherwise — decided once at startup.
+  auto      (default) Anthropic when importable, then Ollama, then heuristic.
   llm       Require LLM extraction; startup fails without `anthropic`.
+  ollama    Local Ollama extraction, then heuristic; no Anthropic API calls.
   heuristic Always use the built-in keyword-rule extractor.
@@ -18,4 +18,5 @@

 (50% cost — naptime is idle-time work, latency is irrelevant). Any file whose
-LLM extraction fails falls back to the heuristic extractor for that file, so
-the pyramid never silently misses an update.
+LLM extraction fails tries the remaining configured extractors for that file.
+Store write failures remain fatal to batch ingestion: continuing without a
```
Preview truncated: 85 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/ollama_extractor.py

+++ /Users/mitch/dev/llm-memory-pyramid/ollama_extractor.py

@@ -91,3 +91,3 @@

         data = json.loads(content)
-    except ValueError:
+    except (ValueError, RecursionError):
         return content
@@ -104,3 +104,3 @@


-THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
+THINK_RE = re.compile(r"^\s*<think>.*?</think>\s*", re.DOTALL)

@@ -119,3 +119,4 @@

         raise OllamaExtractionError(f"{url} returned no message content")
-    content = THINK_RE.sub("", content).strip()
+    # Strip only a reasoning preamble, never literal markup inside JSON text.
```
Preview truncated: 43 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/semantic_index.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/semantic_index.py

+++ /Users/mitch/dev/llm-memory-pyramid/semantic_index.py

@@ -68,2 +68,3 @@

 HASHED_DIM = 512
+MAX_CACHE_DIMENSIONS = 8192

@@ -71,3 +72,25 @@

 def _text_key(text: str) -> str:
-    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]
+    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
+
+
+def _valid_cached_vector(vector: Any, dimensions: int | None = None) -> bool:
+    """Validate disposable cache data before it reaches cosine scoring."""
+    if (not isinstance(vector, list) or not 1 <= len(vector) <= MAX_CACHE_DIMENSIONS
+            or (dimensions is not None and len(vector) != dimensions)):
```
Preview truncated: 152 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_extensions.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_extensions.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_extensions.py

@@ -11,2 +11,3 @@

 import json
+import io
 import os
@@ -31,5 +32,15 @@


-# Network-free suite: point the Ollama chat chain at the discard port so any
-# accidental live probe refuses instantly instead of reaching a real daemon.
-os.environ.setdefault("NAPMEM_OLLAMA_CHAT", "http://127.0.0.1:9=test-model")
+def setUpModule():
+    # Every transport exercise installs its own fake. Unexpected requests must
+    # fail here, regardless of the operator's configured Ollama endpoints.
+    global _network_guard
+    _network_guard = mock.patch(
```
Preview truncated: 265 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_failover.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_failover.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_failover.py

@@ -11,2 +11,3 @@

 import shutil
+import subprocess
 import sys
@@ -41,2 +42,24 @@


+# The production server is deliberately permissive about lifecycle ordering.
+# This backend makes the proxy's handshake replay observable to the test.
+STRICT_FALLBACK = r"""
+import json, sys
+initialized = False
+initializing = False
+for line in sys.stdin:
+    msg = json.loads(line)
```
Preview truncated: 175 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_pipeline.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_pipeline.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_pipeline.py

@@ -173,3 +173,3 @@

         self.assertEqual(prompt.count(RAW_TEXT_DELIMITER), 3)  # label line + 2 wrappers only
-        file_lines = [l for l in prompt.splitlines() if "IGNORE PREVIOUS" in l]
+        file_lines = [line for line in prompt.splitlines() if "IGNORE PREVIOUS" in line]
         self.assertEqual(len(file_lines), 1)
```

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_protocol.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_protocol.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_protocol.py

@@ -0,0 +1,143 @@

+"""Offline regressions for the stdlib MCP protocol boundary."""
+
+import io
+import json
+import sys
+import unittest
+from unittest import mock
+
+import napmem_mcp_server as mcp
+import napmem_mcp_failover as failover
+
+
+class TestProtocolBoundary(unittest.TestCase):
```
Preview truncated: 146 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_regressions.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_regressions.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_regressions.py

@@ -0,0 +1,242 @@

+"""Offline regression checks for store reconciliation and disposable caches."""
+
+import json
+import tempfile
+import unittest
+from pathlib import Path
+from unittest import mock
+
+from memory_pyramid_distiller import MemoryPyramidDistiller
+from napmem_retrieval_agent import NapMemRetrievalAgent
+from semantic_index import HashedTfBackend, SemanticIndex, _text_key
+
+
```
Preview truncated: 245 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/test_napmem_safety.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/test_napmem_safety.py

+++ /Users/mitch/dev/llm-memory-pyramid/test_napmem_safety.py

@@ -0,0 +1,76 @@

+"""Offline regressions for prompt CPU bounds and wrapper filesystem safety."""
+import os
+from pathlib import Path
+import subprocess
+import sys
+import tempfile
+import unittest
+
+from llm_extraction_prompts import _neutralize_metadata
+
+ROOT = Path(__file__).resolve().parent
+
+
```
Preview truncated: 79 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/scripts/run-naptime.sh

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/scripts/run-naptime.sh

+++ /Users/mitch/dev/llm-memory-pyramid/scripts/run-naptime.sh

@@ -14,9 +14,8 @@

 #
-# Credentials come from the operator's `ant auth login` OAuth profile, which
-# the anthropic SDK resolves natively — no key is stored here or in the
-# service definitions. Without a profile the consolidator degrades to the
-# heuristic extractor.
+# Anthropic credentials resolve through its SDK when that path is enabled.
+# This wrapper does not load login profiles or store credentials. Extraction
+# failures fall through the configured Ollama/heuristic chain.
 #
-# PRIVACY: everything this mirror sweeps is sent to the Anthropic API (LLM
-# extraction) and the Ollama embedding hosts — the mirror IS the consent
+# PRIVACY: enabled LLM extraction sends source text to Anthropic or Ollama;
+# semantic dedup sends records to embedding hosts. The mirror IS the consent
```
Preview truncated: 30 total diff lines.

### /Users/mitch/dev/llm-memory-pyramid/scripts/repo_docs.py

```diff
--- /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/scripts/repo_docs.py

+++ /Users/mitch/dev/llm-memory-pyramid/scripts/repo_docs.py

@@ -0,0 +1,125 @@

+#!/usr/bin/env python3
+"""Generate static repository maps, or check their exact content without writes.
+
+This tool reads files and Git metadata only. It never imports runtime modules,
+contacts services, builds embeddings or touches a pyramid store.
+"""
+import argparse
+import ast
+import json
+from pathlib import Path
+import subprocess
+import sys
+
```
Preview truncated: 128 total diff lines.

## Blind re-audit

The first fresh-context review returned seven corroborated findings. Iteration 2 fixed all seven with failing-before/passing-after regressions. The second fresh-context review returned one further Medium: the Ollama wrapper parser missed RecursionError. That one-line boundary fix and a two-file failing-before/passing-after regression were completed after the optimizer loop stopped. No third independent gate ran. The required optimizer status remains BLIND-AUDIT-DISSENT; no independent CLEAN claim is made. All 35 corroborated runtime/test findings are now fixed. The new static-map generator also failed its first idempotence check; stable descriptions for generated outputs fixed that bootstrap-tool defect, and immediate regeneration/check now passes.

Protocol findings were checked against the supported MCP specification (integer/string non-null request IDs, one-way notifications, object params) and JSON-RPC notification rules:
https://modelcontextprotocol.io/specification/2025-06-18/basic/index
https://www.jsonrpc.org/specification#notification

## Summary

2 iterations · 18/18 fix-track passes active · standard profile · Final known-unfixed C/H/M 0/0/0 · Verify PASS · Status: BLIND-AUDIT-DISSENT (second gate dissented; final targeted fix verified without a third gate).

## Snapshot and rollback

Originals and per-iteration copies: /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/. The snapshot includes no private CI key. Restore only run-owned paths; preserve any later unrelated changes. To restore original tracked files and remove files this run added, review and use the commit reversal after delivery. Direct source restore example:

```bash
cp /Users/mitch/.claude/skill-consolidation/backups/llm-memory-pyramid-20261026T2155/memory_pyramid_distiller.py /Users/mitch/dev/llm-memory-pyramid/memory_pyramid_distiller.py
```

New source/test files require removal on a full manual rollback:
```bash
rm -- /Users/mitch/dev/llm-memory-pyramid/scripts/repo_docs.py
rm -- /Users/mitch/dev/llm-memory-pyramid/test_napmem_regressions.py
rm -- /Users/mitch/dev/llm-memory-pyramid/test_napmem_protocol.py
rm -- /Users/mitch/dev/llm-memory-pyramid/test_napmem_safety.py
```

CI dependency access is a dedicated read-only deploy key, id 167768571, on mithudso/ollama-client. Its private key exists only in the OLLAMA_CLIENT_DEPLOY_KEY Actions secret on mithudso/llm-memory-pyramid. Revoke both if rolling back CI access:
```bash
gh api --method DELETE repos/mithudso/ollama-client/keys/167768571
gh secret delete OLLAMA_CLIENT_DEPLOY_KEY -R mithudso/llm-memory-pyramid
```

## Index

index: static repository maps checked; external dossier refresh at final checkpoint; no semantic embeddings/indexing ran. Optimizer prose-index refresh is N/A outside its corpus roots.

## Memory-central

memory-central: 0 lesson files · 11 conventions consulted · 0 prior regression checks fired. Durable fixes are recorded in the repository work log and anchored Stele lessons. No central memory corpus was edited.
