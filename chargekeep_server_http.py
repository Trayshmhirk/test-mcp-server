from typing import Any, Dict
import json
import httpx
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = {}
    id: int = 1

class MCPResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: Any = None
    error: Any = None
    id: int = 1

class ChargeKeepHTTPServer:
    def __init__(self):
        self.app = FastAPI(title="ChargeKeep MCP HTTP Server")
        
        # ChargeKeep API details
        self.CHARGEKEEP_API_BASE = "https://beta.chargekeep.com/api/services/CRM/Contact"
        self.CHARGEKEEP_API_KEY = os.getenv("CHARGEKEEP_API_KEY")
        self.headers = {
            "accept": "application/json;odata.metadata=minimal;odata.streaming=true",
            "api-key": self.CHARGEKEEP_API_KEY,
        }
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        self.setup_routes()
    
    def setup_routes(self):
        @self.app.post("/mcp")
        async def mcp_endpoint(request: MCPRequest):
            """Handle MCP protocol requests over HTTP"""
            try:
                if request.method == "initialize":
                    return MCPResponse(
                        result={
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {}
                            },
                            "serverInfo": {
                                "name": "chargekeep-http",
                                "version": "1.0.0"
                            }
                        },
                        id=request.id
                    )
                
                elif request.method == "tools/list":
                    return MCPResponse(
                        result={
                            "tools": [
                                {
                                    "name": "get_contact_details",
                                    "description": "Get ChargeKeep contact details by contact ID.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "contact_id": {
                                                "type": "string",
                                                "description": "The contact ID to fetch details for"
                                            }
                                        },
                                        "required": ["contact_id"]
                                    }
                                }
                            ]
                        },
                        id=request.id
                    )
                
                elif request.method == "tools/call":
                    tool_name = request.params.get("name")
                    tool_args = request.params.get("arguments", {})
                    
                    if tool_name == "get_contact_details":
                        contact_id = tool_args.get("contact_id")
                        if not contact_id:
                            return MCPResponse(
                                error={
                                    "code": -32602,
                                    "message": "Missing required parameter: contact_id"
                                },
                                id=request.id
                            )
                        
                        result = await self.fetch_contact_details(contact_id)
                        return MCPResponse(
                            result={
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps(result, indent=2)
                                    }
                                ]
                            },
                            id=request.id
                        )
                    
                    else:
                        return MCPResponse(
                            error={
                                "code": -32601,
                                "message": f"Unknown tool: {tool_name}"
                            },
                            id=request.id
                        )
                
                else:
                    return MCPResponse(
                        error={
                            "code": -32601,
                            "message": f"Unknown method: {request.method}"
                        },
                        id=request.id
                    )
                    
            except Exception as e:
                return MCPResponse(
                    error={
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    },
                    id=request.id
                )
        
        @self.app.get("/health")
        async def health_check():
            """Health check endpoint"""
            return JSONResponse({
                "status": "healthy",
                "api_connected": bool(self.CHARGEKEEP_API_KEY),
                "type": "http_mcp_server"
            })
        
        @self.app.get("/")
        async def root():
            """Root endpoint with usage instructions"""
            return JSONResponse({
                "message": "ChargeKeep MCP HTTP Server",
                "usage": "This server exposes ChargeKeep MCP tools over HTTP",
                "endpoints": {
                    "/mcp": "MCP protocol endpoint",
                    "/health": "Health check",
                    "/": "This information"
                }
            })

    async def fetch_contact_details(self, contact_id: str) -> dict:
        """Fetch contact details from ChargeKeep API."""
        url = f"{self.CHARGEKEEP_API_BASE}/GetContactDetails"
        params = {"contactId": contact_id}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, headers=self.headers, params=params, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                # Return mock data for development or fallback
                return {
                    "id": contact_id,
                    "name": "John Doe",
                    "email": "john.doe@example.com",
                    "phone": "+1-555-0123",
                    "status": "mock",
                    "note": f"This is fallback mock data due to API error: {str(e)}"
                }

# For standalone running
if __name__ == "__main__":
    import uvicorn
    
    server = ChargeKeepHTTPServer()
    port = int(os.getenv("PORT", 8001))
    
    print(f"Starting ChargeKeep HTTP MCP Server on http://0.0.0.0:{port}")
    
    config = uvicorn.Config(
        app=server.app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
    uvicorn_server = uvicorn.Server(config)
    import asyncio
    asyncio.run(uvicorn_server.serve())