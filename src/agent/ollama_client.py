import ollama
import json
from typing import List, Dict, Any, Optional

class OllamaClient:
    def __init__(self, model_name: str, host: str = "http://localhost:11434", system_prompt: str = ""):
        self.client = ollama.Client(host=host)
        self.model_name = model_name
        self.system_prompt = system_prompt
        # Ensure model is pulled? No, let's assume it's there or user pulls it.

    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Send a chat request to Ollama. 
        Supports native tool calling if the model/library supports it.
        """
        # Note: deepseek-r1 via ollama might not natively support 'tools' param in the standard way yet depending on version,
        # but modern ollama libs serve as a pass-through.
        # If tools are provided, we pass them.
        
        options = {}
        if self.system_prompt:
             # If system prompt is not already in messages, insert it? 
             # Or just trust the caller. Usually caller manages history.
             pass

        try:
            response = self.client.chat(
                model=self.model_name,
                messages=messages,
                tools=tools, # Pass tools definition (JSON schema)
                stream=False
            )
            return response
        except Exception as e:
            print(f"Error communicating with Ollama: {e}")
            return {"error": str(e)}

    def generate(self, prompt: str) -> str:
        """Simple generation."""
        response = self.client.generate(model=self.model_name, prompt=prompt)
        return response['response']
