"""MCP server (stdio) so an AI agent can run PreSend before it pays.

Run: BLOCKSCOUT_API_KEY=proapi_... python -m presend.mcp_server
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .check import check_payment, scan_wallet
from .client import BlockscoutClient

mcp = FastMCP("presend")


@mcp.tool()
def presend_check(sender: str, recipient: str, chain_id: int = 1, token: str | None = None,
                  as_of_block: int | None = None, use_labels: bool = True) -> dict:
    """Check a payment BEFORE sending it. Returns verdict STOP / CAUTION / OK with findings.

    Call this before any transfer or x402 payment to an address you did not type yourself.
    STOP: do not send; show the findings to the human. CAUTION: do not send automatically;
    show the findings and get explicit human confirmation. OK: no warning signs were found
    (this is not a guarantee).
    sender, recipient, token: 0x addresses of 40 hex characters. token is the ERC-20 contract
    you are sending; omit it for the native coin. chain_id: EVM chain id (1 = Ethereum).
    as_of_block: replay the check as of an older block. use_labels: use Blockscout scam labels.
    """
    rep = check_payment(BlockscoutClient(chain_id=chain_id), sender, recipient, token,
                        as_of_block, use_labels=use_labels)
    return rep.to_dict()


@mcp.tool()
def presend_scan(wallet: str, chain_id: int = 1, pages: int = 6) -> dict:
    """List address-poisoning attempts against a wallet: fake look-alikes of addresses it paid.

    wallet: 0x address. pages: how many pages of 50 history items to read (more = deeper, costs
    more API credits). An attempt with paid_by_wallet > 0 means the wallet already paid the fake.
    """
    return scan_wallet(BlockscoutClient(chain_id=chain_id), wallet, max_pages=pages)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
