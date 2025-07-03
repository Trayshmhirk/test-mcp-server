from typing import Any
import json
import httpx
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

# MCP Server name
mcp = FastMCP("chargekeep")

# ChargeKeep API details
CHARGEKEEP_API_BASE = "https://beta.chargekeep.com/api/services/CRM/Contact"
CHARGEKEEP_API_KEY = os.getenv("CHARGEKEEP_API_KEY")

HEADERS = {
    "accept": "application/json;odata.metadata=minimal;odata.streaming=true",
    "api-key": CHARGEKEEP_API_KEY,
}

async def fetch_contact_details(contact_id: str) -> dict[str, Any]:
    """Fetch contact details from ChargeKeep API."""
    url = f"{CHARGEKEEP_API_BASE}/GetContactDetails"
    params = {"contactId": contact_id}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=HEADERS, params=params, timeout=30.0)
            response.raise_for_status()
            return response.json()
        except Exception:
            # Return mock data for development or fallback
            return {
                "id": contact_id,
                "name": "John Doe",
                "email": "john.doe@example.com",
                "phone": "+1-555-0123",
                "status": "mock",
                "note": "This is fallback mock data due to API error"
            }

@mcp.tool()
async def get_contact_details(contact_id: str) -> str:
    """Get ChargeKeep contact details by contact ID."""
    data = await fetch_contact_details(contact_id)
    return json.dumps(data, indent=2)

if __name__ == "__main__":
    mcp.run(transport="stdio")
