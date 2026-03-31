#!/usr/bin/env python
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

async def main():
    """Main agent loop"""
    # Load config
    try:
        with open("config/agent_config.json", "r") as f:
            agent_config = json.load(f)
    except FileNotFoundError:
        agent_config = {"model_name": "llama3.1", "api_base": "http://localhost:11434"}

    # Initialize clients
    ollama = OllamaClient(
        model_name=agent_config.get("model_name", "llama3.1"),
        host=agent_config.get("api_base", "http://localhost:11434"),
        system_prompt=agent_config.get("system_prompt", "")
    )
    
    mcp_client = MCPClient(config_path="config/claude_desktop_config.json")
    approved_papers = set()

    # Connect to MCP
    print("AGENT_READY", flush=True)  # Signal to wrapper that we're ready
    
    await mcp_client.connect()
    tools = await mcp_client.list_tools()

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
            
            skip_approval = "without approval" in user_input.lower() or "auto-download" in user_input.lower()
            messages.append({"role": "user", "content": user_input})

            # Agent turn loop
            while True:
                response = ollama.chat(messages, tools=tools)
                
                if "error" in response:
                    print(f"ERROR: {response['error']}", flush=True)
                    break

                message = response.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])
                
                if content:
                    print(f"AGENT_RESPONSE:{content}", flush=True)
                    messages.append({"role": "assistant", "content": content})
                
                if not tool_calls:
                    break
                
                messages.append(message)

                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name")
                    args = fn.get("arguments")
                    
                    args = convert_tool_arguments(args, tools, name)
                    
                    # Safety gate for downloads
                    if name == "download_paper":
                        paper_id = args.get("paper_id")
                        if skip_approval or paper_id in approved_papers:
                            pass  # Allow
                        else:
                            tool_result_message = {
                                "role": "tool",
                                "content": f"BLOCKED: Paper {paper_id} requires approval",
                                "name": name
                            }
                            messages.append(tool_result_message)
                            print(f"TOOL_BLOCKED:{name}:{paper_id}", flush=True)
                            continue
                    
                    # Handle confirm_download
                    if name == "confirm_download":
                        result = await mcp_client.call_tool(name, args)
                        content_str = str(result)
                        
                        print(f"TOOL_EXECUTE:{name}", flush=True)
                        
                        if skip_approval:
                            print(f"TOOL_AUTO_APPROVE", flush=True)
                            paper_id = args.get("paper_id")
                            approved_papers.add(paper_id)
                            response_msg = f"Auto-approved download of paper {paper_id}"
                        else:
                            print(f"TOOL_CONFIRM:{content_str}", flush=True)
                            # Wait for user decision
                            decision = sys.stdin.readline().strip().lower()
                            if decision in ["yes", "y"]:
                                paper_id = args.get("paper_id")
                                approved_papers.add(paper_id)
                                response_msg = f"User approved download of paper {paper_id}"
                                print(f"TOOL_USER_APPROVED", flush=True)
                            else:
                                response_msg = f"User rejected download"
                                print(f"TOOL_USER_REJECTED", flush=True)
                        
                        tool_result = {
                            "role": "tool",
                            "content": response_msg,
                            "name": name
                        }
                        messages.append(tool_result)
                    else:
                        # Regular tool execution
                        try:
                            result = await mcp_client.call_tool(name, args)
                            result_str = str(result)
                            print(f"TOOL_EXECUTE:{name}:{result_str[:100]}", flush=True)
                            
                            tool_result = {
                                "role": "tool",
                                "content": result_str,
                                "name": name
                            }
                            messages.append(tool_result)
                        except Exception as e:
                            error_str = f"Tool error: {str(e)}"
                            messages.append({
                                "role": "tool",
                                "content": error_str,
                                "name": name
                            })
                            print(f"TOOL_ERROR:{name}:{error_str}", flush=True)
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"ERROR:{str(e)}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
