from __future__ import annotations

import asyncio

from mcp.server import MCPServer


mcp = MCPServer("slow-test-server")


@mcp.tool(name="get_equipment_status")
async def get_equipment_status(equipment_id: str) -> dict[str, str]:
    await asyncio.sleep(0.5)
    return {"equipment_id": equipment_id}


if __name__ == "__main__":
    mcp.run("stdio")
