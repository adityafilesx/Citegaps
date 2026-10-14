import json

from citegap import cli
from citegap.tinyfish.client import TinyFishClient
from fakes import resolver, settings
from scenarios import A_URL, scenario_a


def test_cli_requires_key(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    monkeypatch.setenv("CITEGAP_DB", str(tmp_path / "c.db"))
    monkeypatch.chdir(tmp_path)  # no .env here
    assert cli.main(["audit", A_URL]) == 2
    assert "TINYFISH_API_KEY" in capsys.readouterr().err


def test_cli_rejects_private_url(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("TINYFISH_API_KEY", "k" * 20)
    monkeypatch.setenv("CITEGAP_DB", str(tmp_path / "c.db"))
    assert cli.main(["audit", "http://127.0.0.1/x", "--quiet"]) == 1
    assert "URL rejected" in capsys.readouterr().err
