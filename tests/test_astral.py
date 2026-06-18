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
