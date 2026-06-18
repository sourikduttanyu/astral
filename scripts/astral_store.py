#!/usr/bin/env python3
"""Astral store — searchable index over evicted context (Option C, step 1).

Flat-file snapshots are the durable truth (written by astral_precompact.py); this
module builds and queries the *derived* search index over them. The backend is
chosen at runtime so there is never a third-party dependency:

  * ``fts5``  — ``sqlite3`` (stdlib) with the FTS5 extension: real BM25 ranking.
  * ``scan``  — pure-stdlib in-memory keyword scan, used when ``sqlite3`` or FTS5
                isn't compiled into the runtime. Slower, same results shape.

A normalized ``chunks.jsonl`` is always appended in the store dir; it doubles as
the rebuild source for the FTS5 db and as the corpus the scan backend reads. So
the store works in every environment — only search speed varies.

Public API:
    Store(store_dir)         open/create a store (auto-detects backend)
      .add(chunks)           index an iterable of {"cid","source","text"} dicts
      .search(query, k=5)    -> list of {"cid","source","text","score"}, best first
    backend()                "fts5" or "scan" (respects ASTRAL_FORCE_SCAN)
"""
import os, re, json

_WORD = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text):
    return _WORD.findall((text or "").lower())


def backend():
    """Detect the index backend once. ASTRAL_FORCE_SCAN=1 forces the fallback
    (used by tests and by anyone who wants to avoid the db)."""
    if os.environ.get("ASTRAL_FORCE_SCAN"):
        return "scan"
    try:
        import sqlite3
    except ImportError:
        return "scan"
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        c.close()
        return "fts5"
    except Exception:
        return "scan"


def _fts_match(query):
    """Turn an arbitrary query into a safe FTS5 MATCH expression: quote each
    word token and OR them. Returns None when the query has no usable tokens
    (so the caller can short-circuit to an empty result)."""
    toks = _tokens(query)
    if not toks:
        return None
    return " OR ".join('"' + t + '"' for t in toks)


class Store:
    def __init__(self, store_dir, backend_override=None):
        self.dir = store_dir
        os.makedirs(store_dir, exist_ok=True)
        self.corpus = os.path.join(store_dir, "chunks.jsonl")
        self.backend = backend_override or backend()
        self._db = None
        if self.backend == "fts5":
            import sqlite3
            self._db = sqlite3.connect(os.path.join(store_dir, "store.db"))
            self._db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks "
                "USING fts5(cid UNINDEXED, source UNINDEXED, text)"
            )
            self._db.commit()

    def add(self, chunks):
        """Append chunks to the durable corpus and (fts5) into the index.
        Each chunk: {"cid": str, "source": str, "text": str}."""
        rows = [c for c in chunks if (c.get("text") or "").strip()]
        if not rows:
            return 0
        with open(self.corpus, "a", encoding="utf-8") as f:
            for c in rows:
                f.write(json.dumps({"cid": c.get("cid", ""),
                                    "source": c.get("source", ""),
                                    "text": c["text"]}) + "\n")
        if self._db is not None:
            self._db.executemany(
                "INSERT INTO chunks(cid, source, text) VALUES (?,?,?)",
                [(c.get("cid", ""), c.get("source", ""), c["text"]) for c in rows],
            )
            self._db.commit()
        return len(rows)

    def search(self, query, k=5):
        if self.backend == "fts5":
            return self._search_fts5(query, k)
        return self._search_scan(query, k)

    def _search_fts5(self, query, k):
        match = _fts_match(query)
        if not match:
            return []
        cur = self._db.execute(
            "SELECT cid, source, text, bm25(chunks) AS score "
            "FROM chunks WHERE chunks MATCH ? ORDER BY score LIMIT ?",
            (match, k),
        )
        # bm25() is lower=better; flip the sign so higher score = better, matching
        # the scan backend's convention.
        return [{"cid": r[0], "source": r[1], "text": r[2], "score": -r[3]}
                for r in cur.fetchall()]

    def _search_scan(self, query, k):
        """Pure-stdlib fallback: term-frequency overlap over the corpus."""
        qt = _tokens(query)
        if not qt:
            return []
        qset = set(qt)
        scored = []
        for c in self._iter_corpus():
            toks = _tokens(c["text"])
            if not toks:
                continue
            score = sum(1 for t in toks if t in qset)
            if score:
                scored.append((score, c))
        scored.sort(key=lambda s: s[0], reverse=True)
        return [{"cid": c["cid"], "source": c["source"], "text": c["text"],
                 "score": float(score)} for score, c in scored[:k]]

    def _iter_corpus(self):
        try:
            with open(self.corpus, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        yield json.loads(line)
        except OSError:
            return


def chunk_turns(messages):
    """Group a flat list of transcript messages into per-turn chunks.

    A turn = a user message and everything up to (not including) the next user
    message (the assistant + tool traffic it produced). Each message is a dict
    with at least ``role`` and ``text``; ``uuid`` (if present) seeds the chunk id.
    Returns a list of {"cid","source","text"} ready for Store.add.
    """
    chunks, cur = [], []

    def flush():
        if not cur:
            return
        text = "\n".join(m.get("text", "") for m in cur if m.get("text"))
        if text.strip():
            cid = cur[0].get("uuid") or f"turn-{len(chunks)}"
            chunks.append({"cid": cid, "source": cid, "text": text})
        cur.clear()

    for m in messages:
        if m.get("role") == "user" and cur:
            flush()
        cur.append(m)
    flush()
    return chunks
