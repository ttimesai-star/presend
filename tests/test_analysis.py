from presend.analysis import (address_flagged, interactions, is_junk, is_lookalike,
                              is_real_payment, lookalike_score, symbol_skeleton, token_red_flags)

REAL = "0xd9A1b0B1e1aE382DbDc898Ea68012FfcB2853a91"
FAKE = "0xd9A1C3788D81257612E2581A6ea0aDa244853a91"
W = "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5"


def test_lookalike_score_real_case():
    assert lookalike_score(REAL, FAKE) == (4, 6)
    assert is_lookalike(REAL, FAKE)


def test_lookalike_is_case_insensitive_and_not_self():
    assert lookalike_score(REAL, REAL.lower()) == (0, 0)
    assert not is_lookalike(REAL, REAL.upper().replace("0X", "0x"))


def test_unrelated_addresses_do_not_match():
    assert not is_lookalike(REAL, "0x0000000000000000000000000000000000000001")
    # prefix only (6 chars) is not enough: needs both ends
    assert not is_lookalike("0xabcdef0000000000000000000000000000000001",
                            "0xabcdef1111111111111111111111111111111112")
    # 3 + 3 is below the threshold of 7
    assert not is_lookalike("0xabc0000000000000000000000000000000000def",
                            "0xabc1111111111111111111111111111111111def")


def test_symbol_skeleton_maps_cyrillic():
    assert symbol_skeleton("WВТC") == "WBTC"   # Cyrillic В and Т
    assert symbol_skeleton("USDС") == "USDC"   # Cyrillic С


def test_token_red_flags():
    real_wbtc = {"symbol": "WBTC", "reputation": "ok", "holders_count": "202951",
                 "exchange_rate": "81276", "type": "ERC-20"}
    assert token_red_flags(real_wbtc, 1) == []
    fake = {"symbol": "WВТC", "reputation": "ok", "holders_count": "3", "exchange_rate": None,
            "type": "ERC-20"}
    flags = token_red_flags(fake, 1)
    assert any("imitates WBTC" in f for f in flags)
    assert any("no market price" in f for f in flags)
    fake_eth = {"symbol": "ETH", "reputation": "ok", "holders_count": "0", "type": "ERC-20"}
    assert any("native coin" in f for f in token_red_flags(fake_eth, 1))
    scam = {"symbol": "XYZ", "reputation": "scam", "type": "ERC-20"}
    assert token_red_flags(scam, 1) and token_red_flags(scam, 1, ignore_labels=True) == []


def test_address_flagged_reads_labels_and_notes():
    meta = {"is_scam": True, "reputation": "scam", "metadata": {"tags": [
        {"name": "Phish / Hack", "tagType": "generic"},
        {"name": "note_0", "tagType": "note", "meta": {"data": "Reported by Cyvers Alerts."}}]}}
    r = address_flagged(meta)
    assert "Blockscout marks this address as scam" in r
    assert any("Phish / Hack" in x for x in r) and any("Cyvers" in x for x in r)
    assert address_flagged({"reputation": "ok"}) == []
    assert address_flagged(None) == []


def _tx(h, frm, to, value, block, status="ok"):
    return {"hash": h, "from": {"hash": frm}, "to": {"hash": to}, "value": str(value),
            "block_number": block, "timestamp": "2024-05-03T00:00:00Z", "status": status}


def _tt(h, frm, to, value, block, symbol="WBTC", holders="200000", rate="80000"):
    return {"transaction_hash": h, "from": {"hash": frm}, "to": {"hash": to},
            "total": {"value": str(value)}, "block_number": block,
            "timestamp": "2024-05-03T00:00:00Z",
            "token": {"symbol": symbol, "holders_count": holders, "exchange_rate": rate,
                      "type": "ERC-20", "reputation": "ok", "decimals": "8"}}


def test_interactions_signed_and_as_of():
    txs = [_tx("0xa", W, REAL, 10**16, 100), _tx("0xb", W, REAL, 5, 300),
           _tx("0xc", W, REAL, 5, 50, status="error")]
    tts = [_tt("0xa", W, REAL, 1, 100), _tt("0xd", W, FAKE, 0, 150, symbol="ETH", holders="0",
                                              rate=None)]
    hist = interactions(W, txs, tts, as_of_block=200)
    assert {h.tx_hash for h in hist} == {"0xa", "0xd"}        # block 300 and failed tx dropped
    native = [h for h in hist if h.kind == "native"][0]
    assert native.signed_by_wallet is True and is_real_payment(native, 1)
    tok_signed = [h for h in hist if h.kind == "token" and h.tx_hash == "0xa"][0]
    assert tok_signed.signed_by_wallet is True               # its tx hash is one of ours
    spoof = [h for h in hist if h.tx_hash == "0xd"][0]
    # block 150 is inside the range our own tx list covers (from block 50), and 0xd is not ours
    assert spoof.signed_by_wallet is False and is_junk(spoof, 1)
    assert not is_real_payment(spoof, 1)


def test_zero_value_is_junk_and_not_payment():
    hist = interactions(W, [_tx("0xe", W, REAL, 0, 10)], [], None)
    assert is_junk(hist[0], 1) and not is_real_payment(hist[0], 1)
