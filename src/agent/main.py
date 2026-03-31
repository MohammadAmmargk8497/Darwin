import asyncio
import json
import os
import sys

from .ollama_client import OllamaClient
from .mcp_client import MCPClient

# Colors for terminal output
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def convert_tool_arguments(args: dict, tool_definitions: list, tool_name: str) -> dict:
    """Convert tool arguments to correct types based on tool schema."""
    # Find the tool definition
    tool_def = None
    for tool in tool_definitions:
        if tool.get('function', {}).get('name') == tool_name:
            tool_def = tool
            break
    
    if not tool_def:
        return args
    
    # Get properties from schema
    properties = tool_def.get('function', {}).get('parameters', {}).get('properties', {})
    
    # Convert each argument to correct type
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

async def run_agent():
    # 1. Load Config
    try:
        with open("config/agent_config.json", "r") as f:
            agent_config = json.load(f)
    except FileNotFoundError:
        print("config/agent_config.json not found. Using defaults.")
        agent_config = {"model_name": "llama3.1", "api_base": "http://localhost:11434"}

    # 2. Initialize Clients
    ollama = OllamaClient(
        model_name=agent_config.get("model_name", "llama3.1"),
        host=agent_config.get("api_base", "http://localhost:11434"),
        system_prompt=agent_config.get("system_prompt", "")
    )
    
    mcp_client = MCPClient(config_path="config/claude_desktop_config.json")
    
    # Track approved papers for Human-in-the-Loop enforcement
    approved_papers = set()
    
    print(f"{BLUE}Connecting to MCP servers...{RESET}")
    await mcp_client.connect()
    
    try:
        # 3. List Tools
        print(f"{BLUE}Discovering tools...{RESET}")
        tools = await mcp_client.list_tools()
        print(f"{GREEN}Found {len(tools)} tools.{RESET}")
        for t in tools:
            print(f"  - {t['function']['name']}")

        # 4. Chat Loop
        messages = []
        if agent_config.get("system_prompt"):
            messages.append({"role": "system", "content": agent_config["system_prompt"]})

        print(f"\n{BLUE}Agent ready. Type 'exit' to quit.{RESET}")
        
        while True:
            try:
                user_input = input(f"\n{GREEN}You: {RESET}")
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                messages.append({"role": "user", "content": user_input})
                
                # --- Turn Loop (Handle Tool Calls) ---
                while True:
                    response = ollama.chat(messages, tools=tools)
                    
                    if "error" in response:
                        print(f"{YELLOW}Error from LLM: {response['error']}{RESET}")
                        break

                    message = response.get("message", {})
                    content = message.get("content", "")
                    tool_calls = message.get("tool_calls", [])
                    
                    # Print content if any
                    if content:
                        print(f"{BLUE}Agent:{RESET} {content}")
                        messages.append({"role": "assistant", "content": content})
                    
                    if not tool_calls:
                        break
                    
                    # Handle tool calls
                    # Note: Need to append the tool calls to history correctly for the API to contextually understand
                    # Ollama's API for adding tool calls to history might differ slighty, check documentation.
                    # Usually: append message with tool_calls
                    messages.append(message) 

                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        name = fn.get("name")
                        args = fn.get("arguments")
                        
                        # Convert arguments to correct types
                        args = convert_tool_arguments(args, tools, name)
                        
                        # HUMAN-IN-THE-LOOP ENFORCEMENT: Block downloads without approval
                        if name == "download_paper":
                            paper_id = args.get("paper_id")
                            if paper_id not in approved_papers:
                                # Paper not approved - this shouldn't happen with proper workflow
                                # but we block it anyway as safety net
                                print(f"{YELLOW}⚠️  Safety Gate: Paper {paper_id} attempted download without approval!{RESET}")
                                tool_result_message = {
                                    "role": "tool",
                                    "content": f"BLOCKED: Paper {paper_id} requires approval via confirm_download first. Please ask the user for approval.",
                                    "name": name
                                }
                                messages.append(tool_result_message)
                                print(f"{YELLOW}Tool result: Paper blocked - requires approval{RESET}")
                                continue
                        
                        # Track approved papers from confirm_download results
                        if name == "confirm_download":
                            result = await mcp_client.call_tool(name, args)
                            content_str = str(result)
                            if hasattr(result, 'content') and isinstance(result.content, list):
                                text_parts = []
                                for item in result.content:
                                    if hasattr(item, 'text'):
                                        text_parts.append(item.text)
                                    elif isinstance(item, dict) and 'text' in item:
                                        text_parts.append(item['text'])
                                if text_parts:
                                    content_str = "\n".join(text_parts)
                            
                            print(f"{YELLOW}Executing tool: {name}...{RESET}")
                            print(f"{YELLOW}Args: {args}{RESET}")
                            print(f"\n{BLUE}Confirmation Required:{RESET}")
                            print(content_str)
                            
                            # Get user decision
                            while True:
                                user_decision = input(f"\n{GREEN}Approve? (yes/no/skip): {RESET}").strip().lower()
                                if user_decision in ["yes", "y"]:
                                    paper_id = args.get("paper_id")
                                    approved_papers.add(paper_id)
                                    response_msg = f"User approved download of paper {paper_id}"
                                    print(f"{GREEN}✓ Approved{RESET}")
                                    break
                                elif user_decision in ["no", "n", "skip", "s"]:
                                    response_msg = f"User rejected download"
                                    print(f"{YELLOW}✗ Rejected{RESET}")
                                    break
                                else:
                                    print(f"{YELLOW}Please enter 'yes', 'no', or 'skip'{RESET}")
                            
                            tool_result_message = {
                                "role": "tool",
                                "content": response_msg,
                                "name": name
                            }
                            messages.append(tool_result_message)
                            continue
                        
                        print(f"{YELLOW}Executing tool: {name}...{RESET}")
                        print(f"{YELLOW}Args: {args}{RESET}")
                        
                        # Execute
                        result = await mcp_client.call_tool(name, args)
                        
                        # Extract content from result if it's an MCP CallToolResult
                        # (Simulated check, actual types depend on mcp lib version imported)
                        content_str = str(result)
                        if hasattr(result, 'content') and isinstance(result.content, list):
                            text_parts = []
                            for item in result.content:
                                if hasattr(item, 'text'):
                                    text_parts.append(item.text)
                                elif isinstance(item, dict) and 'text' in item:
                                    text_parts.append(item['text'])
                            if text_parts:
                                content_str = "\n".join(text_parts)

                        # Feed back result
                        tool_result_message = {
                            "role": "tool",
                            "content": content_str,
                            "name": name 
                        }
                        messages.append(tool_result_message)
                        print(f"{YELLOW}Tool result: {content_str[:200]}...{RESET}")
                    
                    # Do not break loop, go back to top to let LLM process result
                    
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"{YELLOW}Error: {e}{RESET}")
                import traceback
                traceback.print_exc()

    finally:
        await mcp_client.cleanup()
        print(f"{BLUE}Disconnected.{RESET}")

def main():
    asyncio.run(run_agent())

if __name__ == "__main__":
    main()
