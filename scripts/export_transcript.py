"""Render a Claude Code session log (.jsonl) as readable Markdown.

Faithful but condensed: every user message and every assistant text block is kept verbatim; tool calls are kept with
their inputs truncated; tool results are truncated; images and 'thinking' blocks are omitted (counted, not shown).
The owner's e-mail address is redacted. Usage:
    python scripts/export_transcript.py <session.jsonl> <out.md> [--redact STRING ...]
"""
import json
import re
import sys

MAX_IN, MAX_OUT = 1500, 1200


def clip(s: str, n: int) -> str:
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f"\n… [truncated {len(s) - n} chars]"


def blocks(msg):
    c = msg.get("content")
    if isinstance(c, str):
        return [{"type": "text", "text": c}]
    return c or []


def render(path, out, redact):
    pats = [re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")] + [re.compile(re.escape(x)) for x in redact]
    def scrub(t):
        for p in pats:
            t = p.sub("<redacted>", t)
        return t
    n_img = n_think = 0
    lines = ["# Claude Code session transcript (rendered)", "",
             "Rendered from the raw session log by `scripts/export_transcript.py`. User messages and assistant text are verbatim; "
             "tool inputs/outputs are truncated; images and thinking blocks are omitted; e-mail addresses are redacted.", ""]
    for raw in open(path, encoding="utf-8"):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = d.get("type")
        if t not in ("user", "assistant"):
            continue
        msg = d.get("message", {})
        role = "USER" if t == "user" else "ASSISTANT"
        parts = []
        for b in blocks(msg):
            k = b.get("type")
            if k == "text" and b.get("text", "").strip():
                parts.append(b["text"].strip())
            elif k == "tool_use":
                parts.append(f"**tool call `{b.get('name')}`**\n```\n{clip(b.get('input', {}), MAX_IN)}\n```")
            elif k == "tool_result":
                c = b.get("content")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", "[image]") if x.get("type") == "text" else "[image omitted]" for x in c)
                parts.append(f"*tool result:*\n```\n{clip(c or '', MAX_OUT)}\n```")
            elif k == "image":
                n_img += 1
            elif k == "thinking":
                n_think += 1
        if parts:
            lines += [f"## {role}", "", scrub("\n\n".join(parts)), ""]
    lines += ["", f"_Omitted: {n_img} images, {n_think} thinking blocks._"]
    open(out, "w", encoding="utf-8").write("\n".join(lines))


if __name__ == "__main__":
    a = sys.argv[1:]
    red = [a[i + 1] for i, x in enumerate(a) if x == "--redact"]
    render(a[0], a[1], red)
