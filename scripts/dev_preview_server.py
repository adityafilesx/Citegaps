"""TEST TOOLING ONLY: serves the real app against the fake TinyFish/web doubles from tests/ so the UI can be
previewed without an API key. Never used by the product (CLAUDE.md Rule 1)."""
import sys
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

from citegap.api import create_app  # noqa: E402
from citegap.store import Store  # noqa: E402
from citegap.tinyfish.client import TinyFishClient  # noqa: E402
from fakes import resolver, settings  # noqa: E402
from scenarios import scenario_a  # noqa: E402

fake, web = scenario_a()
s = settings(db_path="/tmp/citegap_preview.db", audits_per_minute=50, audits_per_hour=500)
app = create_app(s, client_factory=lambda st: TinyFishClient(st, transport=fake.transport()), raw_transport=web.transport(),
                 resolver=resolver, store=Store(s.db_path))
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8791)
