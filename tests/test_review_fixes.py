"""Regression tests for the external review (Jules, 17 Oct 2026) and our own follow-ups."""
import pytest
import requests

from presend import BlockscoutClient, BlockscoutError, check_payment, scan_wallet
from presend.analysis import interactions, is_real_payment, lookalike_score, token_red_flags
from replay import FakeResponse

W = "0x1111111111111111111111111111111111111111"
REAL = "0xd9a1b0b1e1ae382dbdc898ea68012ffcb2853a91"
FAKE = "0xd9a1c3788d81257612e2581a6ea0ada244853a91"
SPOOFER = "0x517dc8e50b8bf03a1d69c84d27bf96dc5a911db2"


def tx(h, frm, to, value, block):
    return {"hash": h, "from": {"hash": frm}, "to": {"hash": to}, "value": str(value),
            "block_number": block, "timestamp": "2024-05-03T00:00:00Z", "status": "ok"}


def tt(h, frm, to, value, block, symbol="USDC", holders="2000000", rate="1"):
    return {"transaction_hash": h, "from": {"hash": frm}, "to": {"hash": to},
            "total": {"value": str(value)}, "block_number": block, "timestamp": "2024-05-03T00:00:00Z",
            "token": {"symbol": symbol, "holders_count": holders, "exchange_rate": rate,
                      "type": "ERC-20", "reputation": "ok", "decimals": "6"}}


class Fake:
    """Minimal in-memory Blockscout: answers by path, records calls."""

    def __init__(self, sender_is_contract=False, txs=(), transfers=(), tx_senders=None):
        self.data = {f"addresses/{W}": {"hash": W, "is_contract": sender_is_contract},
                     f"addresses/{W}/transactions": {"items": list(txs), "next_page_params": None},
                     f"addresses/{W}/token-transfers": {"items": list(transfers),
                                                        "next_page_params": None}}
        for h, s in (tx_senders or {}).items():
            self.data[f"transactions/{h}"] = {"from": {"hash": s}}
        self.calls = []

    def get(self, url, params=None, **kw):
        path = url.split("/api/v2/", 1)[1]
        self.calls.append(path)
        if path in self.data:
            return FakeResponse(200, self.data[path])
        if path.startswith("addresses/") and path.count("/") == 1:
            return FakeResponse(200, {"hash": path.split("/")[1], "is_contract": False})
        if path.endswith("/counters"):
            return FakeResponse(200, {"transactions_count": "50", "token_transfers_count": "10"})
        return FakeResponse(404, {})


def client(fake):
    return BlockscoutClient(api_key="proapi_SECRET", session=fake, min_interval=0)


def test_lookalike_without_0x_prefix():
    assert lookalike_score(REAL[2:], FAKE[2:]) == (4, 6)
    assert lookalike_score(REAL, FAKE[2:]) == (4, 6)


def test_testnet_tokens_are_not_flagged_for_missing_price():
    sepolia_usdc = {"symbol": "USDC", "holders_count": "40", "exchange_rate": None, "type": "ERC-20",
                    "reputation": "ok"}
    assert token_red_flags(sepolia_usdc, 11155111) == []
    assert token_red_flags(sepolia_usdc, 1)          # same token on mainnet is suspicious


def test_spoof_is_inferred_from_own_tx_list_without_lookups():
    txs = [tx("0xa", W, REAL, 10**16, 100), tx("0xb", W, "0x" + "2" * 40, 1, 200)]
    tts = [tt("0xc", W, FAKE, 0, 150, symbol="ETH", holders="0", rate=None)]
    hist = interactions(W, txs, tts)
    assert [h.signed_by_wallet for h in hist if h.tx_hash == "0xc"] == [False]
    # older than what our tx list covers: unknown, needs a lookup
    hist = interactions(W, txs, [tt("0xd", W, FAKE, 0, 90)])
    assert [h.signed_by_wallet for h in hist if h.tx_hash == "0xd"] == [None]


def test_contract_wallet_gets_no_spoof_claim_and_its_token_payments_count():
    # A Safe / ERC-4337 wallet: its transfers are sent by an owner or a bundler, not by itself.
    tts = [tt("0xe", W, REAL, 5_000_000, 150)]
    hist = interactions(W, [tx("0xa", "0x" + "9" * 40, W, 0, 100)], tts, wallet_is_contract=True)
    item = [h for h in hist if h.tx_hash == "0xe"][0]
    assert item.signed_by_wallet is None
    assert is_real_payment(item, 1, wallet_is_contract=True)
    fake = Fake(sender_is_contract=True, txs=[tx("0xa", "0x" + "9" * 40, W, 0, 100)], transfers=tts)
    rep = check_payment(client(fake), W, REAL)
    assert rep.verdict == "OK"
    assert not [c for c in fake.calls if c.startswith("transactions/")]   # no signer lookups


def test_eoa_spoof_still_detected_end_to_end():
    txs = [tx("0xa", W, REAL, 10**16, 100), tx("0xb", W, "0x" + "2" * 40, 1, 300)]
    tts = [tt("0xc", W, FAKE, 0, 150, symbol="ETH", holders="0", rate=None)]
    rep = check_payment(client(Fake(txs=txs, transfers=tts)), W, FAKE)
    codes = {f.code: f.severity for f in rep.findings}
    assert rep.verdict == "STOP"
    assert codes["SPOOFED_TRANSFER"] == "stop" and codes["LOOKALIKE_OF_PAID"] == "stop"


def test_already_poisoned_payee_stays_stop():
    # The wallet was tricked once already (it paid FAKE), and FAKE also planted a spoofed entry.
    txs = [tx("0xa", W, REAL, 10**16, 100), tx("0xf", W, FAKE, 10**15, 160),
           tx("0xb", W, "0x" + "2" * 40, 1, 300)]
    tts = [tt("0xc", W, FAKE, 0, 150, symbol="ETH", holders="0", rate=None)]
    rep = check_payment(client(Fake(txs=txs, transfers=tts)), W, FAKE)
    codes = {f.code: f.severity for f in rep.findings}
    assert "KNOWN_RECIPIENT" in codes
    assert codes["LOOKALIKE_OF_PAID"] == "stop" and rep.verdict == "STOP"


def test_two_clean_lookalike_payees_is_only_caution():
    txs = [tx("0xa", W, REAL, 10**16, 100), tx("0xf", W, FAKE, 10**16, 160)]
    rep = check_payment(client(Fake(txs=txs)), W, FAKE)
    codes = {f.code: f.severity for f in rep.findings}
    assert codes["LOOKALIKE_OF_PAID"] == "caution" and rep.verdict == "CAUTION"


def test_scan_reports_spoofed_lookalike():
    txs = [tx("0xa", W, REAL, 10**16, 100), tx("0xb", W, "0x" + "2" * 40, 1, 300)]
    tts = [tt("0xc", W, FAKE, 1, 150)]   # legit-looking token, but not signed by the wallet
    res = scan_wallet(client(Fake(txs=txs, transfers=tts)), W)
    assert [a["fake"] for a in res["attempts"]] == [FAKE]


def test_invalid_addresses_are_rejected_before_any_call():
    fake = Fake()
    with pytest.raises(ValueError, match="recipient"):
        check_payment(client(fake), W, "0x123")
    with pytest.raises(ValueError, match="token"):
        check_payment(client(fake), W, REAL, token="../../stats")
    with pytest.raises(ValueError, match="wallet"):
        scan_wallet(client(fake), "nope")
    assert fake.calls == []


def test_api_key_is_redacted_from_network_errors(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    class Boom:
        def get(self, url, params=None, **kw):
            raise requests.ConnectionError(f"failed: {url}?apikey={params['apikey']}")
    c = BlockscoutClient(api_key="proapi_SECRET", session=Boom(), min_interval=0, max_retries=1)
    with pytest.raises(BlockscoutError) as e:
        c.address(W)
    assert "proapi_SECRET" not in str(e.value) and "***" in str(e.value)
    assert e.value.__cause__ is None


def test_next_page_params_override_instead_of_colliding(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    class Pager:
        def __init__(self):
            self.n = 0
            self.params = []

        def get(self, url, params=None, **kw):
            self.params.append(dict(params))
            self.n += 1
            if self.n == 1:
                return FakeResponse(200, {"items": [{"block_number": 5}],
                                          "next_page_params": {"filter": "to", "index": 7}})
            return FakeResponse(200, {"items": [], "next_page_params": None})
    p = Pager()
    c = BlockscoutClient(api_key="k", session=p, min_interval=0)
    items = list(c.pages("addresses/x/token-transfers", max_pages=3, filter="from"))
    assert items == [{"block_number": 5}] and p.params[1]["filter"] == "to"


def test_zero_exchange_rate_counts_as_no_price():
    fake = {"symbol": "USDT", "holders_count": "2", "exchange_rate": "0", "type": "ERC-20",
            "reputation": "ok"}
    assert any("no market price" in f for f in token_red_flags(fake, 1))


def test_retry_after_header_is_honoured(monkeypatch):
    slept = []
    monkeypatch.setattr("time.sleep", lambda s: slept.append(s))

    class S:
        def __init__(self):
            self.a = [FakeResponse(429, {}, {"Retry-After": "3"}), FakeResponse(200, {"ok": 1})]

        def get(self, url, params=None, **kw):
            return self.a.pop(0)
    c = BlockscoutClient(api_key="k", session=S(), min_interval=0)
    assert c.get("stats") == {"ok": 1} and 3.0 in slept
