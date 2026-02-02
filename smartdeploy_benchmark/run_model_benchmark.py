#!/usr/bin/env python3
import argparse
import json
import os
import time
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# This script benchmarks SmartDeploy's "intent-like" JSON generation step
# across multiple model backends. It is intentionally provider-agnostic:
# - Ollama (already used in your project) works out of the box.
# - Optional: OpenAI-compatible endpoints (OpenAI, vLLM OpenAI server, etc.)
#
# It measures:
# - latency (s)
# - JSON parse success
# - optional schema/rules success if you plug your validators

@dataclass
class RunResult:
    model: str
    prompt_id: str
    run_idx: int
    latency_s: float
    ok_json: bool
    ok_schema: Optional[bool]
    raw_len: int
    error: Optional[str]

def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def load_prompts(path: str) -> List[Dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, obj: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ---------------------------
# Backend abstraction
# ---------------------------

class BackendError(RuntimeError):
    pass

class BaseBackend:
    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        raise NotImplementedError

class OllamaBackend(BaseBackend):
    def __init__(self, base_url: str, model: str, temperature: float, timeout_s: int):
        # Reuse your existing engine class if available.
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

        # Lazy import to keep this script standalone.
        import requests  # type: ignore
        self._requests = requests
        import re, json as _json
        self._re = re
        self._json = _json

    def _extract_json(self, text: str) -> str:
        # 1) ```json ... ```
        m = self._re.search(r"```json\\s*(\\{.*\\})\\s*```", text, self._re.DOTALL)
        if m:
            return m.group(1)
        # 2) first {...}
        m = self._re.search(r"(\\{.*\\})", text, self._re.DOTALL)
        if m:
            return m.group(1)
        return text

    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": self.temperature},
            "messages": messages,
        }
        try:
            r = self._requests.post(url, json=payload, timeout=self.timeout_s)
        except Exception as e:
            raise BackendError(f"Ollama request failed: {e}") from e
        if r.status_code != 200:
            raise BackendError(f"Ollama HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        content = (data.get("message") or {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise BackendError("Ollama returned empty content")
        cleaned = self._extract_json(content)
        try:
            return self._json.loads(cleaned)
        except Exception as e:
            raise BackendError(f"JSON parse failed. Raw content:\n{content}") from e

# Optional: OpenAI-compatible backend (OpenAI, vLLM OpenAI server, etc.)
class OpenAICompatBackend(BaseBackend):
    def __init__(self, base_url: str, api_key: str, model: str, temperature: float, timeout_s: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

        import requests  # type: ignore
        self._requests = requests
        import re, json as _json
        self._re = re
        self._json = _json

    def _extract_json(self, text: str) -> str:
        m = self._re.search(r"```json\\s*(\\{.*\\})\\s*```", text, self._re.DOTALL)
        if m:
            return m.group(1)
        m = self._re.search(r"(\\{.*\\})", text, self._re.DOTALL)
        if m:
            return m.group(1)
        return text

    def chat_json(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        # OpenAI-compatible: POST /v1/chat/completions
        url = f"{self.base_url}/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": messages,
        }
        try:
            r = self._requests.post(url, headers=headers, json=payload, timeout=self.timeout_s)
        except Exception as e:
            raise BackendError(f"OpenAI-compatible request failed: {e}") from e
        if r.status_code != 200:
            raise BackendError(f"HTTP {r.status_code}: {r.text[:500]}")
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        cleaned = self._extract_json(content)
        try:
            return self._json.loads(cleaned)
        except Exception as e:
            raise BackendError(f"JSON parse failed. Raw content:\n{content}") from e

def build_backend(args) -> BaseBackend:
    if args.backend == "ollama":
        return OllamaBackend(args.base_url, args.model, args.temperature, args.timeout_s)
    if args.backend == "openai_compat":
        api_key = args.api_key or os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise SystemExit("Missing API key (use --api-key or set OPENAI_API_KEY).")
        return OpenAICompatBackend(args.base_url, api_key, args.model, args.temperature, args.timeout_s)
    raise SystemExit(f"Unknown backend: {args.backend}")

# ---------------------------
# Main benchmark loop
# ---------------------------

SYSTEM_PROMPT = (
    "You are a senior DevOps assistant. "
    "Return ONLY valid JSON. No markdown. No explanations."
)

def run_once(backend: BaseBackend, prompt: str) -> Tuple[Optional[Dict[str, Any]], str]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    out = backend.chat_json(messages)
    return out, ""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["ollama", "openai_compat"], default="ollama")
    p.add_argument("--base-url", default=os.getenv("SMARTDEPLOY_LLM_BASE_URL", "http://127.0.0.1:11434"))
    p.add_argument("--api-key", default=os.getenv("SMARTDEPLOY_LLM_API_KEY", ""))
    p.add_argument("--models", nargs="+", required=True, help="List of model names to benchmark")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--timeout-s", type=int, default=600)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--prompts", default="benchmark_prompts.json")
    p.add_argument("--outdir", default="benchmark_output")
    args = p.parse_args()

    prompts = load_prompts(args.prompts)
    all_results: List[RunResult] = []
    raw_outputs: Dict[str, Any] = {"generated_at": now_ts(), "backend": args.backend, "base_url": args.base_url, "models": args.models, "runs": args.runs, "results": []}

    for model in args.models:
        for pr in prompts:
            pid = pr["id"]
            text = pr["prompt"]

            for i in range(args.runs):
                args.model = model  # used by build_backend()
                backend = build_backend(args)

                t0 = time.perf_counter()
                ok_json = True
                ok_schema = None
                err = None
                out_obj = None
                try:
                    out_obj, _ = run_once(backend, text)
                except Exception as e:
                    ok_json = False
                    err = str(e)
                latency = time.perf_counter() - t0

                raw_len = len(json.dumps(out_obj, ensure_ascii=False)) if out_obj is not None else 0
                rr = RunResult(model=model, prompt_id=pid, run_idx=i, latency_s=latency, ok_json=ok_json, ok_schema=ok_schema, raw_len=raw_len, error=err)
                all_results.append(rr)

                raw_outputs["results"].append({
                    "model": model,
                    "prompt_id": pid,
                    "run_idx": i,
                    "latency_s": latency,
                    "ok_json": ok_json,
                    "ok_schema": ok_schema,
                    "raw_len": raw_len,
                    "error": err,
                    "output": out_obj,
                })

                print(f"[{model}] {pid} run {i+1}/{args.runs}: latency={latency:.2f}s ok_json={ok_json}")

    # Aggregate
    summary: Dict[str, Any] = {"generated_at": now_ts(), "by_model": {}}
    for model in args.models:
        mr = [r for r in all_results if r.model == model]
        lat_ok = [r.latency_s for r in mr if r.ok_json]
        summary["by_model"][model] = {
            "runs_total": len(mr),
            "json_success_rate": (sum(1 for r in mr if r.ok_json) / len(mr)) if mr else 0.0,
            "latency_avg_s": statistics.mean(lat_ok) if lat_ok else None,
            "latency_p50_s": statistics.median(lat_ok) if lat_ok else None,
            "latency_p95_s": (sorted(lat_ok)[int(0.95 * (len(lat_ok)-1))] if len(lat_ok) >= 2 else (lat_ok[0] if lat_ok else None)),
        }

    os.makedirs(args.outdir, exist_ok=True)
    save_json(os.path.join(args.outdir, "benchmark_raw.json"), raw_outputs)
    save_json(os.path.join(args.outdir, "benchmark_summary.json"), summary)
    print(f"\nSaved:\n- {os.path.join(args.outdir,'benchmark_raw.json')}\n- {os.path.join(args.outdir,'benchmark_summary.json')}")

if __name__ == "__main__":
    main()
