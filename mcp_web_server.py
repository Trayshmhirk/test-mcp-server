import asyncio
import json
import sys
import os
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
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic()
        self.server_connected = False
        
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
            # You'll need to save the HTML artifact as 'chat.html' in the same directory
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
                "server_connected": self.server_connected
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

    async def connect_to_server(self, server_script_path: str):
        """Connect to an MCP server"""
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
            print(f"Connected to MCP server with tools: {[tool.name for tool in tools]}")
            
            self.server_connected = True
            return True
            
        except Exception as e:
            print(f"Failed to connect to MCP server: {e}")
            self.server_connected = False
            return False

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools"""
        if not self.session:
            raise Exception("MCP session not initialized")
            
        messages = [
            {
                "role": "user",
                "content": query
            }
        ]

        # Get available tools
        response = await self.session.list_tools()
        available_tools = [{ 
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema
        } for tool in response.tools]

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
                result = await self.session.call_tool(tool_name, tool_args)
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
                            "content": str(result.content)
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
        self.server_connected = False

async def main():
    if len(sys.argv) < 2:
        print("Usage: python web_server.py <path_to_server_script>")
        sys.exit(1)
    
    web_server = MCPWebServer()
    
    # Connect to MCP server
    server_script_path = sys.argv[1]
    print(f"Connecting to MCP server: {server_script_path}")
    
    success = await web_server.connect_to_server(server_script_path)
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
    print("Server will be available at the Render-provided URL")
    
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