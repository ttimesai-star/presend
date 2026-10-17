# Concept selection (17 Oct 2026)

Judging weights from the Craftora brief: Blockscout API integration 30, real-world utility 20,
technical execution 20, creativity 15, UX and demo 10, Blockscout showcase 5.

Constraints: one builder, Sprint 1 ends 21 Oct (MVP, repo, short demo), Sprint 2 25-31 Oct
(final, 3-5 min video, X post). Free PRO API tier: 100k credits/day, 5 RPS; Base, Polygon and
zkSync are not on the free tier.

What was already submitted (Submissions tab, 17 Oct): Carpan (USDC accounting review),
ChainLens, DiDo (token holder map / insiders). Blockscout already ships an official MCP server
(`blockscout/mcp-server`), so "a generic MCP wrapper over the API" adds little.

| # | Concept | Integration (30) | Utility (20) | Execution risk (20) | Creativity (15) | Demo (10+5) | Total /100 |
|---|---|---|---|---|---|---|---|
| A | **PreSend**: a pre-payment check for wallets and AI agents. Before sending funds, compare the recipient with the sender's own history from Blockscout and stop address-poisoning lookalikes, spoofed "from you" transfers, fake tokens and flagged addresses. CLI + MCP tool + JSON. | 27 (core verdict is built only from Blockscout address, transactions, token-transfers, transaction and token endpoints) | 18 (address poisoning stole 1,155 WBTC in one transfer in May 2024; agents paying via x402 copy addresses from history) | 16 (pure-function analysis, offline fixtures, live smoke) | 12 (replay mode: "what would PreSend have said one block before the theft") | 13 (real case on Blockscout Explorer, before/after) | **86** |
| B | Generic Blockscout MCP server for agents (history, contract info, x402 address check) | 22 | 12 | 17 | 5 (official MCP server exists) | 10 | 66 |
| C | Agent audit journal: reconcile what an agent says it paid with Blockscout evidence | 20 | 12 | 14 | 11 | 9 | 66 |

Scores are our own estimate, not the jury's.

Decision: **A (PreSend)**. It covers the brief's "address-poisoning detection" area, keeps
Blockscout as the only data source, and has a real, verifiable case for the demo. The MCP tool
from B is kept as one interface of A, not as the product.
