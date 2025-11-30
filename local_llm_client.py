# local_llm_client.py

import requests
from typing import Optional


class LocalLLMClient:
    """
    Thin wrapper around a local LLM server (Ollama).

    Assumes:
      - Ollama is running at http://localhost:11434
      - A model name like "llama3.1" or "codellama" is available.

    Usage:
      client = LocalLLMClient()
      text = client.generate("llama3.1", prompt)
    """

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")

    def generate(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Call the local model and return the generated text.

        For Ollama, the endpoint is POST /api/generate with:
          {
            "model": "llama3.1",
            "prompt": "...",
            "options": {...}
          }
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        resp = requests.post(url, json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        # Ollama returns { "model": ..., "created_at": ..., "response": "..." , ... }
        return data.get("response", "").strip()


# Convenience singleton for scripts
default_client = LocalLLMClient()


def call_llm(model: str, prompt: str, temperature: float = 0.2, max_tokens: Optional[int] = None) -> str:
    return default_client.generate(model=model, prompt=prompt, temperature=temperature, max_tokens=max_tokens)
