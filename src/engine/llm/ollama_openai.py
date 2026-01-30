import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import re


class LLMError(RuntimeError):
    pass

@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "mistral"
    temperature: float = 0.0
    timeout_s: int = 600 #120

def _extract_json(text: str) -> str:
    """
    Extract JSON object from text, even if wrapped in markdown or extra text.
    """
    # Cas 1 : bloc ```json ... ```
    code_block = re.search(r"```json\s*(\{.*\})\s*```", text, re.DOTALL)
    if code_block:
        return code_block.group(1)

    # Cas 2 : premier objet JSON trouvé
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return brace_match.group(0)

    return text  # fallback (sera invalide)

class OllamaProvider:
    """
    Calls Ollama's native chat API: POST /api/chat
    Returns parsed JSON only (dict). Any non-JSON output is an error.
    """

    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg

    
    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.cfg.model,
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
            },
            "messages": messages,
        }

        try:
            r = requests.post(url, json=payload, timeout=self.cfg.timeout_s)
        except requests.RequestException as e:
            raise LLMError(f"Failed to call Ollama at {url}: {e}") from e

        if r.status_code != 200:
            raise LLMError(f"Ollama error {r.status_code}: {r.text}")

        data = r.json()
        content = (data.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMError(f"Ollama returned empty content: {data}")

        # to extract JSON even if wrapped in markdown
        cleaned = _extract_json(content)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMError(
                "Model did not return valid JSON. "
                f"Raw content was:\n{content}"
            ) from e

    


