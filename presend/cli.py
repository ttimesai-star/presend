"""Command line: `presend check` and `presend scan`."""
from __future__ import annotations

import argparse
import json
import sys

from .check import check_payment, scan_wallet
from .client import BlockscoutClient, BlockscoutError, explorer_url

MARK = {"stop": "[STOP]   ", "caution": "[CAUTION]", "info": "[INFO]   "}


def render_report(rep) -> str:
    lines = [f"PreSend verdict: {rep.verdict}",
             f"  chain {rep.chain_id}  from {rep.sender}  to {rep.recipient}"]
    if rep.as_of_block is not None:
        lines.append(f"  replay as of block {rep.as_of_block}"
                     + ("" if rep.labels_used else " (Blockscout scam labels ignored: hindsight)"))
    lines.append("")
    order = {"stop": 0, "caution": 1, "info": 2}
    for f in sorted(rep.findings, key=lambda f: order[f.severity]):
        lines.append(f"{MARK[f.severity]} {f.code}: {f.message}")
        for e in f.evidence:
            lines.append(f"            {e}")
    h = rep.history_checked
    lines += ["", f"Checked {h.get('transactions', 0)} transactions and "
                  f"{h.get('token_transfers', 0)} token transfers of the sender via Blockscout "
                  f"PRO API; {rep.api_calls} API calls"
                  + (f", {rep.credits_remaining} credits left today." if rep.credits_remaining
                     is not None else "."),
              f"Recipient on Blockscout: {explorer_url(rep.chain_id, 'address', rep.recipient)}"]
    return "\n".join(lines)


def render_scan(res: dict) -> str:
    lines = [f"PreSend scan of {res['wallet']} on chain {res['chain_id']}: "
             f"{len(res['attempts'])} poisoning attempt(s) among {res['payees_seen']} real payees"]
    for a in res["attempts"]:
        lines.append(f"  - {a['fake']} imitates {a['imitates']}  ({a['events']} event(s), first "
                     f"{a['first_seen']}{', flagged by Blockscout' if a['flagged_by_blockscout'] else ''}"
                     f"{', YOU PAID IT ' + str(a['paid_by_wallet']) + ' time(s)' if a['paid_by_wallet'] else ''})")
        for e in a["evidence"]:
            lines.append(f"      {e}")
    lines.append(f"{res['api_calls']} API calls; credits left: {res['credits_remaining']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="presend",
                                 description="Pre-payment address check on Blockscout PRO API data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="check a payment before sending")
    c.add_argument("--chain", type=int, default=1)
    c.add_argument("--from", dest="sender", required=True)
    c.add_argument("--to", dest="recipient", required=True)
    c.add_argument("--token", help="token contract you are about to send (optional)")
    c.add_argument("--as-of-block", type=int, help="replay the check as of this block")
    c.add_argument("--no-labels", action="store_true",
                   help="ignore Blockscout scam labels (to test the heuristics alone)")
    c.add_argument("--pages", type=int, default=6, help="history pages of 50 items to read")
    c.add_argument("--json", action="store_true")
    s = sub.add_parser("scan", help="list poisoning attempts against a wallet")
    s.add_argument("--chain", type=int, default=1)
    s.add_argument("--wallet", required=True)
    s.add_argument("--as-of-block", type=int)
    s.add_argument("--pages", type=int, default=6)
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        client = BlockscoutClient(chain_id=a.chain)
        if a.cmd == "check":
            rep = check_payment(client, a.sender, a.recipient, a.token, a.as_of_block,
                                use_labels=not a.no_labels, max_pages=a.pages)
            print(json.dumps(rep.to_dict(), indent=2) if a.json else render_report(rep))
            return {"OK": 0, "CAUTION": 1, "STOP": 2}[rep.verdict]
        res = scan_wallet(client, a.wallet, max_pages=a.pages, as_of_block=a.as_of_block)
        print(json.dumps(res, indent=2) if a.json else render_scan(res))
        return 0
    except BlockscoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
