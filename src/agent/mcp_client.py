"""MCP client: stdio-based connection manager for Darwin's tool servers.

Resolves ``${VAR}`` placeholders in the config against both ``PROJECT_ROOT``
(a synthetic variable pointing at the repo root) and the current process
environment, so configs never need to hardcode paths or secrets.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from loguru import logger
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _expand(value: str, synthetic: dict[str, str]) -> str:
    """Expand ``${VAR}`` placeholders against ``synthetic`` then ``os.environ``.

    Unresolved placeholders are left intact so misconfiguration surfaces as a
    visible error rather than a silently-empty path.
    """

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        return synthetic.get(key) or os.environ.get(key) or match.group(0)

    return _ENV_RE.sub(repl, value)


class MCPClient:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.sessions: dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()
        self.tools: list[dict[str, Any]] = []
        self._tool_server_map: dict[str, ClientSession] = {}

    async def connect(self) -> None:
        """Spawn all configured MCP servers and initialise their sessions."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found at {self.config_path}")
            return

        project_root = str(Path(__file__).resolve().parent.parent.parent)
        synthetic = {"PROJECT_ROOT": project_root}

        for server_name, server_config in config.get("mcpServers", {}).items():
            logger.info(f"Connecting to {server_name}...")

            command = _expand(server_config["command"], synthetic)
            args = [_expand(a, synthetic) for a in server_config.get("args", [])]

            # Merge: parent env first, then server-specific overrides. ${VAR}
            # placeholders in the server-specific env block get expanded too.
            env = os.environ.copy()
            for k, v in server_config.get("env", {}).items():
                env[k] = _expand(str(v), synthetic)

            server_params = StdioServerParameters(command=command, args=args, env=env)
            try:
                read, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
                session = await self.exit_stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                self.sessions[server_name] = session
                logger.info(f"Connected to {server_name}")
            except Exception as e:
                logger.error(f"Failed to connect to {server_name}: {e}")

    async def list_tools(self) -> list[dict[str, Any]]:
        """Return all tools from all connected servers in OpenAI-function format."""
        self.tools = []
        self._tool_server_map = {}
        for name, session in self.sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    tool_def = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.inputSchema,
                        },
                    }
                    self.tools.append(tool_def)
                    self._tool_server_map[tool.name] = session
            except Exception as e:
                logger.error(f"Error listing tools for {name}: {e}")
        return self.tools

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Dispatch a tool call to whichever server exposes ``tool_name``."""
        session = self._tool_server_map.get(tool_name)
        if session is None:
            return f"Tool {tool_name} not found."
        logger.info(f"Calling {tool_name}...")
        try:
            return await session.call_tool(tool_name, arguments)
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return f"Error executing tool {tool_name}: {e}"

    async def cleanup(self) -> None:
        await self.exit_stack.aclose()
