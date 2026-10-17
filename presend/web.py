"""Small local web page: `python -m presend.web` then open http://127.0.0.1:8765

The API key stays on the server; the page calls /api/check and /api/scan.
"""
from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .check import check_payment, scan_wallet
from .client import BlockscoutClient, BlockscoutError

ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PreSend</title>
<style>
:root{--bg:#0f1720;--card:#16212d;--fg:#e6edf3;--mut:#8b9bab;--stop:#e5484d;--cau:#f5a524;--ok:#30a46c;--line:#24313f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px}h1{margin:0 0 4px;font-size:26px}p.sub{color:var(--mut);margin:0 0 20px}
form{display:grid;gap:10px;background:var(--card);padding:16px;border-radius:10px;border:1px solid var(--line)}
label{font-size:13px;color:var(--mut)}input,select{width:100%;padding:9px 10px;border-radius:7px;border:1px solid var(--line);background:#0b1118;color:var(--fg);font:14px ui-monospace,Consolas,monospace}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.chk{display:flex;gap:8px;align-items:center;font-size:13px;color:var(--mut)}.chk input{width:auto}
button{padding:10px 14px;border:0;border-radius:7px;background:#3e63dd;color:#fff;font-weight:600;cursor:pointer}button.alt{background:#2b3a4a}
#out{margin-top:18px}.verdict{font-size:30px;font-weight:800;padding:14px 16px;border-radius:10px;margin-bottom:12px}
.STOP{background:color-mix(in srgb,var(--stop) 22%,transparent);color:var(--stop)}.CAUTION{background:color-mix(in srgb,var(--cau) 22%,transparent);color:var(--cau)}.OK{background:color-mix(in srgb,var(--ok) 22%,transparent);color:var(--ok)}
.f{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--mut);border-radius:8px;padding:10px 12px;margin:8px 0}
.f.stop{border-left-color:var(--stop)}.f.caution{border-left-color:var(--cau)}.f.info{border-left-color:var(--ok)}
.code{font:12px ui-monospace,Consolas,monospace;color:var(--mut)}a{color:#7cb4ff;word-break:break-all}.meta{color:var(--mut);font-size:13px;margin-top:10px}
.demo{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}
</style></head><body><main>
<h1>PreSend</h1><p class="sub">Check a recipient against your own on-chain history before you pay. Data: Blockscout PRO API.</p>
<form id="f"><div class="row"><div><label>Chain</label><select name="chain">
<option value="1">Ethereum (1)</option><option value="10">Optimism (10)</option><option value="42161">Arbitrum One (42161)</option>
<option value="100">Gnosis (100)</option><option value="59144">Linea (59144)</option><option value="534352">Scroll (534352)</option>
<option value="11155111">Sepolia (11155111)</option></select></div>
<div><label>Replay as of block (optional)</label><input name="as_of_block" placeholder="e.g. 19789008"></div></div>
<div><label>Your wallet (sender)</label><input name="sender" required placeholder="0x..."></div>
<div><label>Recipient you are about to pay</label><input name="recipient" placeholder="0x... (leave empty to scan your wallet)"></div>
<div class="chk"><input type="checkbox" name="no_labels" id="nl"><label for="nl">Ignore Blockscout scam labels (test the heuristics alone)</label></div>
<div style="display:flex;gap:8px"><button type="submit">Check payment</button><button class="alt" type="button" id="scan">Scan wallet for poisoning</button></div>
<div class="demo"><button class="alt" type="button" data-demo="fake">Demo: 3 May 2024, fake address</button><button class="alt" type="button" data-demo="real">Demo: same moment, real address</button></div>
</form><div id="out"></div></main>
<script>
const V="0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5",F="0xd9A1C3788D81257612E2581A6ea0aDa244853a91",R="0xd9A1b0B1e1aE382DbDc898Ea68012FfcB2853a91";
const f=document.getElementById('f'),out=document.getElementById('out');
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const links=e=>e.map(u=>`<div><a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a></div>`).join('');
async function run(kind){const d=new FormData(f);const q=new URLSearchParams();for(const[k,v]of d)if(v)q.set(k,v);
out.innerHTML='<p class="meta">Reading history from Blockscout PRO API…</p>';
try{const r=await fetch('/api/'+kind+'?'+q);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);
if(kind==='check'){const ord={stop:0,caution:1,info:2};out.innerHTML=`<div class="verdict ${j.verdict}">${j.verdict}</div>`+
j.findings.sort((a,b)=>ord[a.severity]-ord[b.severity]).map(x=>`<div class="f ${x.severity}"><div class="code">${x.severity.toUpperCase()} · ${esc(x.code)}</div><div>${esc(x.message)}</div>${links(x.evidence)}</div>`).join('')+
`<div class="meta">${j.history_checked.transactions} transactions and ${j.history_checked.token_transfers} token transfers read · ${j.api_calls} API calls${j.as_of_block?` · replay as of block ${j.as_of_block}`:''}${j.labels_used?'':' · Blockscout labels ignored'}</div>`}
else{out.innerHTML=`<div class="verdict ${j.attempts.length?'CAUTION':'OK'}">${j.attempts.length} poisoning attempt(s)</div>`+
j.attempts.map(a=>`<div class="f ${a.paid_by_wallet?'stop':'caution'}"><div class="code">FAKE ${esc(a.fake)}</div><div>imitates ${esc(a.imitates)} · ${a.events} event(s) · first ${esc(a.first_seen)}${a.flagged_by_blockscout?' · flagged by Blockscout':''}${a.paid_by_wallet?` · <b>you paid it ${a.paid_by_wallet} time(s)</b>`:''}</div>${links(a.evidence)}</div>`).join('')+
`<div class="meta">${j.payees_seen} real payees found · ${j.api_calls} API calls</div>`}}
catch(e){out.innerHTML=`<div class="f stop">${esc(e.message)}</div>`}}
f.addEventListener('submit',e=>{e.preventDefault();run('check')});
document.getElementById('scan').onclick=()=>run('scan');
document.querySelectorAll('[data-demo]').forEach(b=>b.onclick=()=>{f.chain.value='1';f.sender.value=V;f.as_of_block.value='19789008';f.no_labels.checked=true;
f.recipient.value=b.dataset.demo==='fake'?F:R;run('check')});
</script></body></html>"""


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if u.path not in ("/api/check", "/api/scan"):
            return self._json(404, {"error": "not found"})
        chain = _int(q.get("chain"), 1)
        sender = q.get("sender", "")
        if not ADDR.match(sender):
            return self._json(400, {"error": "sender must be a 0x address of 40 hex characters"})
        as_of = _int(q.get("as_of_block"))
        try:
            client = BlockscoutClient(chain_id=chain)
            if u.path == "/api/scan":
                return self._json(200, scan_wallet(
                    client, sender, max_pages=max(1, min(_int(q.get("pages"), 14), 20)),
                    as_of_block=as_of))
            rcpt = q.get("recipient", "")
            if not ADDR.match(rcpt):
                return self._json(400, {"error": "recipient must be a 0x address of 40 hex characters"})
            rep = check_payment(client, sender, rcpt, q.get("token") or None, as_of,
                                use_labels=not q.get("no_labels"))
            return self._json(200, rep.to_dict())
        except BlockscoutError as e:
            return self._json(502, {"error": str(e)})


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"PreSend on http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
