from fastapi import FastAPI
from chargekeep_server_http import ChargeKeepHTTPServer
from mcp_web_server import MCPWebServer

# Create the unified FastAPI app
app = FastAPI(title="ChargeKeep + MCP Web Server")

# Mount the ChargeKeep MCP HTTP server under /mcp
chargekeep_app = ChargeKeepHTTPServer().app
app.mount("/mcp", chargekeep_app)

# Mount the web UI app on root (/) — will use HTTP MCP mode
web_app = MCPWebServer(
    use_http_mcp=True,
    http_mcp_url="/mcp"
).app
app.mount("/", web_app)
