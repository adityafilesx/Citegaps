"""Live smoke test: one real Search + one real Fetch (ttl 0). Needs TINYFISH_API_KEY in .env or the environment.

    python scripts/smoke.py [url]
"""
import asyncio
import sys

from citegap.config import load_dotenv, load_settings, mask_key
from citegap.tinyfish.client import TinyFishClient
from citegap.tinyfish.fetch import fetch_many
from citegap.tinyfish.search import run_probe


async def main(url: str) -> int:
    load_dotenv()
    s = load_settings()
    if not s.tinyfish_api_key:
        print("TINYFISH_API_KEY missing. Add it to .env (see .env.example).")
        return 2
    print("key:", mask_key(s.tinyfish_api_key))
    c = TinyFishClient(s)
    probe = await run_probe(c, "target_query", "web automation tools")
    print(f"search: {len(probe.results)} results", probe.error or "")
    for r in probe.results[:3]:
        print(f"  #{r.position} {r.title[:60]} — {r.url}")
    batch = await fetch_many(c, [url], summary="smoke fetch")
    ok = batch.results.get(url)
    print("fetch:", f"{len(ok.text or '')} chars, final_url={ok.final_url}" if ok else batch.errors.get(url) or batch.request_error)
    for e in c.calls:
        print(f"  call {e.id} {e.endpoint} ttl={e.ttl} {e.status} {e.latency_ms} ms")
    await c.aclose()
    return 0 if probe.results and ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "https://www.tinyfish.ai/")))
