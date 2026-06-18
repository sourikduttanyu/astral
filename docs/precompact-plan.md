# Astral PreCompact + Recall — design & build plan

Status: planned (not yet built). Decisions locked 2026-06-18.

## Goal

Let Astral re-fetch context that auto-compaction evicted. Today Astral only
manages what stays in-context (Watcher warns; Checkpoint sheds; Read-gate keeps
big reads out). This adds **automatic eviction-aware re-fetch**: capture the
about-to-be-evicted context before compaction, then let the model pull the
right slice back on demand.

## Key realization

The transcript JSONL already persists on disk after compaction — compaction
rewrites the *in-context working set*, it does not delete `transcript_path`. So
evicted data isn't gone, just out of context. The feature is therefore about
**indexing for retrieval**, not merely backing data up. (We still snapshot a
durable copy — see decisions — so the store is self-contained if the transcript
is ever rotated/deleted.)

## Why a tool, not a hook, does the re-fetch

A hook can't act mid-turn (hooks only fire on prompt-submit / pre-read / etc. and
can't run commands — they emit text that instructs the agent). An MCP **tool**
can: the model invokes `recall()` itself when a later step needs dropped data, so
from the outside it looks automatic. That distinction is the whole unlock.

Verified primitives (official docs):
- `PreCompact` hook fires **before compaction, on auto and manual** (matcher
  `auto` / `manual`; payload has `trigger`, `transcript_path`, `session_id`).
  It can even return `decision: "block"` to hold compaction.
- Plugins ship an MCP server via `.mcp.json` at plugin root, `command` using
  `${CLAUDE_PLUGIN_ROOT}`.

## Locked decisions

1. **Retrieval trigger:** MCP `recall()` from day one (model-autonomous).
2. **Capture scope:** full snapshot each compaction — durable copy of the evicted
   slice — but **incremental via a watermark** so repeated compactions don't
   re-copy already-snapshotted turns.
3. **MCP deps:** hand-roll a minimal JSON-RPC-over-stdio MCP server in **pure
   Python stdlib**. Keeps the repo's "stdlib only, zero deps" invariant intact.
   Cost: ~150 lines of protocol we maintain against the MCP spec.
4. **Storage + search (Option C — hybrid):** evicted slices are snapshotted as
   readable flat files (the durable truth, matches the full-snapshot decision and
   the `.astral/checkpoint-*.md` style). The search index is **SQLite FTS5**
   (`sqlite3` is stdlib; FTS5 gives BM25 ranking for free) and is treated as
   **derived + rebuildable** from the snapshots. Fail-open: if FTS5 isn't compiled
   into the runtime's `sqlite3`, feature-detect and fall back to an in-memory
   keyword scan over the snapshot files. No hand-rolled BM25.
   - **`sqlite3` is stdlib, not a dep** (no `pip install`, same category as
     `json`/`os`). Backend is detected at runtime via guarded import:
     `fts5` (sqlite3 + FTS5 present) → `scan` (sqlite3/FTS5 missing → pure-stdlib
     in-memory keyword scan over the snapshot files). Worst case still works,
     only search speed varies. Zero third-party deps in every path.
   - **No vector DB / embeddings in core.** Embeddings need a third-party model
     lib (breaks zero-dep) or a remote API call (network in a hook = slow/fragile,
     and ships conversation off-box = privacy regression). The job is recalling
     the model's *own* session with queries it writes — high lexical overlap,
     where BM25 is strongest. An **optional embedding layer is a v3 add-on**,
     behind a dependency boundary and opt-in, for semantic recall across
     diverging vocabulary. Retrieval quality is the main risk — bench it like
     `bench/` benches context.
5. **No blocking:** PreCompact runs before eviction, so data is intact when it
   fires; snapshot synchronously and exit 0. `decision:block` risks wedging the
   session — avoid by default.
6. Per-turn chunking (user+assistant+tool grouped). `.astral/store/` gitignored,
   symlink-refused. Config: `ASTRAL_STORE` (on/off), `ASTRAL_RECALL_K` (top-k).

## Architecture

### New files
- `scripts/astral_precompact.py` — `PreCompact` hook. Reads `transcript_path`,
  takes new-since-watermark turns, snapshots them as readable files in
  `.astral/store/snap-<ts>/`, chunks per-turn, and indexes the chunks into the
  SQLite FTS5 table in `.astral/store/store.db` (watermark + chunk→file map also
  in the db). Fail-open; index is rebuildable from the snapshot files.
- `servers/astral_recall_mcp.py` — stdio MCP server (stdlib JSON-RPC). Implements
  `initialize`, `tools/list`, `tools/call`. One tool: `recall(query, k)` →
  FTS5 BM25 query over `store.db` (in-memory scan over snapshot files if FTS5 is
  unavailable) → top-k chunks (text + source pointer).
- `.mcp.json` — wires the server:
  `python3 ${CLAUDE_PLUGIN_ROOT}/servers/astral_recall_mcp.py`.

### Edits
- `hooks/hooks.json` — add `PreCompact` (matcher `auto` + `manual`).
- `scripts/astral_monitor.py` — post-compaction nudge: tell the model evicted
  detail is recallable via `recall()`.
- `install.sh` / `install.ps1` — copy `servers/`, wire `.mcp.json`.
- `README.md` + config table — document `ASTRAL_STORE`, `ASTRAL_RECALL_K` and the
  new capture/recall behavior.
- `tests/test_astral.py` — chunker, index build, BM25 scoring, watermark
  increment (no re-copy), JSON-RPC handshake + a `recall` call.

### Data flow
context fills → `PreCompact(auto)` fires → snapshot + index evicted slice →
compaction proceeds → later step needs dropped data → model calls
`recall("...")` → slice returns to context. Model-initiated ⇒ looks automatic.

## Build sequence (each step verifiable)

1. **Index core** — chunker + FTS5 index builder/query, with FTS5 feature-detect
   and in-memory-scan fallback. Verify: unit tests; search returns the right chunk
   on a fixture, both with FTS5 and via the fallback path.
2. **PreCompact hook** — snapshot + incremental index via watermark.
   Verify: feed fake transcript + `trigger:auto` on stdin → store files +
   watermark advance; re-run → no re-copy.
3. **MCP server** — stdlib JSON-RPC stdio; initialize / tools/list / tools/call.
   Verify: pipe handshake + a `recall` call → spec-shaped responses.
4. **Wiring** — `.mcp.json`, `hooks.json`, monitor nudge, installers.
   Verify: `claude plugin validate .` passes; manual `/plugin` smoke test.
5. **Docs** — Verify: README ↔ code config in sync.

## Open / to-verify during build

- Exact MCP protocol version string to advertise in `initialize`.
- Confirm `PreCompact` fires on auto-compact in the user's installed CC version
  (docs confirm; smoke-test locally).
- Store growth cap / prune-oldest (`ASTRAL_STORE_MAX`?) — defer unless needed.
- FTS5 + `bm25()` confirmed available on the dev runtime (SQLite 3.51.0). The
  in-memory-scan fallback is still required for portability (FTS5 is a
  compile-time option, not guaranteed on every user's Python).
