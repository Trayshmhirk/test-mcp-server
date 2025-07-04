# main.py
from fastapi import FastAPI
from chargekeep_server_http import ChargeKeepHTTPServer
from mcp_web_server import MCPWebServer

# Create servers
chargekeep = ChargeKeepHTTPServer()
web_server = MCPWebServer(use_http_mcp=False)
web_server.attach_server_instance(chargekeep)  # <-- you'd add this method

# Combine apps
app = FastAPI(title="ChargeKeep + MCP Web Server")
app.mount("/mcp", chargekeep.app)
app.mount("/", web_server.app)
