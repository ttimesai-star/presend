"""PreSend: decide whether a payment from `sender` to `recipient` is safe, using Blockscout data."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .analysis import (Interaction, address_flagged, interactions, is_junk, is_lookalike,
                       is_real_payment, lookalike_score, norm, token_red_flags)
from .client import BlockscoutClient, explorer_url

STOP, CAUTION, INFO = "stop", "caution", "info"
MAX_TX_LOOKUPS = 8


@dataclass
class Finding:
    code: str
    severity: str
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Report:
    chain_id: int
    sender: str
    recipient: str
    verdict: str                      # "STOP" | "CAUTION" | "OK"
    findings: list[Finding]
    as_of_block: int | None = None
    labels_used: bool = True
    history_checked: dict = field(default_factory=dict)
    api_calls: int = 0
    credits_remaining: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def verdict_of(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    return "STOP" if STOP in sev else "CAUTION" if CAUTION in sev else "OK"


def _confirm_signers(client: BlockscoutClient, wallet: str, items: list[Interaction],
                     budget: list[int]) -> None:
    """For outgoing token transfers with unknown signer, fetch the tx and compare tx.from."""
    w = norm(wallet)
    for it in items:
        if it.direction != "out" or it.signed_by_wallet is not None or budget[0] <= 0:
            continue
        budget[0] -= 1
        tx = client.transaction(it.tx_hash)
        sender = norm((tx.get("from") or {}).get("hash"))
        it.signed_by_wallet = (sender == w) if sender else None


def _fmt_amount(it: Interaction) -> str:
    if it.kind == "native":
        return f"{it.value / 1e18:.6g} native"
    tok = it.token or {}
    dec = int(tok.get("decimals") or 0)
    return f"{it.value / (10 ** dec) if dec else it.value:.6g} {tok.get('symbol') or '?'}"


def check_payment(client: BlockscoutClient, sender: str, recipient: str,
                  token: str | None = None, as_of_block: int | None = None,
                  use_labels: bool = True, max_pages: int = 6) -> Report:
    chain = client.chain_id
    s, r = norm(sender), norm(recipient)
    findings: list[Finding] = []
    link = lambda kind, v: explorer_url(chain, kind, v)  # noqa: E731

    if s == r:
        findings.append(Finding("SELF_TRANSFER", CAUTION, "Recipient is the sender itself."))

    # 1. Recipient as Blockscout sees it.
    rmeta = client.address(recipient) or {}
    if not rmeta:
        findings.append(Finding("UNKNOWN_ADDRESS", CAUTION,
                                "Blockscout has no record of the recipient on this chain "
                                "(never used here).", [link("address", recipient)]))
    if use_labels:
        for why in address_flagged(rmeta):
            findings.append(Finding("RECIPIENT_FLAGGED", STOP, why, [link("address", recipient)]))
    if rmeta.get("is_contract") and not rmeta.get("is_verified"):
        findings.append(Finding("UNVERIFIED_CONTRACT", CAUTION,
                                "Recipient is a contract without verified source code.",
                                [link("address", recipient)]))

    # 2. The sender's own history, as of the given block.
    txs = client.transactions(sender, max_pages, as_of_block)
    transfers = client.token_transfers(sender, max_pages, as_of_block)
    hist = interactions(sender, txs, transfers, as_of_block)

    with_r = [it for it in hist if it.counterparty == r]
    look = {}
    for it in hist:
        if it.counterparty != r and is_lookalike(it.counterparty, r):
            look.setdefault(it.counterparty, []).append(it)

    budget = [MAX_TX_LOOKUPS]
    _confirm_signers(client, sender, with_r, budget)
    for items in look.values():
        _confirm_signers(client, sender, items, budget)

    paid_r = [it for it in with_r if is_real_payment(it, chain)]
    spoofed = [it for it in with_r if it.direction == "out" and it.signed_by_wallet is False]
    junk_r = [it for it in with_r if is_junk(it, chain)]

    if paid_r:
        last = max(paid_r, key=lambda i: i.block)
        findings.append(Finding("KNOWN_RECIPIENT", INFO,
                                f"You paid this address {len(paid_r)} time(s) before; last: "
                                f"{_fmt_amount(last)} on {last.timestamp[:10]}.",
                                [link("tx", last.tx_hash)]))
    else:
        findings.append(Finding("NEW_RECIPIENT", CAUTION,
                                "You have never sent anything of value to this address."))

    if spoofed:
        ev = [link("tx", it.tx_hash) for it in spoofed[:3]]
        findings.append(Finding("SPOOFED_TRANSFER", STOP,
                                f"{len(spoofed)} transfer(s) 'from your wallet' to this address were "
                                "not signed by you. This is how address poisoning plants a fake entry "
                                "in your history.", ev))
    if with_r and not paid_r and len(junk_r) == len(with_r):
        ev = [link("tx", it.tx_hash) for it in junk_r[:3]]
        findings.append(Finding("ONLY_JUNK_HISTORY", CAUTION,
                                "Your only history with this address is zero-value or fake-token "
                                "transfers.", ev))

    for addr, items in sorted(look.items(), key=lambda kv: -sum(lookalike_score(kv[0], r))):
        paid = [it for it in items if is_real_payment(it, chain)]
        if not paid:
            continue
        p, sfx = lookalike_score(addr, r)
        last = max(paid, key=lambda i: i.block)
        sev = STOP if not paid_r else CAUTION
        findings.append(Finding(
            "LOOKALIKE_OF_PAID", sev,
            f"Recipient imitates {addr} (same first {p} and last {sfx} hex characters). You paid "
            f"that address {len(paid)} time(s), last {_fmt_amount(last)} on {last.timestamp[:10]}. "
            f"Check every character before sending.",
            [link("address", addr), link("tx", last.tx_hash)]))

    # 3. Recipient freshness (current counters, so skipped in a historical replay).
    if rmeta and not rmeta.get("is_contract") and as_of_block is None:
        cnt = client.counters(recipient) or {}
        n = int(cnt.get("transactions_count") or 0) + int(cnt.get("token_transfers_count") or 0)
        if n and n < 5 and not paid_r:
            findings.append(Finding("FRESH_ADDRESS", CAUTION,
                                    f"Recipient has very little activity ({n} transactions and "
                                    f"token transfers in total).", [link("address", recipient)]))

    # 4. Token being sent.
    if token:
        tmeta = client.token(token) or {}
        for why in token_red_flags(tmeta, chain, ignore_labels=not use_labels):
            findings.append(Finding("TOKEN_SUSPICIOUS", CAUTION, why, [link("token", token)]))

    rep = Report(chain, sender, recipient, verdict_of(findings), findings, as_of_block, use_labels)
    rep.history_checked = {"transactions": len(txs), "token_transfers": len(transfers),
                           "interactions_used": len(hist)}
    rep.api_calls = client.usage.calls
    rep.credits_remaining = client.usage.credits_remaining
    return rep


@dataclass
class PoisonAttempt:
    fake: str
    imitates: str
    events: int
    first_seen: str
    flagged_by_blockscout: bool
    paid_by_wallet: int
    evidence: list[str]


def scan_wallet(client: BlockscoutClient, wallet: str, max_pages: int = 6,
                as_of_block: int | None = None) -> dict:
    """List addresses that tried to poison this wallet's history (look-alikes of real payees).

    A candidate is a counterparty that reached the wallet through junk (zero-value or fake-token)
    transfers or through 'outgoing' token transfers the wallet may not have signed, and that
    looks like an address the wallet really paid. `paid_by_wallet` > 0 means the wallet later
    sent real value to the fake address: the poisoning worked.
    """
    chain = client.chain_id
    txs = client.transactions(wallet, max_pages, as_of_block)
    transfers = client.token_transfers(wallet, max_pages, as_of_block)
    hist = interactions(wallet, txs, transfers, as_of_block)
    by_cp: dict[str, list[Interaction]] = {}
    for it in hist:
        by_cp.setdefault(it.counterparty, []).append(it)
    payees = {cp: [i for i in items if is_real_payment(i, chain)] for cp, items in by_cp.items()}
    payees = {cp: v for cp, v in payees.items() if v}
    attempts = []
    for cp, items in by_cp.items():
        suspicious = [i for i in items if is_junk(i, chain)
                      or (i.direction == "out" and i.kind == "token" and i.signed_by_wallet is None)]
        if not suspicious:
            continue
        target = next((p for p in payees if p != cp and is_lookalike(cp, p)), None)
        if not target:
            continue
        meta = items[0].counterparty_meta or {}
        first = min(suspicious, key=lambda i: i.block)
        attempts.append(PoisonAttempt(cp, target, len(suspicious), first.timestamp[:19],
                                      bool(address_flagged(meta)), len(payees.get(cp, [])),
                                      [explorer_url(chain, "tx", i.tx_hash) for i in suspicious[:3]]))
    attempts.sort(key=lambda a: a.first_seen)
    return {"chain_id": chain, "wallet": wallet, "as_of_block": as_of_block,
            "payees_seen": len(payees), "attempts": [asdict(a) for a in attempts],
            "history_checked": {"transactions": len(txs), "token_transfers": len(transfers)},
            "api_calls": client.usage.calls, "credits_remaining": client.usage.credits_remaining}
