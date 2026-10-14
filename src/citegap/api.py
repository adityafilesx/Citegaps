"""FastAPI: POST /audit, GET /audit/{id}/events (SSE), GET /audit/{id}, fixpack, permalinks, static UI."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Settings, load_dotenv, load_settings, mask_key
from .fixes.llm_rewrite import llm_suggestions
from .pipeline import AuditError, run_audit
from .report.fixpack import build_fixpack
from .report.model import Report
from .report.render_md import render_markdown
from .store import Store
from .tinyfish.client import TinyFishClient
from .util import check_public_url

WEB_DIR = Path(__file__).resolve().parents[2] / "web"


class AuditRequest(BaseModel):
    url: str
    query: Optional[str] = None
    deep: bool = False


class Job:
    def __init__(self, job_id: str, url: str, query: Optional[str], deep: bool = False):
        self.id, self.url, self.query, self.deep = job_id, url, query, deep
        self.events: list[dict] = []
        self.done = False
        self.error: Optional[str] = None
        self.cond = asyncio.Condition()
        self.created = time.time()

    def add(self, ev: dict) -> None:
        """Synchronous append keeps event order deterministic; waiters are woken afterwards."""
        self.events.append(ev)
        asyncio.get_event_loop().create_task(self._notify())

    async def _notify(self) -> None:
        async with self.cond:
            self.cond.notify_all()

    async def finish(self, error: Optional[str] = None) -> None:
        self.error, self.done = error, True
        await self._notify()


class RateLimiter:
    def __init__(self, per_minute: int, per_hour: int):
        self.pm, self.ph = per_minute, per_hour
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.time()
        q = self.hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        last_min = sum(1 for t in q if now - t <= 60)
        if last_min >= self.pm:
            return False, 60
        if len(q) >= self.ph:
            return False, int(3600 - (now - q[0]))
        q.append(now)
        return True, 0


def create_app(settings: Optional[Settings] = None, client_factory: Optional[Callable[[Settings], TinyFishClient]] = None,
               raw_transport=None, resolver=None, store: Optional[Store] = None) -> FastAPI:
    load_dotenv()
    settings = settings or load_settings()
    store = store or Store(settings.db_path)
    jobs: dict[str, Job] = {}
    limiter = RateLimiter(settings.audits_per_minute, settings.audits_per_hour)
    app = FastAPI(title="CiteGap", version="0.1.0")

    def client_ip(req: Request) -> str:
        fwd = req.headers.get("x-forwarded-for")
        return (fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "unknown"))

    async def runner(job: Job, previous_of: Optional[str] = None) -> None:
        client = client_factory(settings) if client_factory else TinyFishClient(settings)
        try:
            rep = await run_audit(job.url, job.query, settings=settings, client=client, emit=job.add,
                                  raw_transport=raw_transport, resolver=resolver, audit_id=job.id, store=store, deep=job.deep)
            store.save(rep)
            job.add({"stage": "report", "message": "Report ready", "report_id": rep.id})
            await job.finish()
        except (AuditError, ValueError) as exc:
            job.add({"stage": "error", "message": str(exc)})
            await job.finish(str(exc))
        except Exception as exc:  # never leak internals or keys
            job.add({"stage": "error", "message": f"Audit failed unexpectedly ({type(exc).__name__})."})
            await job.finish(type(exc).__name__)
        finally:
            await client.aclose()

    def start(url: str, query: Optional[str], deep: bool = False) -> Job:
        job = Job(uuid.uuid4().hex[:10], url, (query or "").strip() or None, deep)
        jobs[job.id] = job
        if len(jobs) > 200:
            for k in sorted(jobs, key=lambda k: jobs[k].created)[:50]:
                if jobs[k].done:
                    jobs.pop(k, None)
        asyncio.get_event_loop().create_task(runner(job))
        return job

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "tinyfish_key": mask_key(settings.tinyfish_api_key) if settings.tinyfish_api_key else "<unset>"}

    @app.post("/audit")
    async def post_audit(body: AuditRequest, request: Request):
        url = body.url.strip()
        if "://" not in url:
            url = "https://" + url
        ok, reason, _ = check_public_url(url, resolver) if resolver else check_public_url(url)
        if not ok:
            raise HTTPException(400, f"URL rejected: {reason}")
        if not settings.tinyfish_api_key and not client_factory:
            raise HTTPException(503, "Server is missing TINYFISH_API_KEY.")
        allowed, retry = limiter.allow(client_ip(request))
        if not allowed:
            return JSONResponse({"detail": "Rate limit exceeded. Try again later."}, status_code=429, headers={"Retry-After": str(retry)})
        job = start(url, body.query, body.deep)
        return {"id": job.id}

    @app.get("/audit/{job_id}/events")
    async def events(job_id: str):
        job = jobs.get(job_id)
        if job is None:
            if store.get(job_id):
                async def replay():
                    yield "data: " + json.dumps({"stage": "report", "message": "Report ready", "report_id": job_id}) + "\n\n"
                return StreamingResponse(replay(), media_type="text/event-stream")
            raise HTTPException(404, "unknown audit")

        async def gen():
            i = 0
            while True:
                async with job.cond:
                    await job.cond.wait_for(lambda: i < len(job.events) or job.done)
                    batch, i = job.events[i:], len(job.events)
                    finished = job.done
                for e in batch:
                    yield "data: " + json.dumps(e) + "\n\n"
                if finished and i >= len(job.events):
                    break
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/audit/{job_id}")
    async def get_audit(job_id: str):
        rep = store.get(job_id)
        if rep:
            return JSONResponse(json.loads(rep.model_dump_json()))
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown audit")
        return JSONResponse({"status": "failed" if job.error else "running", "error": job.error}, status_code=200 if not job.error else 500)

    def need(job_id: str) -> Report:
        rep = store.get(job_id)
        if not rep:
            raise HTTPException(404, "report not found (still running?)")
        return rep

    @app.get("/audit/{job_id}/report.md")
    async def get_md(job_id: str):
        return PlainTextResponse(render_markdown(need(job_id)), media_type="text/markdown")

    @app.get("/audit/{job_id}/fixpack.zip")
    async def get_fixpack(job_id: str):
        rep = need(job_id)
        llm = await llm_suggestions(rep, settings, None, (rep.serp_card or {}).get("meta_description"))
        return Response(build_fixpack(rep, llm), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="citegap-fixpack-{job_id}.zip"'})

    @app.post("/audit/{job_id}/reaudit")
    async def reaudit(job_id: str, request: Request):
        rep = need(job_id)
        allowed, retry = limiter.allow(client_ip(request))
        if not allowed:
            return JSONResponse({"detail": "Rate limit exceeded."}, status_code=429, headers={"Retry-After": str(retry)})
        job = start(rep.url, None if rep.query_derived else rep.query)
        return {"id": job.id}

    @app.get("/audits")
    async def recent():
        return store.recent()

    @app.get("/r/{report_id}")
    async def permalink(report_id: str):
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def app_factory() -> FastAPI:  # uvicorn --factory citegap.api:app_factory
    return create_app()
