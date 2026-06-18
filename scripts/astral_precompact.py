#!/usr/bin/env python3
"""Astral PreCompact hook — capture context before it's evicted.

Fires on `PreCompact` (auto-compact AND manual /compact). Claude Code rewrites
the in-context working set on compaction but does NOT delete the transcript, so
this hook's job is to make the about-to-be-evicted turns *retrievable*: it
snapshots the new-since-last-run turns to readable files under
`.astral/store/snap-<ts>/` and indexes them via astral_store (FTS5 or scan).

Incremental: a line watermark in `.astral/store/manifest.json` means repeated
compactions only process turns added since the previous run — no re-copying.

Fail-open: any error -> exit 0 without touching the host. Compaction is never
blocked. Disable entirely with ASTRAL_STORE=0/off/false.
"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import astral_store
except Exception:
    astral_store = None


def _disabled():
    return os.environ.get("ASTRAL_STORE", "").strip().lower() in ("0", "off", "false", "no")


def _msg_text(o):
    """(role, text) extracted from one transcript line; ('', '') if nothing."""
    msg = o.get("message") or {}
    role = msg.get("role") or o.get("type") or ""
    content = msg.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", ""))
            elif t == "tool_use":
                parts.append(f"[tool_use {b.get('name', '')}] "
                             + json.dumps(b.get("input", {}))[:500])
            elif t == "tool_result":
                c = b.get("content")
                if isinstance(c, str):
                    parts.append(c)
                elif isinstance(c, list):
                    for cc in c:
                        if isinstance(cc, dict) and cc.get("type") == "text":
                            parts.append(cc.get("text", ""))
    return role, "\n".join(p for p in parts if p)


def _messages(lines):
    out = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        role, text = _msg_text(o)
        if text.strip():
            out.append({"role": role, "text": text, "uuid": o.get("uuid")})
    return out


def _safe(name):
    return "".join(c for c in str(name) if c.isalnum() or c in "-_") or "chunk"


def main():
    if _disabled() or astral_store is None:
        return
    try:
        data = json.load(sys.stdin)
    except Exception:
        return

    transcript = data.get("transcript_path", "")
    cwd = data.get("cwd") or os.getcwd()
    if not transcript or not os.path.isfile(transcript):
        return

    store_dir = os.path.join(cwd, ".astral", "store")
    manifest_path = os.path.join(store_dir, "manifest.json")
    try:
        os.makedirs(store_dir, exist_ok=True)
    except OSError:
        return

    manifest = {}
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except Exception:
        pass
    wm = manifest.get("watermark", 0)
    if not isinstance(wm, int) or wm < 0:
        wm = 0

    try:
        with open(transcript, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return

    # New transcript / rotation -> reprocess from the start.
    if wm > len(lines):
        wm = 0
    new = lines[wm:]
    chunks = astral_store.chunk_turns(_messages(new))

    if chunks:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        snap_dir = os.path.join(store_dir, f"snap-{ts}")
        try:
            os.makedirs(snap_dir, exist_ok=True)
            for c in chunks:
                with open(os.path.join(snap_dir, _safe(c["cid"]) + ".md"),
                          "w", encoding="utf-8") as f:
                    f.write(c["text"])
        except OSError:
            pass
        try:
            astral_store.Store(store_dir).add(chunks)
        except Exception:
            pass

    manifest.update({"watermark": len(lines),
                     "last_trigger": data.get("trigger", ""),
                     "updated": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())})
    try:
        with open(manifest_path, "w") as f:
            json.dump(manifest, f)
    except OSError:
        pass


if __name__ == "__main__":
    main()
