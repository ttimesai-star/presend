import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import presend.web as web
from presend.client import BlockscoutClient
from replay import ReplaySession

VICTIM = "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5"
FAKE = "0xd9A1C3788D81257612E2581A6ea0aDa244853a91"


@pytest.fixture
def base(monkeypatch):
    sess = ReplaySession("may2024_wbtc.json.gz")
    real_init = BlockscoutClient.__init__

    def init(self, *a, **kw):
        kw.update(api_key="test", session=sess, min_interval=0)
        real_init(self, *a, **kw)
    monkeypatch.setattr(web.BlockscoutClient, "__init__", init)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_page_served(base):
    code, body = get(base + "/")
    assert code == 200 and "PreSend" in body and "Blockscout PRO API" in body


def test_api_check_replay(base):
    code, body = get(f"{base}/api/check?chain=1&sender={VICTIM}&recipient={FAKE}"
                     "&as_of_block=19789008&no_labels=on")
    d = json.loads(body)
    assert code == 200 and d["verdict"] == "STOP"
    assert {"SPOOFED_TRANSFER", "LOOKALIKE_OF_PAID"} <= {f["code"] for f in d["findings"]}


def test_api_rejects_bad_input(base):
    code, body = get(f"{base}/api/check?sender=0x123&recipient={FAKE}")
    assert code == 400 and "sender" in json.loads(body)["error"]
    code, _ = get(f"{base}/api/check?sender={VICTIM}&recipient=<script>")
    assert code == 400
    assert get(base + "/nope")[0] == 404
