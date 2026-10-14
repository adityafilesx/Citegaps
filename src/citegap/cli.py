"""`citegap audit <url> --query "..."` and `citegap serve`."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_dotenv, load_settings
from .fixes.llm_rewrite import llm_suggestions
from .pipeline import AuditError, run_audit
from .report.fixpack import build_fixpack
from .report.render_md import render_markdown
from .store import Store


def _progress(e: dict) -> None:
    c = e.get("tinyfish_call")
    if c:
        if c["status"] != "pending":
            print(f"  · {c['endpoint']:<6} {c['summary']} → {c['status']} {c['latency_ms']} ms", file=sys.stderr)
    else:
        print(f"[{e['stage']}] {e['message']}", file=sys.stderr)


async def _audit(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.tinyfish_api_key:
        print("TINYFISH_API_KEY is not set (put it in .env or the environment).", file=sys.stderr)
        return 2
    store = Store(settings.db_path)
    try:
        rep = await run_audit(args.url if args.url.startswith("http") else "https://" + args.url, args.query, settings=settings,
                              emit=None if args.quiet else _progress, store=store)
    except (AuditError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    store.save(rep)
    out = render_markdown(rep) if args.format == "md" else rep.model_dump_json(indent=2)
    if args.out:
        d = Path(args.out)
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.md").write_text(render_markdown(rep), encoding="utf-8")
        (d / "report.json").write_text(rep.model_dump_json(indent=2), encoding="utf-8")
        if args.fixpack:
            llm = await llm_suggestions(rep, settings, None, (rep.serp_card or {}).get("meta_description"))
            (d / f"citegap-fixpack-{rep.id}.zip").write_bytes(build_fixpack(rep, llm))
        print(f"wrote {d}/", file=sys.stderr)
    else:
        print(out)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="citegap", description="AI-readability x search-visibility auditor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit", help="audit a public URL")
    a.add_argument("url")
    a.add_argument("--query", "-q", default=None, help="target query (derived from the page if omitted)")
    a.add_argument("--format", choices=["md", "json"], default="md")
    a.add_argument("--out", help="write report.md, report.json (and the fix pack) to this directory")
    a.add_argument("--fixpack", action="store_true", help="with --out: also write the fix pack zip")
    a.add_argument("--quiet", action="store_true")
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("citegap.api:app_factory", factory=True, host=args.host, port=args.port)
        return 0
    return asyncio.run(_audit(args))


if __name__ == "__main__":
    raise SystemExit(main())
