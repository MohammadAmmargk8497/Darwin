"""
OpenAI API client for the Darwin agent.
Compatible with OpenAI, Azure OpenAI, OpenRouter, Together AI, and other OpenAI-compatible endpoints.
"""
from openai import OpenAI
from typing import List, Dict, Any, Optional
import json

class OpenAIClient:
    def __init__(
        self, 
        model_name: str, 
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        system_prompt: str = ""
    ):
        """
        Initialize OpenAI client.
        
        Args:
            model_name: Model to use (e.g., "gpt-4", "gpt-3.5-turbo")
            api_key: Your API key
            base_url: API endpoint (default: OpenAI, can use OpenRouter, Together, etc.)
            system_prompt: System prompt to prepend to conversations
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model_name = model_name
        self.system_prompt = system_prompt

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Send a chat request with optional tool calling support.
        Returns response in Ollama-compatible format for agent compatibility.
        """
        # Prepare messages - ensure system prompt if needed
        chat_messages = messages.copy()
        
        try:
            # Build request params
            params = {
                "model": self.model_name,
                "messages": chat_messages,
            }
            
            # Add tools if provided
            if tools:
                # Convert from Ollama format to OpenAI format if needed
                params["tools"] = tools
                params["tool_choice"] = "auto"
            
            print(f"Sending request to {self.model_name}...")
            completion = self.client.chat.completions.create(**params)
            
            # Convert OpenAI response to Ollama-compatible format
            response_message = completion.choices[0].message
            
            result = {
                "message": {
                    "role": response_message.role,
                    "content": response_message.content or "",
                }
            }
            
            # Handle tool calls if present
            if response_message.tool_calls:
                result["message"]["tool_calls"] = []
                for tc in response_message.tool_calls:
                    # Keep arguments as string for API compatibility (Groq requires this)
                    # We'll parse them when we actually call the tool
                    result["message"]["tool_calls"].append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments  # Keep as JSON string
                        }
                    })
            
            return result
            
        except Exception as e:
            print(f"Error communicating with OpenAI API: {e}")
            return {"error": str(e)}

    def generate(self, prompt: str) -> str:
        """Simple text generation without chat format."""
        try:
            completion = self.client.completions.create(
                model=self.model_name,
                prompt=prompt
            )
            return completion.choices[0].text
        except Exception as e:
            return f"Error: {e}"
