import json
import time
import statistics
import hashlib
from pathlib import Path
from typing import Any, Dict, List

from src.engine.pipeline_runner import run_pipeline, PipelineConfig


TOP3_MODELS = [
    "mistral", 
    "qwen2.5:latest", 
    "llama3.1:8b"
]

N_RUNS = 5

DATA_INFRA = Path("data/infra.json")
OUT_DIR = Path("data/bench_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

TESTS = [
    {
        "id": "T1_valid_simple",
        "text": "Ajoute un PC02 sur Site1 avec IP 192.168.10.20 dans VLAN10",
        "expect_status": {"OK", "NEED_USER_INPUT"},  # valid pipeline outcomes
    },
    {
        "id": "T2_valid_fw_rules",
        "text": (
            "Sur Site1 VLAN10 réseau 192.168.10.0/24, ajoute PC02 IP 192.168.10.20. "
            "Ajoute une règle firewall allow tcp/80 depuis 192.168.10.0/24 vers 0.0.0.0/0 "
            "et une règle allow tcp/443 depuis 192.168.10.0/24 vers 0.0.0.0/0."
        ),
        "expect_status": {"OK", "NEED_USER_INPUT"},
    },
    {
        "id": "T3_invalid_ip_outside_prefix",
        "text": "Ajoute un PC02 sur Site1 avec IP 192.168.20.20 dans VLAN10",
        "expect_status": {"INVALID_INTENT", "INVALID_INFRA", "NEED_USER_INPUT", "ERROR"},
    },
]


def load_infra_current() -> Dict[str, Any]:
    if not DATA_INFRA.exists():
        raise FileNotFoundError(f"Missing {DATA_INFRA}")
    return json.loads(DATA_INFRA.read_text(encoding="utf-8"))


def stable_hash(obj: Any) -> str:
    dumped = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def time_score(avg_s: float) -> int:
    # Ajuste selon ton CDC/UI (à adapter)
    if avg_s <= 5:
        return 10
    if avg_s <= 10:
        return 7
    if avg_s <= 20:
        return 4
    return 0


def stability_score(unique_outputs: int) -> int:
    if unique_outputs == 1:
        return 10
    if unique_outputs == 2:
        return 7
    if unique_outputs == 3:
        return 4
    return 0


def strict_network_score(result_obj: Dict[str, Any], test_id: str) -> (int, List[str]):
    """
    Score strict basé sur les sorties pipeline déterministes :
    - statut OK/NEED_USER_INPUT attendu pour valid cases
    - candidate contient PC02 + IP (pour T1/T2)
    - invalid case doit être détecté (pas OK silencieux)
    """
    issues: List[str] = []
    score = 0

    status = result_obj.get("status")
    intent_result = result_obj.get("intent_result") or {}
    patch = result_obj.get("patch") or {}
    candidate = result_obj.get("infra_candidate") or {}
    infra_issues = result_obj.get("infra_issues") or []
    error = result_obj.get("error")

    # (20) pipeline output exists
    score += 10
    if status:
        score += 10
    else:
        issues.append("Missing pipeline status.")

    # (20) intent quality: must have VALID_* in intent_result if pipeline OK
    intent_status = intent_result.get("status")
    if status in ("OK", "NEED_USER_INPUT"):
        if intent_status in ("VALID_INTENT", "VALID_INTENT_AFTER_REPAIR"):
            score += 20
        else:
            issues.append(f"Pipeline OK but intent_status={intent_status}.")
    else:
        # invalid case: we accept non-valid intent
        score += 10

    # (20) patch correctness
    if isinstance(patch, dict) and isinstance(patch.get("ops"), list) and patch["ops"]:
        score += 20
    else:
        issues.append("Missing or empty patch ops.")

    # (30) candidate checks for valid tests
    if test_id in ("T1_valid_simple", "T2_valid_fw_rules") and isinstance(candidate, dict):
        devices = candidate.get("devices") or []
        ips = candidate.get("ips") or []

        has_pc02 = any(isinstance(d, dict) and d.get("name") == "PC02" for d in devices)
        if has_pc02:
            score += 10
        else:
            issues.append("Candidate missing device PC02.")

        has_ip = any(
            isinstance(ip, dict)
            and ip.get("device") == "PC02"
            and "192.168.10.20" in (ip.get("address") or "")
            for ip in ips
        )
        if has_ip:
            score += 10
        else:
            issues.append("Candidate missing IP 192.168.10.20 for PC02.")

        # validation: infra_issues should be empty for valid tests
        if not infra_issues:
            score += 10
        else:
            issues.append(f"Candidate infra_issues not empty: {infra_issues[:2]}")
    else:
        # invalid test: we want NOT OK silently
        if status in ("OK",):
            issues.append("Invalid test returned OK (should be flagged).")
        else:
            score += 20  # credited for not silently accepting invalid case

        if error:
            issues.append(f"Pipeline error: {error.get('type')}: {error.get('message')}")

    return score, issues


def run_one_model_one_test(model: str, test: Dict[str, Any], infra_current: Dict[str, Any]) -> Dict[str, Any]:
    times: List[float] = []
    hashes: List[str] = []
    reps: List[Dict[str, Any]] = []

    cfg = PipelineConfig(
        known_sites=["Site1", "Site2"],
        llm_model=model,
        output_dir="data/bench_output/tmp",
        save_intent=False,
        save_patch=False,
        save_candidate=False,
    )

    for _ in range(N_RUNS):
        start = time.perf_counter()
        res = run_pipeline(test["text"], infra_current, cfg)
        elapsed = time.perf_counter() - start

        # convert dataclass -> dict
        res_dict = res.__dict__
        times.append(elapsed)
        hashes.append(stable_hash(res_dict))
        reps.append(res_dict)

    avg_t = statistics.mean(times)
    p95_t = statistics.quantiles(times, n=20)[18] if len(times) >= 5 else max(times)
    unique = len(set(hashes))

    # pick representative = most common output hash
    most_common_hash = max(set(hashes), key=hashes.count)
    representative = next(r for r, h in zip(reps, hashes) if h == most_common_hash)

    strict_score, strict_issues = strict_network_score(representative, test["id"])

    total = strict_score + time_score(avg_t) + stability_score(unique)

    return {
        "model": model,
        "test_id": test["id"],
        "avg_time_s": avg_t,
        "p95_time_s": p95_t,
        "stability_unique_outputs": unique,
        "scores": {
            "strict_90": strict_score,     # strict_network_score returns up to ~90
            "time_10": time_score(avg_t),
            "stability_10": stability_score(unique),
            "total_110": total,
        },
        "issues": strict_issues,
        "representative_output": representative,
    }


def main():
    infra_current = load_infra_current()
    results = []

    for model in TOP3_MODELS:
        for test in TESTS:
            r = run_one_model_one_test(model, test, infra_current)
            results.append(r)

            print(
                f"{r['model']} | {r['test_id']} | "
                f"total={r['scores']['total_110']}/110 | "
                f"avg={r['avg_time_s']:.2f}s p95={r['p95_time_s']:.2f}s | "
                f"stable={r['stability_unique_outputs']}"
            )
            if r["issues"]:
                print("  issues:", "; ".join(r["issues"][:5]) + (" ..." if len(r["issues"]) > 5 else ""))

    out = OUT_DIR / "benchmark_strict_network_pipeline.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {out}")


if __name__ == "__main__":
    main()
