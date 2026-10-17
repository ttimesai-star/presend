"""Record / replay Blockscout API answers so tests run offline and without a key."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from urllib.parse import urlparse

import requests

FIXTURES = Path(__file__).parent / "fixtures"


def _key(url: str, params: dict) -> str:
    path = urlparse(url).path
    q = "&".join(f"{k}={params[k]}" for k in sorted(params) if k != "apikey")
    return f"{path}?{q}"


class FakeResponse:
    def __init__(self, status: int, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body) if not isinstance(body, str) else body

    def json(self):
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class RecordingSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.store: dict[str, dict] = {}

    def get(self, url, params=None, **kw):
        r = super().get(url, params=params, **kw)
        if r.status_code in (200, 404):
            self.store[_key(url, params or {})] = {"status": r.status_code,
                                                   "body": r.json() if r.status_code == 200 else {}}
        return r

    def save(self, name: str) -> Path:
        FIXTURES.mkdir(exist_ok=True)
        p = FIXTURES / name
        with gzip.open(p, "wt", encoding="utf-8") as f:
            json.dump(self.store, f, separators=(",", ":"))
        return p


class ReplaySession:
    def __init__(self, name: str):
        with gzip.open(FIXTURES / name, "rt", encoding="utf-8") as f:
            self.store = json.load(f)
        self.calls = []

    def get(self, url, params=None, **kw):
        k = _key(url, params or {})
        self.calls.append(k)
        if k not in self.store:
            raise AssertionError(f"no recorded answer for {k}")
        rec = self.store[k]
        return FakeResponse(rec["status"], rec["body"], {"x-credits-remaining": "100000"})
