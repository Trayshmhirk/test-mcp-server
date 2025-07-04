import asyncio
import json
import sys
import os
import httpx
from pathlib import Path
from typing import Optional
from contextlib import AsyncExitStack

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

class ChatRequest(BaseModel):
    message: str

class MCPWebServer:
    def __init__(self, use_http_mcp: bool = False, http_mcp_url: str = None):
        self.use_http_mcp = use_http_mcp
        self.http_mcp_url = http_mcp_url
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        self.server_connected = False
        self.http_client = httpx.AsyncClient() if use_http_mcp else None
        
        # Create FastAPI app
        self.app = FastAPI(title="MCP Web Chat Server")
        
        # Add CORS middleware
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Setup routes
        self.setup_routes()

    def setup_routes(self):
        @self.app.get("/", response_class=HTMLResponse)
        async def serve_chat_ui():
            """Serve the chat UI HTML"""
            html_path = Path(__file__).parent / "chat.html"
            if html_path.exists():
                return HTMLResponse(content=html_path.read_text(), status_code=200)
            else:
                return HTMLResponse(
                    content="<h1>Chat UI not found</h1><p>Please save the chat HTML as 'chat.html' in the same directory.</p>",
                    status_code=404
                )

        @self.app.get("/health")
        async def health_check():
            """Health check endpoint"""
            return JSONResponse({
                "status": "healthy" if self.server_connected else "disconnected",
                "server_connected": self.server_connected,
                "mcp_protocol": "http" if self.use_http_mcp else "stdio",
                "mcp_url": self.http_mcp_url if self.use_http_mcp else None
            })

        @self.app.post("/chat")
        async def chat_endpoint(request: ChatRequest):
            """Handle chat messages"""
            if not self.server_connected:
                raise HTTPException(status_code=503, detail="MCP server not connected")
            
            try:
                response = await self.process_query(request.message)
                return JSONResponse({"response": response})
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

    async def connect_to_stdio_server(self, server_script_path: str):
        """Connect to a stdio MCP server"""
        try:
            is_python = server_script_path.endswith('.py')
            is_js = server_script_path.endswith('.js')
            if not (is_python or is_js):
                raise ValueError("Server script must be a .py or .js file")
                
            command = "python" if is_python else "node"
            server_params = StdioServerParameters(
                command=command,
                args=[server_script_path],
                env=None
            )
            
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
            
            await self.session.initialize()
            
            # List available tools
            response = await self.session.list_tools()
            tools = response.tools
            print(f"Connected to stdio MCP server with tools: {[tool.name for tool in tools]}")
            
            self.server_connected = True
            return True
            
        except Exception as e:
            print(f"Failed to connect to stdio MCP server: {e}")
            self.server_connected = False
            return False

    async def connect_to_http_server(self, http_url: str):
        """Connect to an HTTP MCP server"""
        try:
            # Test connection with initialize
            response = await self.send_http_mcp_request("initialize", {})
            if response.get("error"):
                raise Exception(f"Initialize failed: {response['error']}")
            
            print(f"Connected to HTTP MCP server at: {http_url}")
            self.server_connected = True
            return True
            
        except Exception as e:
            print(f"Failed to connect to HTTP MCP server: {e}")
            self.server_connected = False
            return False

    async def send_http_mcp_request(self, method: str, params: dict, request_id: int = 1):
        """Send request to HTTP MCP server"""
        request_data = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id
        }
        
        response = await self.http_client.post(
            self.http_mcp_url,
            json=request_data,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()

    async def get_available_tools(self):
        """Get available tools from either stdio or HTTP MCP server"""
        if self.use_http_mcp:
            response = await self.send_http_mcp_request("tools/list", {})
            if response.get("error"):
                return []
            tools = response.get("result", {}).get("tools", [])
            return [{
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["inputSchema"]
            } for tool in tools]
        else:
            response = await self.session.list_tools()
            return [{
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            } for tool in response.tools]

    async def call_tool(self, tool_name: str, tool_args: dict):
        """Call a tool on either stdio or HTTP MCP server"""
        if self.use_http_mcp:
            response = await self.send_http_mcp_request(
                "tools/call", 
                {"name": tool_name, "arguments": tool_args}
            )
            if response.get("error"):
                raise Exception(f"Tool call failed: {response['error']}")
            return response.get("result", {}).get("content", [{}])[0].get("text", "")
        else:
            result = await self.session.call_tool(tool_name, tool_args)
            return str(result.content)

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        if not self.server_connected:
            raise Exception("MCP server not connected")
            
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        # Get available tools
        available_tools = await self.get_available_tools()

        # Initial Claude API call
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=messages,
            tools=available_tools
        )

        # Process response and handle tool calls
        final_text = []

        for content in response.content:
            if content.type == 'text':
                final_text.append(content.text)
            elif content.type == 'tool_use':
                tool_name = content.name
                tool_args = content.input
                
                # Execute tool call
                result = await self.call_tool(tool_name, tool_args)
                final_text.append(f"[Calling tool {tool_name} with args {tool_args}]")

                # Continue conversation with tool results
                messages.append({
                    "role": "assistant",
                    "content": [content]  # Include the tool use content
                })
                messages.append({
                    "role": "user", 
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": content.id,
                            "content": result
                        }
                    ]
                })

                # Get next response from Claude
                response = self.anthropic.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=1000,
                    messages=messages,
                    tools=available_tools
                )

                # Add the final response
                for content_item in response.content:
                    if content_item.type == 'text':
                        final_text.append(content_item.text)

        return "\n".join(final_text)

    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()
        if self.http_client:
            await self.http_client.aclose()
        self.server_connected = False

async def main():
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Stdio MCP: python mcp_web_server.py <path_to_server_script>")
        print("  HTTP MCP:  python mcp_web_server.py --http <http_mcp_url>")
        print("Examples:")
        print("  python mcp_web_server.py chargekeep_server.py")
        print("  python mcp_web_server.py --http http://localhost:8001/mcp")
        sys.exit(1)
    
    # Determine if using HTTP or stdio
    use_http = sys.argv[1] == "--http"
    
    if use_http:
        if len(sys.argv) < 3:
            print("HTTP MCP URL required after --http flag")
            sys.exit(1)
        http_url = sys.argv[2]
        web_server = MCPWebServer(use_http_mcp=True, http_mcp_url=http_url)
        print(f"Using HTTP MCP server: {http_url}")
        success = await web_server.connect_to_http_server(http_url)
    else:
        server_script_path = sys.argv[1]
        web_server = MCPWebServer(use_http_mcp=False)
        print(f"Using stdio MCP server: {server_script_path}")
        success = await web_server.connect_to_stdio_server(server_script_path)
    
    if not success:
        print("Failed to connect to MCP server. Exiting.")
        sys.exit(1)
    
    # Import uvicorn here to avoid import issues
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not found. Please install it with: pip install uvicorn")
        sys.exit(1)
    
    # Get port from environment (Render provides this via PORT)
    port = int(os.getenv("PORT", 8000))
    print(f"Starting web server on http://0.0.0.0:{port}")
    
    try:
        # Run the web server
        config = uvicorn.Config(
            app=web_server.app,
            host="0.0.0.0",
            port=port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await web_server.cleanup()

if __name__ == "__main__":
    asyncio.run(main())