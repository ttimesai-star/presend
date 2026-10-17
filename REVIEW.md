# External reviews

## Google Jules, 17 Oct 2026 (session 6982389221089873113, commit b0b37a6)

Jules reviewed a mirror branch of commit `b0b37a6`, ran the 25 tests (all passed) and posted a
written report with 18 findings. Each one was checked against the code; outcome below. Fixes are
in the commit after `b0b37a6`; regression tests are in `tests/test_review_fixes.py` and
`tests/test_web.py` (39 tests in total now).

| # | Finding (Jules severity) | Outcome |
|---|---|---|
| 1.1 | `lookalike_score` strips 2 chars even without `0x` (medium) | **Fixed.** `_hex()` strips only a real `0x` prefix. |
| 1.2 | Outgoing token transfers with unknown signer are not counted as payments (high) | **Fixed differently.** For an EOA wallet, every transaction it sent is in its own transaction list, so a transfer "from the wallet" inside the covered block range whose hash is not in that list is now marked *not signed* without any lookup. Only transfers older than the list stay unknown and go to the lookup budget. |
| (own) | Contract wallets (Safe, ERC-4337, EIP-7702): transactions are sent by an owner or bundler, so the tx-sender test would call every transfer "spoofed" | **Fixed.** Sender metadata is read first; for contract wallets no spoof claim is made from the tx sender, and non-junk outgoing transfers count as payments. |
| 1.3 | Testnet tokens flagged for missing price (medium) | **Fixed.** Price/holders rule is skipped on known testnets. |
| 1.4 | `exchange_rate: "0"` evades the no-price rule (medium) | **Fixed.** Zero or non-numeric price counts as no price. |
| 2.1 | Look-alike downgraded to CAUTION when the wallet already paid the fake once (high) | **Fixed.** It stays STOP when the recipient also has spoofed or junk entries in the wallet's history (a wallet that was already poisoned). Two clean look-alike payees stay CAUTION. |
| 2.2 | Spoof missed when signer stays unknown (high) | **Fixed** by 1.2 (inference from the wallet's own transaction list). |
| 2.3 | STOP on a clean new address that happens to match a past payee (medium) | **Kept as STOP, documented.** A random 7-character match at both ends has odds of about 4 in a billion per pair; a missed poisoning costs the whole payment. The message names the address it imitates so a human can confirm. |
| 2.4 | Lookup budget of 8 (medium) | **Mitigated** by 1.2: lookups are needed only for transfers older than the transaction window. |
| 3.1 | API key could leak through `RequestException` text (contains the URL) (high) | **Fixed.** Key is redacted from every error message; exception chain is cut (`from None`). Test added. |
| 3.2 | `pages()` yields items newer than the replay block (low) | **Kept.** `interactions()` filters by block; `pages()` stays a generic iterator. |
| 3.3 | `next_page_params` keys could collide with call kwargs (low) | **Fixed.** Dicts are merged; the page cursor wins. Test added. |
| 3.4 | 429 ignores `Retry-After` (low) | **Fixed.** `Retry-After` is honoured (capped at 30 s), exponential backoff otherwise. |
| 4.1 | `token` query parameter not validated (medium) | **Fixed** in the web handler and in `check_payment` itself (all interfaces), with a test for `../../stats`. |
| 4.2 | `javascript:` URI in evidence links (high) | **Fixed.** Only `https://` links are rendered; `rel="noopener noreferrer"`. |
| 4.3 | `verdict` and `as_of_block` interpolated without escaping (medium) | **Fixed.** Escaped. |
| 4.4 | Server without auth if bound to a public interface (low) | **Kept, documented.** Default host is `127.0.0.1`; the README says not to expose it. |
| 5.1 | No guidance for CAUTION in the MCP tool (medium) | **Fixed.** STOP: do not send. CAUTION: do not send automatically, get explicit human confirmation. OK is not a guarantee. |
| 5.2 | Parameter formats missing in MCP docstrings (low) | **Fixed.** |
