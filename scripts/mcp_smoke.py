"""Live MCP smoke test: start the stdio server and call presend_check (needs BLOCKSCOUT_API_KEY)."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "presend.mcp_server"],
                                   env={**os.environ})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            res = await s.call_tool("presend_check", {
                "sender": "0x1E227979f0b5BC691a70DEaed2e0F39a6F538FD5",
                "recipient": "0xd9A1C3788D81257612E2581A6ea0aDa244853a91",
                "as_of_block": 19789008, "use_labels": False})
            d = json.loads(res.content[0].text)
            print("verdict:", d["verdict"], [f["code"] for f in d["findings"]])

asyncio.run(main())
