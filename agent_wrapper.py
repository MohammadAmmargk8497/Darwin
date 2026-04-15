#!/usr/bin/env python3
"""
Wrapper script for running agent in subprocess mode.
Reads commands from stdin and writes results to stdout.
"""
import asyncio
import json
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent.ollama_client import OllamaClient
from src.agent.openai_client import OpenAIClient
from src.agent.mcp_client import MCPClient

def convert_tool_arguments(args: dict, tool_definitions: list, tool_name: str) -> dict:
    """Convert tool arguments to correct types based on tool schema."""
    tool_def = None
    for tool in tool_definitions:
        if tool.get('function', {}).get('name') == tool_name:
            tool_def = tool
            break
    
    if not tool_def:
        return args
    
    properties = tool_def.get('function', {}).get('parameters', {}).get('properties', {})
    
    converted = {}
    for key, value in args.items():
        if key in properties:
            param_type = properties[key].get('type')
            if param_type == 'integer' and isinstance(value, str):
                try:
                    converted[key] = int(value)
                except (ValueError, TypeError):
                    converted[key] = value
            elif param_type == 'number' and isinstance(value, str):
                try:
                    converted[key] = float(value)
                except (ValueError, TypeError):
                    converted[key] = value
            else:
                converted[key] = value
        else:
            converted[key] = value
    
    return converted

def _extract_result_text(result) -> str:
    """Extract plain text from an MCP CallToolResult (or fall back to str)."""
    if hasattr(result, "content") and isinstance(result.content, list):
        parts = []
        for item in result.content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
        if parts:
            return "\n".join(parts)
    return str(result)


async def main():
    """Main agent loop"""
    # Load config — DARWIN_CONFIG env var overrides the default path
    config_path = os.environ.get("DARWIN_CONFIG", "config/agent_config.json")
    try:
        with open(config_path, "r") as f:
            agent_config = json.load(f)
    except FileNotFoundError:
        agent_config = {"model_name": "llama3.1", "api_base": "http://localhost:11434"}

    # Initialize the right client based on provider
    provider = agent_config.get("provider", "ollama").lower()
    if provider == "openai":
        llm_client = OpenAIClient(
            model_name=agent_config.get("model_name", "gpt-4"),
            api_key=agent_config.get("api_key") or os.environ.get("OPENAI_API_KEY", ""),
            base_url=agent_config.get("api_base", "https://api.openai.com/v1"),
            system_prompt=agent_config.get("system_prompt", "")
        )
    else:
        llm_client = OllamaClient(
            model_name=agent_config.get("model_name", "llama3.1"),
            host=agent_config.get("api_base", "http://localhost:11434"),
            system_prompt=agent_config.get("system_prompt", "")
        )
    ollama = llm_client  # keep existing variable name so the rest of the file is unchanged
    
    mcp_client = MCPClient(config_path="config/claude_desktop_config.json")
    approved_papers = set()

    # Connect to MCP
    await mcp_client.connect()
    tools = await mcp_client.list_tools()
    print("AGENT_READY", flush=True)  # Signal to UI that we're ready

    # Chat loop
    messages = []
    if agent_config.get("system_prompt"):
        messages.append({"role": "system", "content": agent_config["system_prompt"]})

    while True:
        try:
            # Read command from stdin
            user_input = sys.stdin.readline().strip()
            if not user_input or user_input.lower() in ["exit", "quit"]:
                print("AGENT_EXIT", flush=True)
                break
            
            import re as _re
            skip_approval = (
                "without approval" in user_input.lower() or
                "auto-download" in user_input.lower() or
                bool(_re.match(r'^download\s+(paper\s+)?[\w.]+$', user_input.strip(), _re.IGNORECASE))
            )
            messages.append({"role": "user", "content": user_input})

            # Agent turn loop
            while True:
                # Ollama can throw transient 500s during model reload — retry a few times.
                # OpenAI/Groq errors are not transient so we don't retry there.
                if provider == "ollama":
                    import time as _time
                    for attempt in range(3):
                        response = llm_client.chat(messages, tools=tools)
                        if "error" not in response:
                            break
                        if attempt < 2:
                            print(f"TOOL_EXECUTE:retrying after Ollama error (attempt {attempt+1})", flush=True)
                            _time.sleep(20)
                else:
                    response = llm_client.chat(messages, tools=tools)

                if "error" in response:
                    print(f"ERROR: {response['error']}", flush=True)
                    break

                message = response.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])

                if content:
                    # Prefix every line so the UI's readline() loop captures all of them.
                    # A bare print(f"AGENT_RESPONSE:{content}") drops everything after
                    # the first newline because the UI reads one line at a time.
                    for line in content.splitlines():
                        print(f"AGENT_RESPONSE:{line}", flush=True)

                if not tool_calls:
                    # No tool calls — content is the final response for this turn
                    if content:
                        messages.append({"role": "assistant", "content": content})
                    break

                # Has tool calls — append full message (already contains content if any)
                messages.append(message)

                for tc in tool_calls:
                    tool_call_id = tc.get("id")  # required by OpenAI/Groq; ignored by Ollama
                    fn = tc.get("function", {})
                    name = fn.get("name")
                    args = fn.get("arguments")

                    # Groq/OpenAI returns arguments as a JSON string; Ollama returns a dict
                    if isinstance(args, str):
                        args = json.loads(args)

                    args = convert_tool_arguments(args, tools, name)

                    # Safety gate for downloads
                    if name == "download_paper":
                        paper_id = args.get("paper_id")
                        if skip_approval or paper_id in approved_papers:
                            pass  # Allow
                        else:
                            blocked_msg = {"role": "tool", "name": name, "content": f"BLOCKED: Paper {paper_id} requires approval"}
                            if tool_call_id:
                                blocked_msg["tool_call_id"] = tool_call_id
                            messages.append(blocked_msg)
                            print(f"TOOL_BLOCKED:{name}:{paper_id}", flush=True)
                            continue

                    # Handle confirm_download
                    if name == "confirm_download":
                        result = await mcp_client.call_tool(name, args)
                        print(f"TOOL_EXECUTE:{name}", flush=True)

                        if skip_approval:
                            print(f"TOOL_AUTO_APPROVE", flush=True)
                            paper_id = args.get("paper_id")
                            approved_papers.add(paper_id)
                            response_msg = f"Auto-approved download of paper {paper_id}"
                        else:
                            content_str = _extract_result_text(result)
                            print(f"TOOL_CONFIRM:{content_str}", flush=True)
                            decision = sys.stdin.readline().strip().lower()
                            if decision in ["yes", "y"]:
                                paper_id = args.get("paper_id")
                                approved_papers.add(paper_id)
                                response_msg = f"User approved download of paper {paper_id}"
                                print(f"TOOL_USER_APPROVED", flush=True)
                            else:
                                response_msg = "User rejected download"
                                print(f"TOOL_USER_REJECTED", flush=True)

                        confirm_result_msg = {"role": "tool", "name": name, "content": response_msg}
                        if tool_call_id:
                            confirm_result_msg["tool_call_id"] = tool_call_id
                        messages.append(confirm_result_msg)
                    else:
                        # Regular tool execution
                        try:
                            result = await mcp_client.call_tool(name, args)
                            result_str = _extract_result_text(result)
                            print(f"TOOL_EXECUTE:{name}:{result_str[:100]}", flush=True)

                            # For search results, send each paper as structured JSON
                            # using the PAPER_CARD: prefix so the UI renders them as
                            # cards (not mixed into the text response).
                            if name == "search_papers":
                                try:
                                    search_results = json.loads(result_str)
                                    actual = [p for p in search_results if not p.get("error")]
                                    for p in actual:
                                        card = json.dumps({
                                            "id": p.get("id", ""),
                                            "title": p.get("title", ""),
                                            "summary": p.get("summary", "")[:300],
                                            "arxiv_url": p.get("arxiv_url", ""),
                                            "pdf_url": p.get("pdf_url", ""),
                                            "authors": p.get("authors", ""),
                                            "published": p.get("published", ""),
                                        })
                                        print(f"PAPER_CARD:{card}", flush=True)
                                except Exception:
                                    pass

                            tool_result_msg = {"role": "tool", "name": name, "content": result_str}
                            if tool_call_id:
                                tool_result_msg["tool_call_id"] = tool_call_id
                            messages.append(tool_result_msg)
                        except Exception as e:
                            error_str = f"Tool error: {str(e)}"
                            error_msg = {"role": "tool", "name": name, "content": error_str}
                            if tool_call_id:
                                error_msg["tool_call_id"] = tool_call_id
                            messages.append(error_msg)
                            print(f"TOOL_ERROR:{name}:{error_str}", flush=True)

            print("AGENT_END", flush=True)  # Signal UI that this command is fully done

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR:{str(e)}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
