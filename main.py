from fastapi import FastAPI
from chargekeep_server_http import ChargeKeepHTTPServer
from mcp_web_server import MCPWebServer
import os

# Use Render's dynamic port
port = int(os.getenv("PORT", 8000))

# Create the unified FastAPI app
app = FastAPI(title="ChargeKeep + MCP Web Server")

# Mount the ChargeKeep MCP HTTP server under /mcp
chargekeep_app = ChargeKeepHTTPServer().app
app.mount("/mcp", chargekeep_app)

# Mount the web UI app on root (/) — use full internal HTTP URL
web_app = MCPWebServer(
    use_http_mcp=True,
    http_mcp_url=f"http://localhost:{port}/mcp"
).app
app.mount("/", web_app)
