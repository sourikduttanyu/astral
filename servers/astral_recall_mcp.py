#!/usr/bin/env python3
"""Astral recall — a minimal MCP server (stdlib only, no `mcp` SDK).

Exposes one tool, `recall(query, k)`, that searches Astral's snapshot store of
context evicted by earlier compactions (written by astral_precompact.py) and
returns the most relevant chunks. The model calls it mid-task when it needs
detail that's no longer in context — a hook can't act mid-turn, but a tool can,
so re-hydration looks automatic from the outside.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio). We
implement just enough of the protocol: initialize, tools/list, tools/call,
ping, and the initialized notification. Everything is stdlib.

Store location: ASTRAL_STORE_DIR if set, else <cwd>/.astral/store. The server is
launched by Claude Code with the project as its working directory.
"""
import sys, os, json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
try:
    import astral_store
except Exception:
    astral_store = None

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "astral-recall", "version": "0.1.0"}

RECALL_TOOL = {
    "name": "recall",
    "description": (
        "Re-fetch context that auto-compaction evicted. Searches Astral's "
        "snapshot store of this session's earlier turns and returns the most "
        "relevant chunks. Use when you need detail from earlier in the session "
        "that is no longer in context (identifiers, file names, decisions, error "
        "text)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "What to look for: keywords, identifiers, "
                                     "file names, error text."},
            "k": {"type": "integer",
                  "description": "Max chunks to return (default 5)."},
        },
        "required": ["query"],
    },
}


def _store_dir():
    return os.environ.get("ASTRAL_STORE_DIR") or os.path.join(os.getcwd(), ".astral", "store")


def _do_recall(args):
    query = (args or {}).get("query", "")
    k = (args or {}).get("k") or 5
    try:
        k = max(1, int(k))
    except (TypeError, ValueError):
        k = 5
    if astral_store is None:
        return "Astral store unavailable (astral_store import failed)."
    hits = astral_store.Store(_store_dir()).search(query, k)
    if not hits:
        return f"No matching context found in the Astral store for: {query!r}"
    out = [f"{len(hits)} chunk(s) recalled for {query!r}:\n"]
    for i, h in enumerate(hits, 1):
        out.append(f"--- [{i}] source={h['source']} (score {h['score']:.3f}) ---\n{h['text']}")
    return "\n\n".join(out)


def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle(req):
    """Return a response dict for a request, or None for a notification."""
    method = req.get("method")
    rid = req.get("id")
    is_notification = "id" not in req

    if method == "initialize":
        params = req.get("params") or {}
        return _result(rid, {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method in ("notifications/initialized", "initialized"):
        return None  # notification, no reply
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": [RECALL_TOOL]})
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name")
        if name != "recall":
            return _error(rid, -32602, f"Unknown tool: {name}")
        try:
            text = _do_recall(params.get("arguments") or {})
            return _result(rid, {"content": [{"type": "text", "text": text}]})
        except Exception as e:  # tool error surfaced to the model, server stays up
            return _result(rid, {"content": [{"type": "text", "text": f"recall failed: {e}"}],
                                 "isError": True})

    if is_notification:
        return None
    return _error(rid, -32601, f"Method not found: {method}")


def main():
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue  # ignore unparseable lines
        try:
            resp = handle(req)
        except Exception as e:
            resp = _error(req.get("id"), -32603, f"Internal error: {e}")
        if resp is not None:
            out.write(json.dumps(resp) + "\n")
            out.flush()


if __name__ == "__main__":
    main()
