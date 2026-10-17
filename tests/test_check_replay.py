"""End-to-end on recorded Blockscout answers: the 3 May 2024 1,155 WBTC address-poisoning theft."""
import json

import pytest

from presend import BlockscoutClient, check_payment, scan_wallet
from presend.cli import main as cli_main
from replay import ReplaySession

VICTIM = "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5"
FAKE = "0xd9A1C3788D81257612E2581A6ea0aDa244853a91"
REAL = "0xd9A1b0B1e1aE382DbDc898Ea68012FfcB2853a91"
BLOCK = 19789008


@pytest.fixture
def client():
    return BlockscoutClient(api_key="test", chain_id=1, session=ReplaySession("may2024_wbtc.json.gz"),
                            min_interval=0)


def codes(rep):
    return {f.code: f for f in rep.findings}


def test_replay_one_block_before_theft_says_stop_without_labels(client):
    rep = check_payment(client, VICTIM, FAKE, as_of_block=BLOCK, use_labels=False, max_pages=3)
    c = codes(rep)
    assert rep.verdict == "STOP"
    assert "RECIPIENT_FLAGGED" not in c                       # hindsight labels were off
    assert c["SPOOFED_TRANSFER"].severity == "stop"
    assert "0x9147d74ef5749b7f27eb2e2528e5a611060b3f609b435f7f50ac87f49e5b957c" in \
        " ".join(c["SPOOFED_TRANSFER"].evidence)
    look = c["LOOKALIKE_OF_PAID"]
    assert look.severity == "stop" and REAL.lower() in look.message
    assert "first 4 and last 6" in look.message
    assert "NEW_RECIPIENT" in c


def test_replay_real_address_is_ok(client):
    rep = check_payment(client, VICTIM, REAL, as_of_block=BLOCK, use_labels=False, max_pages=3)
    assert rep.verdict == "OK"
    assert set(codes(rep)) == {"KNOWN_RECIPIENT"}


def test_today_blockscout_labels_flag_the_attacker(client):
    rep = check_payment(client, VICTIM, FAKE, max_pages=2)
    c = codes(rep)
    assert rep.verdict == "STOP"
    assert c["RECIPIENT_FLAGGED"].severity == "stop"


def test_scan_finds_the_poisoner_and_the_loss(client):
    res = scan_wallet(client, VICTIM, max_pages=14)
    by_fake = {a["fake"]: a for a in res["attempts"]}
    hit = by_fake[FAKE.lower()]
    assert hit["imitates"] == REAL.lower()
    assert hit["paid_by_wallet"] >= 1 and hit["flagged_by_blockscout"]
    assert hit["first_seen"].startswith("2024-05-03T09:17")
    json.dumps(res)  # serialisable for the MCP tool


def test_report_is_json_serialisable(client):
    rep = check_payment(client, VICTIM, FAKE, as_of_block=BLOCK, use_labels=False, max_pages=3)
    d = json.loads(json.dumps(rep.to_dict()))
    assert d["verdict"] == "STOP" and d["as_of_block"] == BLOCK and d["labels_used"] is False


def test_cli_exit_codes(monkeypatch, capsys):
    sess = ReplaySession("may2024_wbtc.json.gz")
    import presend.cli as cli
    real_init = BlockscoutClient.__init__

    def init(self, *a, **kw):
        kw.update(api_key="test", session=sess, min_interval=0)
        real_init(self, *a, **kw)
    monkeypatch.setattr(cli.BlockscoutClient, "__init__", init)
    rc = cli_main(["check", "--from", VICTIM, "--to", FAKE, "--as-of-block", str(BLOCK),
                   "--no-labels", "--pages", "3"])
    out = capsys.readouterr().out
    assert rc == 2 and "PreSend verdict: STOP" in out and "LOOKALIKE_OF_PAID" in out
    rc = cli_main(["check", "--from", VICTIM, "--to", REAL, "--as-of-block", str(BLOCK),
                   "--no-labels", "--pages", "3", "--json"])
    assert rc == 0 and json.loads(capsys.readouterr().out)["verdict"] == "OK"
