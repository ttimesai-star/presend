import asyncio

import pytest

from presend.client import BlockscoutClient, BlockscoutError, explorer_url
from replay import FakeResponse


class Scripted:
    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    def get(self, url, params=None, **kw):
        self.seen.append((url, dict(params or {})))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def mk(answers, **kw):
    s = Scripted(answers)
    return BlockscoutClient(api_key="proapi_secret", chain_id=1, session=s, min_interval=0, **kw), s


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BLOCKSCOUT_API_KEY", raising=False)
    with pytest.raises(BlockscoutError, match="dev.blockscout.com"):
        BlockscoutClient(api_key="")


def test_url_shape_and_credits_header(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c, s = mk([FakeResponse(200, {"hash": "0x1"}, {"x-credits-remaining": "99980"})])
    assert c.address("0xabc") == {"hash": "0x1"}
    url, params = s.seen[0]
    assert url == "https://api.blockscout.com/1/api/v2/addresses/0xabc"
    assert params["apikey"] == "proapi_secret"
    assert c.usage.credits_remaining == 99980 and c.usage.calls == 1


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c, s = mk([FakeResponse(429, {}), FakeResponse(200, {"ok": 1})])
    assert c.get("stats") == {"ok": 1} and len(s.seen) == 2


def test_404_returns_empty_and_401_raises_without_key(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c, _ = mk([FakeResponse(404, {}), FakeResponse(401, "Unauthorized")])
    assert c.address("0xdead") == {}
    with pytest.raises(BlockscoutError) as e:
        c.address("0xdead")
    assert "401" in str(e.value) and "proapi_secret" not in str(e.value)


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    c, _ = mk([FakeResponse(503, {})] * 3, max_retries=2)
    with pytest.raises(BlockscoutError, match="503"):
        c.get("stats")


def test_pagination_follows_next_page_params_and_skips_newer_pages(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    p1 = FakeResponse(200, {"items": [{"block_number": 300}], "next_page_params": {"block_number": 300}})
    p2 = FakeResponse(200, {"items": [{"block_number": 150}], "next_page_params": {"block_number": 150}})
    p3 = FakeResponse(200, {"items": [{"block_number": 90}], "next_page_params": None})
    c, s = mk([p1, p2, p3])
    items = c.transactions("0xabc", max_pages=1, as_of_block=200)
    # page 1 holds only blocks newer than 200, so it does not use up the single page budget
    assert [i["block_number"] for i in items] == [300, 150]
    assert s.seen[1][1]["block_number"] == 300


def test_explorer_links():
    assert explorer_url(1, "tx", "0xab") == "https://eth.blockscout.com/tx/0xab"
    assert explorer_url(999999, "address", "0x1").startswith("https://blockscout.com/chain/999999/")


def test_mcp_tools_are_registered():
    from presend.mcp_server import mcp
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"presend_check", "presend_scan"}
