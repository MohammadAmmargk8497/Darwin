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
            elif param_type == 'array' and isinstance(value, str):
                try:
                    import ast
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, list):
                        converted[key] = parsed
                    else:
                        converted[key] = value
                except (ValueError, SyntaxError):
                    try:
                        converted[key] = json.loads(value)
                    except (ValueError, TypeError):
                        converted[key] = value
            else:
                converted[key] = value
        else:
            # Drop arguments not in schema — small models hallucinate extra params
            pass

    # Remove empty/null values that confuse MCP schema validation
    return {k: v for k, v in converted.items() if v is not None and v != [] and v != {} and v != ""}

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


def _health_check_llm(provider: str, api_base: str, model_name: str) -> None:
    """Ping the LLM backend; emit STARTUP_WARNING: lines that the UI can surface.

    Does not raise — a missing backend shouldn't prevent the agent process
    from starting. The UI shows the warning in its log pane so the user can
    fix it (e.g. run ``ollama serve``) without restarting the whole stack.
    """
    try:
        import httpx
    except ImportError:
        return
    try:
        if provider == "ollama":
            r = httpx.get(f"{api_base.rstrip('/')}/api/tags", timeout=3.0)
            if r.status_code != 200:
                print(
                    f"STARTUP_WARNING:Ollama at {api_base} returned HTTP {r.status_code}. "
                    f"Run 'ollama serve' in another terminal.",
                    flush=True,
                )
                return
            # Verify the requested model is pulled
            try:
                tags = r.json().get("models", [])
                names = {m.get("name", "").split(":")[0] for m in tags}
                wanted = model_name.split(":")[0]
                if wanted and wanted not in names:
                    print(
                        f"STARTUP_WARNING:Ollama is up but model '{model_name}' is not pulled. "
                        f"Run 'ollama pull {model_name}'.",
                        flush=True,
                    )
            except Exception:
                pass  # non-fatal; model list parse is best-effort
        elif provider == "openai":
            # Just verify the base URL responds; we can't auth-check without burning a request
            host = api_base.rstrip("/")
            r = httpx.get(host, timeout=3.0)
            if r.status_code >= 500:
                print(
                    f"STARTUP_WARNING:LLM endpoint {host} returned HTTP {r.status_code}.",
                    flush=True,
                )
    except httpx.ConnectError as e:
        print(
            f"STARTUP_WARNING:LLM backend not reachable at {api_base} ({e}). "
            f"For Ollama: run 'ollama serve' and 'ollama pull {model_name}' in another terminal.",
            flush=True,
        )
    except Exception as e:
        print(f"STARTUP_WARNING:LLM health check failed: {e}", flush=True)


async def main():
    """Main agent loop"""
    # All config flows through load_settings so env vars (e.g. from docker-compose)
    # override the JSON defaults — that's how containerised deployments point
    # the agent at `http://ollama:11434` without editing any files.
    from src.common.settings import load_settings
    settings = load_settings()

    provider = settings.provider.lower()
    api_base = settings.api_base
    model_name = settings.model_name
    system_prompt = settings.system_prompt

    # The settings default api_base is the Ollama URL. If the operator flipped
    # provider to openai but didn't set an explicit api_base, swap in the
    # OpenAI default so they don't get a confusing connection error.
    if provider == "openai" and api_base == "http://localhost:11434":
        api_base = "https://api.openai.com/v1"

    if provider == "openai":
        llm_client = OpenAIClient(
            model_name=model_name,
            api_key=settings.openai_api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=api_base,
            system_prompt=system_prompt,
        )
    else:
        llm_client = OllamaClient(
            model_name=model_name,
            host=api_base,
            system_prompt=system_prompt,
        )

    # Keep a plain dict around too so the rest of this function (which was
    # written against the old config-loading style) keeps working unchanged.
    agent_config = {
        "provider": provider,
        "api_base": api_base,
        "model_name": model_name,
        "system_prompt": system_prompt,
    }

    # Health-check the LLM so the user sees a clear warning in the UI log
    # instead of the agent silently hanging on the first request.
    _health_check_llm(provider, api_base, model_name)

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
                # Ollama can throw transient 500s during model reload — retry a
                # couple of times with a short sleep and a visible heartbeat so
                # the UI doesn't look like it's hung. OpenAI/Groq errors are
                # not transient so we skip retry there.
                if provider == "ollama":
                    import time as _time
                    for attempt in range(3):
                        response = llm_client.chat(messages, tools=tools)
                        if "error" not in response:
                            break
                        if attempt < 2:
                            print(
                                f"TOOL_EXECUTE:LLM error — retrying ({attempt + 1}/3) "
                                f"— {response.get('error', '')[:120]}",
                                flush=True,
                            )
                            _time.sleep(2)
                else:
                    response = llm_client.chat(messages, tools=tools)

                if "error" in response:
                    # Emit the actual LLM error so the UI can display it. The
                    # older code only broke out, leaving the UI to time out at
                    # 180s with a generic "Processing..." placeholder.
                    print(f"ERROR:{response['error']}", flush=True)
                    break

                message = response.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])

                if content:
                    print(f"AGENT_RESPONSE:{content}", flush=True)

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

                            # For search results, emit structured PAPER_CARD JSON
                            # so the UI can render clickable paper cards.
                            if name == "search_papers":
                                try:
                                    papers = json.loads(result_str)
                                    actual = [p for p in papers if not p.get("error")]
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
