import asyncio
import json
import os
import sys

from .ollama_client import OllamaClient
from .openai_client import OpenAIClient
from .mcp_client import MCPClient

# Colors for terminal output
BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

async def run_agent():
    # 1. Load Config
    try:
        with open("config/agent_config.json", "r") as f:
            agent_config = json.load(f)
    except FileNotFoundError:
        print("config/agent_config.json not found. Using defaults.")
        agent_config = {"model_name": "llama3.1", "api_base": "http://localhost:11434"}

    # 2. Initialize Clients based on provider
    provider = agent_config.get("provider", "ollama").lower()
    
    if provider == "openai":
        # OpenAI or compatible API
        api_key = agent_config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print(f"{RED}Error: OpenAI API key not found. Set 'api_key' in config or OPENAI_API_KEY env var.{RESET}")
            return
        
        llm_client = OpenAIClient(
            model_name=agent_config.get("model_name", "gpt-4"),
            api_key=api_key,
            base_url=agent_config.get("api_base", "https://api.openai.com/v1"),
            system_prompt=agent_config.get("system_prompt", "")
        )
        print(f"{GREEN}Using OpenAI API with model: {agent_config.get('model_name', 'gpt-4')}{RESET}")
    
    elif provider == "ollama":
        # Local Ollama
        llm_client = OllamaClient(
            model_name=agent_config.get("model_name", "llama3.1"),
            host=agent_config.get("api_base", "http://localhost:11434"),
            system_prompt=agent_config.get("system_prompt", "")
        )
        print(f"{GREEN}Using Ollama with model: {agent_config.get('model_name', 'llama3.1')}{RESET}")
    
    else:
        print(f"{RED}Unknown provider: {provider}. Use 'ollama' or 'openai'{RESET}")
        return
    
    mcp_client = MCPClient(config_path="config/claude_desktop_config.json")
    
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
                    response = llm_client.chat(messages, tools=tools)
                    
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
                        tool_call_id = tc.get("id")  # Get the tool call ID
                        fn = tc.get("function", {})
                        name = fn.get("name")
                        args_raw = fn.get("arguments")
                        
                        # Parse arguments if they're a string (from OpenAI/Groq API)
                        if isinstance(args_raw, str):
                            args = json.loads(args_raw)
                        else:
                            args = args_raw
                        
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

                        # Feed back result - include tool_call_id for Groq/OpenAI compatibility
                        tool_result_message = {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": content_str,
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
