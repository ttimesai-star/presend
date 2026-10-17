"""Pure functions over Blockscout API items. No network here, so all of it is unit-tested."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

NATIVE_SYMBOL = {1: "ETH", 10: "ETH", 42161: "ETH", 8453: "ETH", 59144: "ETH", 534352: "ETH",
                 11155111: "ETH", 100: "XDAI", 137: "POL", 56: "BNB"}
MAJOR_SYMBOLS = {"USDT", "USDC", "DAI", "WETH", "WBTC", "ETH", "USDE", "PYUSD", "EURC", "LINK"}

# Latin look-alikes used in fake token symbols (Cyrillic and Greek capitals and lower case).
CONFUSABLES = str.maketrans({
    "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "І": "I", "Ј": "J", "К": "K", "М": "M",
    "О": "O", "Р": "P", "Ѕ": "S", "Т": "T", "Х": "X", "У": "Y", "а": "a", "с": "c", "е": "e",
    "о": "o", "р": "p", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "Ζ": "Z", "ο": "o", "ν": "v",
})


def norm(addr: str | None) -> str:
    return (addr or "").lower()


def lookalike_score(a: str, b: str) -> tuple[int, int]:
    """Common prefix and suffix length of two addresses (hex part, case-insensitive)."""
    x, y = norm(a)[2:], norm(b)[2:]
    if not x or not y or x == y:
        return (0, 0)
    p = 0
    while p < min(len(x), len(y)) and x[p] == y[p]:
        p += 1
    s = 0
    while s < min(len(x), len(y)) - p and x[-1 - s] == y[-1 - s]:
        s += 1
    return (p, s)


def is_lookalike(a: str, b: str) -> bool:
    """Vanity-address match the way wallets truncate (0x1234...abcd).

    A random pair matches 7+ hex chars at the ends with probability ~16**-7 (about 4e-9),
    so a hit against a wallet's own counterparties is a strong signal of poisoning.
    """
    p, s = lookalike_score(a, b)
    return p + s >= 7 and min(p, s) >= 3


def symbol_skeleton(symbol: str) -> str:
    """Map confusable characters to Latin and drop the rest of non-ASCII."""
    t = unicodedata.normalize("NFKC", symbol or "").translate(CONFUSABLES)
    return "".join(ch for ch in t if ord(ch) < 128).upper()


def token_red_flags(token: dict | None, chain_id: int, ignore_labels: bool = False) -> list[str]:
    """Reasons a token looks fake. Empty list means nothing suspicious was seen."""
    if not token:
        return []
    flags = []
    sym = token.get("symbol") or ""
    if not ignore_labels and (token.get("reputation") not in (None, "ok") or token.get("is_scam")):
        flags.append(f"Blockscout reputation of token is '{token.get('reputation')}'")
    if sym and any(ord(ch) > 127 for ch in sym):
        skel = symbol_skeleton(sym)
        if skel in MAJOR_SYMBOLS:
            flags.append(f"symbol '{sym}' imitates {skel} with look-alike letters")
        else:
            flags.append(f"symbol '{sym}' has non-ASCII characters")
    native = NATIVE_SYMBOL.get(chain_id)
    if native and sym.upper() == native and (token.get("type") or "").startswith("ERC"):
        flags.append(f"ERC-20 token named like the native coin {native}")
    holders = _int(token.get("holders_count"))
    if symbol_skeleton(sym) in MAJOR_SYMBOLS and token.get("exchange_rate") in (None, "") \
            and holders is not None and holders < 1000:
        flags.append(f"uses the symbol of a major asset but has {holders} holders and no market price")
    return flags


@dataclass
class Interaction:
    counterparty: str          # lower-case address
    direction: str             # "out" (from wallet) or "in"
    kind: str                  # "native" or "token"
    value: int
    tx_hash: str
    block: int
    timestamp: str
    token: dict | None = None
    signed_by_wallet: bool | None = None   # None = unknown yet
    counterparty_meta: dict = field(default_factory=dict)

    @property
    def is_zero(self) -> bool:
        return self.value == 0


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def interactions(wallet: str, txs: list[dict], transfers: list[dict],
                 as_of_block: int | None = None) -> list[Interaction]:
    """Turn transactions + token transfers into one list, as seen at `as_of_block`."""
    w = norm(wallet)
    out: list[Interaction] = []
    signed = set()
    for t in txs:
        blk = _int(t.get("block_number", t.get("block")))
        if as_of_block is not None and (blk is None or blk > as_of_block):
            continue
        if t.get("status") not in (None, "ok"):
            continue
        frm, to = norm((t.get("from") or {}).get("hash")), norm((t.get("to") or {}).get("hash"))
        if frm == w:
            signed.add(norm(t.get("hash")))
        value = _int(t.get("value")) or 0
        if not to:
            continue
        if frm == w and to != w:
            out.append(Interaction(to, "out", "native", value, norm(t.get("hash")), blk or 0,
                                   t.get("timestamp") or "", None, True, t.get("to") or {}))
        elif to == w and frm != w:
            out.append(Interaction(frm, "in", "native", value, norm(t.get("hash")), blk or 0,
                                   t.get("timestamp") or "", None, False, t.get("from") or {}))
    for t in transfers:
        blk = _int(t.get("block_number", t.get("block")))
        if as_of_block is not None and (blk is None or blk > as_of_block):
            continue
        frm, to = norm((t.get("from") or {}).get("hash")), norm((t.get("to") or {}).get("hash"))
        value = _int((t.get("total") or {}).get("value")) or 0
        h = norm(t.get("transaction_hash"))
        if frm == w and to != w:
            out.append(Interaction(to, "out", "token", value, h, blk or 0, t.get("timestamp") or "",
                                   t.get("token") or {}, True if h in signed else None,
                                   t.get("to") or {}))
        elif to == w and frm != w:
            out.append(Interaction(frm, "in", "token", value, h, blk or 0, t.get("timestamp") or "",
                                   t.get("token") or {}, False, t.get("from") or {}))
    return out


def is_junk(it: Interaction, chain_id: int) -> bool:
    """Zero-value transfer, or a transfer of a token that looks fake."""
    if it.kind == "token" and token_red_flags(it.token, chain_id, ignore_labels=True):
        return True
    return it.is_zero


def is_real_payment(it: Interaction, chain_id: int) -> bool:
    """Wallet sent something of value and signed it itself."""
    return (it.direction == "out" and it.signed_by_wallet is True and not it.is_zero
            and not (it.kind == "token" and token_red_flags(it.token, chain_id, ignore_labels=True)))


def address_flagged(meta: dict | None) -> list[str]:
    """Blockscout's own labels on an address (scam flag, reputation, phishing tags)."""
    if not meta:
        return []
    reasons = []
    if meta.get("is_scam") or meta.get("reputation") == "scam":
        reasons.append("Blockscout marks this address as scam")
    for tag in ((meta.get("metadata") or {}).get("tags") or []):
        name = (tag.get("name") or "")
        if any(w in name.lower() for w in ("phish", "hack", "scam", "exploit", "fake")):
            reasons.append(f"Blockscout tag: {name}")
        if tag.get("tagType") == "note":
            note = ((tag.get("meta") or {}).get("data") or "").strip()
            if note:
                reasons.append(f"Blockscout note: {note}")
    return reasons
