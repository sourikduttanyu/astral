#!/usr/bin/env python3
"""Astral test suite - stdlib only, no pytest. Run: python3 tests/test_astral.py

Covers the behaviors that can bite: the context estimate (monitor), the
permission-affecting read-gate, and the audit's plugin classification.
"""
import json, os, sys, subprocess, tempfile, unittest, importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")


def _load(name):
    path = os.path.join(SCRIPTS, name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


monitor = _load("astral_monitor.py")
audit = _load("astral_audit.py")
statusline = _load("astral_statusline.py")
store = _load("astral_store.py")


def _transcript(rows):
    """Write JSONL transcript lines, return path. Each row: (in, cr, cc)."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for i, (it, cr, cc) in enumerate(rows):
            f.write(json.dumps({
                "timestamp": f"2026-06-{i+1:02d}T00:00:00Z",
                "message": {"usage": {"input_tokens": it,
                                      "cache_read_input_tokens": cr,
                                      "cache_creation_input_tokens": cc}},
            }) + "\n")
    return path


def _content_transcript(msgs, path=None):
    """Write a JSONL transcript of (role, text) messages; return its path.
    Reuses `path` (append) when given, so tests can grow a transcript."""
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
    with open(path, "a") as f:
        for i, (role, text) in enumerate(msgs):
            f.write(json.dumps({
                "uuid": f"{role}-{text[:8]}-{i}",
                "type": role,
                "message": {"role": role, "content": [{"type": "text", "text": text}]},
            }) + "\n")
    return path


def _run_precompact(transcript, cwd, trigger="auto", env=None):
    e = dict(os.environ)
    e.update(env or {})
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, "astral_precompact.py")],
        input=json.dumps({"transcript_path": transcript, "cwd": cwd,
                          "trigger": trigger, "session_id": "s"}),
        capture_output=True, text=True, env=e)


class TestMonitorTokens(unittest.TestCase):
    def test_latest_turn_wins(self):
        p = _transcript([(10, 100, 0), (20, 5000, 0)])
        self.assertEqual(monitor.real_tokens(p), 5020)
        os.unlink(p)

    def test_drops_after_compact(self):
        # big turn then a tiny post-compact turn -> reports the small one
        p = _transcript([(50, 150000, 0), (30, 800, 0)])
        self.assertEqual(monitor.real_tokens(p), 830)
        os.unlink(p)

    def test_no_usage_is_zero(self):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.write(fd, b'{"type":"user","message":{"content":"hi"}}\n')
        os.close(fd)
        self.assertEqual(monitor.real_tokens(p), 0)
        os.unlink(p)

    def test_missing_file_is_zero(self):
        self.assertEqual(monitor.real_tokens("/no/such/file.jsonl"), 0)


class TestWindowResolve(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ASTRAL_WINDOW", None)
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, ".astral"))

    def _set_user_window(self, v):
        with open(os.path.join(self.dir, ".astral", "window"), "w") as f:
            f.write(str(v))

    def test_floor_snaps_to_tier(self):
        self.assertEqual(monitor.floor_window(0), 200000)
        self.assertEqual(monitor.floor_window(199999), 200000)
        self.assertEqual(monitor.floor_window(200001), 1000000)   # past 200K -> 1M
        self.assertEqual(monitor.floor_window(2_000_000), 2_000_000)  # custom/huge

    def test_default_is_200k(self):
        self.assertEqual(monitor.resolve_window(50000, self.dir), (200000, "auto"))

    def test_occupancy_floor_lifts_to_1m(self):
        # 399K tokens with no compact proves the window is > 200K -> auto 1M
        self.assertEqual(monitor.resolve_window(399000, self.dir), (1000000, "auto"))

    def test_auto_window_is_sticky_after_compact(self):
        # Once occupancy proved 1M this session (prior), a /compact that drops
        # tokens back under 200K must NOT shrink the window back to 200K.
        self.assertEqual(monitor.resolve_window(40000, self.dir, prior=1000000),
                         (1000000, "auto"))
        # No prior -> floor governs as before.
        self.assertEqual(monitor.resolve_window(40000, self.dir, prior=0),
                         (200000, "auto"))

    def test_user_window_honored_and_floored(self):
        self._set_user_window(200000)
        self.assertEqual(monitor.resolve_window(50000, self.dir), (200000, "user"))
        # but live tokens can't be below the asserted window if they exceed it
        self.assertEqual(monitor.resolve_window(399000, self.dir), (1000000, "user"))

    def test_env_pins_exactly(self):
        os.environ["ASTRAL_WINDOW"] = "300000"
        self._set_user_window(1000000)
        try:
            self.assertEqual(monitor.resolve_window(50000, self.dir), (300000, "env"))
        finally:
            os.environ.pop("ASTRAL_WINDOW", None)

    # --- sad paths ---
    def test_garbage_env_is_ignored(self):
        os.environ["ASTRAL_WINDOW"] = "not-a-number"
        try:  # falls through to auto, doesn't crash
            self.assertEqual(monitor.resolve_window(50000, self.dir), (200000, "auto"))
        finally:
            os.environ.pop("ASTRAL_WINDOW", None)

    def test_garbage_user_file_is_ignored(self):
        for bad in ("abc", "", "  ", "-5", "0", "1e6"):
            with open(os.path.join(self.dir, ".astral", "window"), "w") as f:
                f.write(bad)
            self.assertIsNone(monitor.user_window(self.dir), bad)
            self.assertEqual(monitor.resolve_window(50000, self.dir)[1], "auto", bad)

    def test_user_file_with_whitespace_ok(self):
        with open(os.path.join(self.dir, ".astral", "window"), "w") as f:
            f.write("  1000000\n")
        self.assertEqual(monitor.user_window(self.dir), 1000000)

    def test_no_astral_dir_is_safe(self):
        empty = tempfile.mkdtemp()  # no .astral/ at all
        self.assertIsNone(monitor.user_window(empty))
        self.assertEqual(monitor.resolve_window(50000, empty), (200000, "auto"))

    def test_scan_reads_latest_model(self):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps({"message": {"model": "claude-sonnet-4-6",
                                            "usage": {"input_tokens": 10}}}) + "\n")
            # later turn = model switched to opus; synthetic line must not win
            f.write(json.dumps({"message": {"model": "<synthetic>",
                                            "usage": {"input_tokens": 5}}}) + "\n")
            f.write(json.dumps({"message": {"model": "claude-opus-4-8",
                                            "usage": {"input_tokens": 20}}}) + "\n")
        tokens, model = monitor.scan(p)
        self.assertEqual(tokens, 20)
        self.assertEqual(model, "claude-opus-4-8")
        os.unlink(p)


class TestMonitorHook(unittest.TestCase):
    def _run(self, payload, env=None):
        e = dict(os.environ)
        e.update(env or {})
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "astral_monitor.py")],
                           input=json.dumps(payload), capture_output=True, text=True, env=e)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_guard_always_present(self):
        out = self._run({"transcript_path": "", "cwd": tempfile.mkdtemp()})
        self.assertIn("unrelated to the session", out)

    def test_warns_when_band_crossed(self):
        p = _transcript([(0, 130000, 0)])  # 130k / 200k = 65%
        out = self._run({"transcript_path": p, "cwd": tempfile.mkdtemp()})
        self.assertIn("Context ~65", out)
        self.assertIn("checkpoint", out)
        os.unlink(p)

    def test_no_warn_when_low(self):
        p = _transcript([(0, 1000, 0)])  # 0.5%
        out = self._run({"transcript_path": p, "cwd": tempfile.mkdtemp()})
        self.assertNotIn("[Astral] Context", out)
        os.unlink(p)


class TestStateName(unittest.TestCase):
    def test_happy_session_id(self):
        self.assertEqual(monitor.state_name("abc123"), "state-abc123.json")
        self.assertEqual(monitor.state_name("a1b2-c3d4_e5"), "state-a1b2-c3d4_e5.json")

    def test_no_session_id_falls_back(self):
        self.assertEqual(monitor.state_name(None), "state.json")
        self.assertEqual(monitor.state_name(""), "state.json")

    def test_path_traversal_is_sanitized(self):
        # a malicious / weird session id must not escape .astral/ — only
        # [alnum-_] survive, so no slashes or dot-dot sequences remain.
        for sid in ("../../etc/passwd", "a/b/c", "..", "x/../y", "with spaces"):
            name = monitor.state_name(sid)
            # a plain filename in .astral/ — no separators, no dot-dot escape.
            # ".." sanitizes to empty and safely falls back to state.json.
            self.assertTrue(name == "state.json" or name.startswith("state-"), sid)
            self.assertTrue(name.endswith(".json"), sid)
            self.assertNotIn("/", name)
            self.assertNotIn("..", name)


class TestScanEdges(unittest.TestCase):
    def _write(self, lines):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        return p

    def test_partial_first_line_skipped(self):
        # tail cut can leave a broken first line; it must be skipped, rest parsed
        p = self._write(['{"message": {"usage": {"input_to',  # garbage fragment
                         json.dumps({"message": {"usage": {"input_tokens": 42}}})])
        self.assertEqual(monitor.scan(p), (42, None))
        os.unlink(p)

    def test_non_claude_model_ignored(self):
        p = self._write([json.dumps({"message": {"model": "gpt-4o",
                                                 "usage": {"input_tokens": 9}}})])
        tokens, model = monitor.scan(p)
        self.assertEqual(tokens, 9)
        self.assertIsNone(model)  # only claude-* ids count
        os.unlink(p)

    def test_input_only_usage_counts(self):
        p = self._write([json.dumps({"message": {"usage": {"input_tokens": 100}}})])
        self.assertEqual(monitor.scan(p)[0], 100)  # missing cache_* default to 0
        os.unlink(p)

    def test_empty_file(self):
        fd, p = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.assertEqual(monitor.scan(p), (0, None))
        os.unlink(p)


def _transcript_model(tokens, model):
    """One-line transcript with a given cache_read token count + model id."""
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps({"message": {"model": model,
                                        "usage": {"cache_read_input_tokens": tokens}}}) + "\n")
    return p


class TestPerSessionState(unittest.TestCase):
    def setUp(self):
        os.environ.pop("ASTRAL_WINDOW", None)
        self.dir = tempfile.mkdtemp()

    def _run(self, transcript="", sid=None, env=None):
        payload = {"transcript_path": transcript, "cwd": self.dir}
        if sid is not None:
            payload["session_id"] = sid
        e = dict(os.environ); e.update(env or {})
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "astral_monitor.py")],
                           input=json.dumps(payload), capture_output=True, text=True, env=e)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def _state(self, sid):
        with open(os.path.join(self.dir, ".astral", monitor.state_name(sid))) as f:
            return json.load(f)

    def _write_state(self, sid, d):
        os.makedirs(os.path.join(self.dir, ".astral"), exist_ok=True)
        with open(os.path.join(self.dir, ".astral", monitor.state_name(sid)), "w") as f:
            json.dump(d, f)

    def _set_user_window(self, v):
        os.makedirs(os.path.join(self.dir, ".astral"), exist_ok=True)
        with open(os.path.join(self.dir, ".astral", "window"), "w") as f:
            f.write(str(v))

    # --- happy: two terminals in one project don't clobber each other ---
    def test_sessions_isolated(self):
        a = _transcript([(0, 150000, 0)])   # 75% of 200k -> warns
        b = _transcript([(0, 1000, 0)])     # 0.5% -> quiet
        try:
            self._run(a, sid="sessA")
            self._run(b, sid="sessB")
            self.assertEqual(self._state("sessA")["tokens"], 150000)
            self.assertEqual(self._state("sessB")["tokens"], 1000)
            self.assertGreater(self._state("sessA")["band"], 0)
            self.assertEqual(self._state("sessB")["band"], 0)
        finally:
            os.unlink(a); os.unlink(b)

    def test_no_session_id_uses_shared_file(self):
        p = _transcript([(0, 1000, 0)])
        try:
            self._run(p, sid=None)
            self.assertTrue(os.path.isfile(os.path.join(self.dir, ".astral", "state.json")))
        finally:
            os.unlink(p)

    # --- edge: bands re-arm when the window changes (switch to smaller window) ---
    def test_rearm_on_window_drop(self):
        self._write_state("s", {"window": 1000000, "band": 70, "model": "claude-opus-4-8"})
        self._set_user_window(200000)              # user switches to a 200K tier
        p = _transcript([(0, 150000, 0)])          # 150k -> 75% of 200k
        try:
            out = self._run(p, sid="s")
            self.assertIn("Context ~75", out)      # re-armed, fires at the new window
        finally:
            os.unlink(p)

    def test_no_rewarn_same_window(self):
        self._write_state("s", {"window": 200000, "band": 70})
        self._set_user_window(200000)
        p = _transcript([(0, 150000, 0)])          # still 75%, band 70 already fired
        try:
            out = self._run(p, sid="s")
            self.assertNotIn("[Astral] Context", out)  # not re-armed -> no repeat
        finally:
            os.unlink(p)

    # --- model switching ---
    def test_model_change_prompts_when_ambiguous(self):
        self._write_state("s", {"model": "claude-sonnet-4-6", "window": 200000, "band": 0})
        p = _transcript_model(5000, "claude-opus-4-8")   # low tokens -> window ambiguous
        try:
            out = self._run(p, sid="s")
            self.assertIn("Model changed", out)
            self.assertIn("/astral:window", out)
        finally:
            os.unlink(p)

    def test_no_prompt_when_occupancy_resolves(self):
        self._write_state("s", {"model": "claude-sonnet-4-6", "window": 1000000, "band": 0})
        p = _transcript_model(400000, "claude-opus-4-8")  # >200k -> provably 1M, unambiguous
        try:
            self.assertNotIn("Model changed", self._run(p, sid="s"))
        finally:
            os.unlink(p)

    def test_env_suppresses_model_prompt(self):
        self._write_state("s", {"model": "claude-sonnet-4-6", "window": 300000, "band": 0})
        p = _transcript_model(5000, "claude-opus-4-8")
        try:
            self.assertNotIn("Model changed", self._run(p, sid="s", env={"ASTRAL_WINDOW": "300000"}))
        finally:
            os.unlink(p)


class TestStore(unittest.TestCase):
    CHUNKS = [
        {"cid": "a", "source": "snap-1", "text": "the auth middleware checks token expiry"},
        {"cid": "b", "source": "snap-1", "text": "database connection pool reuses sockets"},
        {"cid": "c", "source": "snap-2", "text": "the readgate delegates large file reads to a subagent"},
    ]

    def _store(self, force_scan):
        d = tempfile.mkdtemp()
        return store.Store(d, backend_override="scan" if force_scan else None)

    def _index(self, force_scan):
        s = self._store(force_scan)
        s.add(self.CHUNKS)
        return s

    def test_search_finds_right_chunk_both_backends(self):
        for scan in (False, True):
            s = self._index(scan)
            hits = s.search("token expiry", k=3)
            self.assertTrue(hits, f"scan={scan}")
            self.assertEqual(hits[0]["cid"], "a", f"scan={scan} -> {hits}")

    def test_empty_query_returns_nothing(self):
        for scan in (False, True):
            self.assertEqual(self._index(scan).search("   !!! ", k=3), [])

    def test_k_limit_respected(self):
        for scan in (False, True):
            s = self._index(scan)
            self.assertLessEqual(len(s.search("the", k=2)), 2)

    def test_punctuation_query_is_safe(self):
        # FTS5 syntax chars must not raise; should still match on the word tokens.
        s = self._index(False)
        hits = s.search('subagent: "reads"? (file)', k=3)
        self.assertEqual(hits[0]["cid"], "c")

    def test_durable_corpus_written(self):
        s = self._index(False)
        self.assertTrue(os.path.isfile(s.corpus))
        with open(s.corpus) as f:
            self.assertEqual(sum(1 for _ in f), 3)

    def test_scan_rebuildable_from_corpus(self):
        # A fresh scan-backed Store over the same dir searches the persisted corpus
        # (proves the index is rebuildable / the corpus is the durable source).
        s = self._index(False)
        reopened = store.Store(s.dir, backend_override="scan")
        self.assertEqual(reopened.search("database pool", k=1)[0]["cid"], "b")

    def test_blank_chunks_skipped(self):
        s = self._store(True)
        self.assertEqual(s.add([{"cid": "x", "source": "s", "text": "   "}]), 0)

    def test_chunk_turns_groups_per_turn(self):
        msgs = [
            {"role": "user", "uuid": "u1", "text": "fix the bug"},
            {"role": "assistant", "text": "found it in auth.py"},
            {"role": "user", "uuid": "u2", "text": "now add a test"},
            {"role": "assistant", "text": "added test_auth"},
        ]
        chunks = store.chunk_turns(msgs)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["cid"], "u1")
        self.assertIn("auth.py", chunks[0]["text"])
        self.assertIn("add a test", chunks[1]["text"])


class TestPrecompact(unittest.TestCase):
    TURNS = [("user", "fix the auth token bug"),
             ("assistant", "patched expiry check in auth.py"),
             ("user", "now add a regression test"),
             ("assistant", "added test_token_expiry")]

    def _corpus_count(self, cwd):
        p = os.path.join(cwd, ".astral", "store", "chunks.jsonl")
        if not os.path.isfile(p):
            return 0
        with open(p) as f:
            return sum(1 for line in f if line.strip())

    def _watermark(self, cwd):
        with open(os.path.join(cwd, ".astral", "store", "manifest.json")) as f:
            return json.load(f)["watermark"]

    def test_snapshots_and_indexes(self):
        cwd = tempfile.mkdtemp()
        t = _content_transcript(self.TURNS)
        try:
            self._run_ok(t, cwd)
            sdir = os.path.join(cwd, ".astral", "store")
            self.assertTrue(any(d.startswith("snap-") for d in os.listdir(sdir)))
            self.assertEqual(self._corpus_count(cwd), 2)   # 2 turns
            self.assertEqual(self._watermark(cwd), 4)       # 4 transcript lines
            hit = store.Store(sdir).search("auth token", k=1)
            self.assertTrue(hit)
        finally:
            os.unlink(t)

    def test_incremental_no_recopy(self):
        cwd = tempfile.mkdtemp()
        t = _content_transcript(self.TURNS)
        try:
            self._run_ok(t, cwd)
            self._run_ok(t, cwd)                            # nothing new
            self.assertEqual(self._corpus_count(cwd), 2)    # not doubled
        finally:
            os.unlink(t)

    def test_appends_new_turns(self):
        cwd = tempfile.mkdtemp()
        t = _content_transcript(self.TURNS)
        try:
            self._run_ok(t, cwd)
            _content_transcript([("user", "also handle refresh tokens"),
                                 ("assistant", "done")], path=t)
            self._run_ok(t, cwd)
            self.assertEqual(self._corpus_count(cwd), 3)    # +1 new turn
            self.assertEqual(self._watermark(cwd), 6)
        finally:
            os.unlink(t)

    def test_disabled_env_writes_nothing(self):
        cwd = tempfile.mkdtemp()
        t = _content_transcript(self.TURNS)
        try:
            _run_precompact(t, cwd, env={"ASTRAL_STORE": "0"})
            self.assertFalse(os.path.isdir(os.path.join(cwd, ".astral", "store")))
        finally:
            os.unlink(t)

    def test_missing_transcript_is_safe(self):
        cwd = tempfile.mkdtemp()
        r = _run_precompact("/no/such/file.jsonl", cwd)
        self.assertEqual(r.returncode, 0)

    def _run_ok(self, t, cwd):
        r = _run_precompact(t, cwd)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r


class TestStatusline(unittest.TestCase):
    def test_prefers_live_context_window(self):
        # Harness-provided used_percentage wins over any state file.
        data = {"context_window": {"used_percentage": 8, "context_window_size": 1000000}}
        self.assertEqual(statusline.pct_from_stdin(data), 8.0)

    def test_null_used_percentage_falls_through(self):
        # null right after /compact (or pre-first-call) -> no stdin pct, use fallback.
        self.assertIsNone(statusline.pct_from_stdin({"context_window": {"used_percentage": None}}))
        self.assertIsNone(statusline.pct_from_stdin({}))  # old Claude Code: no context_window

    def test_state_fallback_reads_per_session_file(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, ".astral"))
        with open(os.path.join(d, ".astral", "state-abc.json"), "w") as f:
            json.dump({"pct": 42.0}, f)
        data = {"workspace": {"current_dir": d}, "session_id": "abc"}
        self.assertEqual(statusline.pct_from_state(data), 42.0)

    def test_color_escalates_with_pct(self):
        # calm < first band; danger >= last band.
        self.assertEqual(statusline.color_for(10), statusline.COLORS[0])
        self.assertEqual(statusline.color_for(95), statusline.COLORS[-1])
        self.assertGreaterEqual(statusline.color_for(95), 0)


class TestReadgate(unittest.TestCase):
    def _run(self, tool_input, env=None):
        e = dict(os.environ)
        e.update(env or {})
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "astral_readgate.py")],
                           input=json.dumps({"tool_name": "Read", "tool_input": tool_input}),
                           capture_output=True, text=True, env=e)
        return r.stdout.strip()

    def _file(self, nbytes, suffix=".txt"):
        fd, p = tempfile.mkstemp(suffix=suffix)
        os.write(fd, b"x" * nbytes)
        os.close(fd)
        return p

    def test_small_passes_through(self):
        p = self._file(400)
        self.assertEqual(self._run({"file_path": p}), "")
        os.unlink(p)

    def test_large_text_asks(self):
        p = self._file(60000)  # ~15k tok
        out = json.loads(self._run({"file_path": p}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")
        os.unlink(p)

    def test_image_skipped(self):
        p = self._file(60000, suffix=".png")
        self.assertEqual(self._run({"file_path": p}), "")
        os.unlink(p)

    def test_limit_bypasses(self):
        p = self._file(60000)
        self.assertEqual(self._run({"file_path": p, "limit": 50}), "")
        os.unlink(p)

    def test_threshold_env(self):
        p = self._file(60000)
        # raise threshold above the file -> passes through
        self.assertEqual(self._run({"file_path": p}, env={"ASTRAL_READ_TOKENS": "999999"}), "")
        os.unlink(p)

    def test_allowlist_bypasses(self):
        p = self._file(60000, suffix=".csv")
        # without allow -> asks
        self.assertIn("permissionDecision", self._run({"file_path": p}))
        # with matching glob -> passes through
        self.assertEqual(self._run({"file_path": p}, env={"ASTRAL_READ_ALLOW": "*.csv"}), "")
        os.unlink(p)


class TestAuditClassify(unittest.TestCase):
    def test_frontmatter(self):
        fd, p = tempfile.mkstemp(suffix=".md")
        os.write(fd, b'---\nname: My Agent\ndescription: does things\n---\nbody\n')
        os.close(fd)
        self.assertEqual(audit._frontmatter(p), ("My Agent", "does things"))
        os.unlink(p)

    def test_plugin_flags_hooks_and_mcp(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "hooks"))
        has_hooks, is_mcp = audit._plugin_flags(d)
        self.assertTrue(has_hooks)
        self.assertFalse(is_mcp)

    def test_plugin_rows_buckets(self):
        # monkeypatch plugins() to a synthetic inventory
        orig = audit.plugins
        audit.plugins = lambda: {
            "real": {"id": "real@m", "install_path": "", "agents": 1, "skills": 0,
                     "commands": 0, "tok": 50, "hooks": False, "opaque": False},
            "hooky": {"id": "hooky@m", "install_path": "", "agents": 0, "skills": 1,
                      "commands": 0, "tok": 10, "hooks": True, "opaque": False},
            "mcpish": {"id": "mcpish@m", "install_path": "", "agents": 0, "skills": 0,
                       "commands": 0, "tok": 0, "hooks": False, "opaque": True},
        }
        try:
            use = {}  # nothing used
            rows = {r["plugin"]: r for r in audit.plugin_rows(use)}
        finally:
            audit.plugins = orig
        self.assertEqual(rows["real"]["bucket"], "NEVER")
        self.assertTrue(rows["real"]["prunable"])
        self.assertEqual(rows["hooky"]["bucket"], "HOOK")
        self.assertFalse(rows["hooky"]["prunable"])      # never auto-prune hook plugins
        self.assertEqual(rows["mcpish"]["bucket"], "MCP?")
        self.assertFalse(rows["mcpish"]["prunable"])     # never auto-prune opaque/MCP


if __name__ == "__main__":
    unittest.main(verbosity=2)
