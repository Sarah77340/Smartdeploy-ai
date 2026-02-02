import time
import statistics
from src.engine.llm.factory import get_llm
from src.engine.llm.ollama_openai import LLMError

MODELS = [
    "mistral",
    "llama3.1:8b",
    "qwen2.5:latest",
    "granite3.2-vision:2b",
    "codestral:22b",
    "codellama:7b",
    "deepseek-coder:1.3b",
    "starcoder2:3b",
]

TESTS = [
    {"name": "valid_simple", "text": "VLAN10 réseau 192.168.10.0/24, FW01=192.168.10.1, DEB01=192.168.10.11", "error": False},
    {"name": "valid_fw_rules", "text": "Même réseau, deny all par défaut, autoriser DEB01 HTTP/HTTPS", "error": False},
    {"name": "invalid_ip", "text": "Réseau 192.168.10.0/24, FW01=192.168.20.1", "error": True}
]

SYSTEM_PROMPT = "Return ONLY valid JSON. No explanations."


def score_output(out, expect_error):
    """
    Very simple scoring MVP. You can refine later with schema validation + rules.
    """
    score = 0

    # JSON + structure
    if isinstance(out, dict):
        score += 15
    if isinstance(out, dict) and "requested_changes" in out:
        score += 15

    # Error handling expectation (case 3)
    if expect_error:
        # We expect the model to flag missing info or inconsistency
        if isinstance(out, dict) and out.get("missing_information"):
            score += 15
    else:
        score += 20

    # Firewall mention heuristic
    if isinstance(out, dict) and ("firewall" in str(out).lower()):
        score += 10

    # Questions
    if isinstance(out, dict) and out.get("missing_information"):
        score += 5

    return score


def time_bonus(avg_time_s: float) -> int:
    if avg_time_s < 1.5:
        return 15
    if avg_time_s < 3.0:
        return 10
    if avg_time_s < 6.0:
        return 5
    return 0


def warmup(llm):
    # 1 quick call to load model
    _ = llm.chat_json([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "{\"warmup\": true}"}
    ])


def run_model(model: str):
    llm = get_llm(model=model)

    # warmup to avoid cold start bias
    try:
        warmup(llm)
    except Exception:
        # warmup failure shouldn't crash benchmark; we'll measure real tests anyway
        pass

    times = []
    total_score = 0
    failures = 0

    for t in TESTS:
        start = time.perf_counter()
        try:
            out = llm.chat_json([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": t["text"]}
            ])
        except LLMError:
            out = None
            failures += 1
        finally:
            times.append(time.perf_counter() - start)

        if out is not None:
            total_score += score_output(out, t["error"])

    avg_time = statistics.mean(times)
    total_score += time_bonus(avg_time)

    return {
        "model": model,
        "score": total_score,
        "avg_time_s": avg_time,
        "failures": failures,
        "times": times
    }


if __name__ == "__main__":
    results = []
    for m in MODELS:
        r = run_model(m)
        results.append(r)
        print(f"{r['model']}: score={r['score']}/100, avg_time={r['avg_time_s']:.2f}s, failures={r['failures']}")

    # Optional: sort by score then time
    results.sort(key=lambda x: (-x["score"], x["avg_time_s"]))
    print("\n=== RANKING ===")
    for r in results:
        print(f"{r['model']}: score={r['score']}/100, avg_time={r['avg_time_s']:.2f}s, failures={r['failures']}")
