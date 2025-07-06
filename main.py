import os
import asyncio
from fastapi import FastAPI
from mcp_web_server import MCPWebServer

# Use Render dynamic port
port = int(os.getenv("PORT", 10000))

# Create web server instance
web_server = MCPWebServer(
    use_http_mcp=True,
    http_mcp_url="https://chargekeep-mcp-server.onrender.com/mcp",
)

# Ensure connection to HTTP MCP server on startup
async def startup_event():
    await web_server.connect_to_http_server("https://chargekeep-mcp-server.onrender.com/mcp")

# Unified FastAPI app
app = web_server.app
app.add_event_handler("startup", startup_event)
