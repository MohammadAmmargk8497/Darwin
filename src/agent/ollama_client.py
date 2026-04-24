import ollama
from typing import Any, Dict, List, Optional


class OllamaClient:
    def __init__(
        self,
        model_name: str,
        host: str = "http://localhost:11434",
        system_prompt: str = "",
        num_ctx: int = 8192,
    ):
        self.client = ollama.Client(host=host)
        self.model_name = model_name
        self.system_prompt = system_prompt
        # Pin the inference context. Models like qwen2.5 default to 32K,
        # which balloons KV cache size and cold-start latency. We cap it at
        # a size that comfortably holds our system prompt + tool defs + a
        # multi-turn conversation with paper abstracts.
        self.num_ctx = int(num_ctx)

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Send a chat request to Ollama with native tool-calling support."""
        try:
            response = self.client.chat(
                model=self.model_name,
                messages=messages,
                tools=tools,
                options={"num_ctx": self.num_ctx},
                stream=False,
            )
            return response
        except Exception as e:
            print(f"Error communicating with Ollama: {e}")
            return {"error": str(e)}

    def generate(self, prompt: str) -> str:
        """Simple generation."""
        response = self.client.generate(
            model=self.model_name,
            prompt=prompt,
            options={"num_ctx": self.num_ctx},
        )
        return response["response"]
