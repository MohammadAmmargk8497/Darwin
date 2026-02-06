import asyncio
import json
import os
from contextlib import AsyncExitStack
from typing import Dict, Any, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPClient:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.tools: List[Dict[str, Any]] = []

    async def connect(self):
        """Connect to all servers defined in the config."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
        except FileNotFoundError:
            print(f"Config file not found at {self.config_path}")
            return

        for server_name, server_config in config.get("mcpServers", {}).items():
            print(f"Connecting to {server_name}...")
            
            # Resolve env vars in args/command
            # Simple resolution for now
            command = server_config["command"]
            args = server_config.get("args", [])
            env = os.environ.copy()
            env.update(server_config.get("env", {}))
            
            # Allow ${PROJECT_ROOT} expansion
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
            args = [arg.replace("${PROJECT_ROOT}", project_root) for arg in args]

            server_params = StdioServerParameters(
                command=command,
                args=args,
                env=env
            )

            try:
                # Enter the stdio_client context
                read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
                
                # Enter the ClientSession context
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                
                await session.initialize()
                self.sessions[server_name] = session
                print(f"Connected to {server_name}")
                
            except Exception as e:
                print(f"Failed to connect to {server_name}: {e}")

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List all tools from all connected servers."""
        self.tools = []
        for name, session in self.sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    # Convert to OpenAI/Ollama compatible format
                    # MCP tool schema -> OpenAI function schema
                    # Note: MCP 'inputSchema' is strictly JSON schema
                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema
                        }
                    }
                    self.tools.append(tool_def)
            except Exception as e:
                print(f"Error listing tools for {name}: {e}")
        return self.tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool by name (finding the right server)."""
        # Find which server has the tool
        # We need to cache which server has which tool, or query. 
        # For simplicity, we query all or iterate. 
        # Better: map tool_name -> server_session during list_tools
        
        # Re-scanning for now to find the server
        for name, session in self.sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                if tool.name == tool_name:
                    print(f"Calling {tool_name} on {name}...")
                    try:
                        result = await session.call_tool(tool_name, arguments)
                        return result
                    except Exception as e:
                        return f"Error executing tool {tool_name}: {e}"
        
        return f"Tool {tool_name} not found."

    async def cleanup(self):
        """Close specific sessions."""
        await self.exit_stack.aclose()
