import json
import time
import statistics
import hashlib
import ipaddress
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from src.engine.llm.factory import get_llm

# On réutilise ton pipeline si dispo
from src.engine.pipeline import parse_intent, generate_infra_candidate


# -----------------------------
# Config benchmark
# -----------------------------
TOP3_MODELS = [
    "mistral",
    "qwen2.5:latest",
    "llama3.1:8b",
]

N_RUNS = 5  # stabilité
DATA_INFRA = Path("data/infra.json")  # état initial (courant)
OUT_DIR = Path("data/bench_output")
OUT_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT_INTENT = (
    "Return ONLY valid JSON. No explanations. "
    "Follow the intent schema: scope/requested_changes/assumptions/missing_information/confidence."
)


# -----------------------------
# 3 tests (réseau)
# -----------------------------
TESTS = [
    {
        "id": "T1_valid_simple",
        "text": "Sur Site1, VLAN10 réseau 192.168.10.0/24. Ajoute PC02 avec IP 192.168.10.20 dans VLAN10.",
        "expect_invalid": False,
    },
    {
        "id": "T2_valid_fw",
        "text": "Sur Site1 VLAN10 réseau 192.168.10.0/24. Ajoute PC02 IP 192.168.10.20. "
                "Ajoute une règle firewall ‘deny_all’ (action deny, source 0.0.0.0/0, destination 0.0.0.0/0, service tcp/0-65535) puis ajoute deux règles allow tcp/80 et allow tcp/443 sortant",
        "expect_invalid": False,
    },
    {
        "id": "T3_invalid_ip_outside_prefix",
        "text": "Sur Site1 VLAN10 réseau 192.168.10.0/24. Ajoute PC02 avec IP 192.168.20.20 dans VLAN10.",
        "expect_invalid": True,
    },
]

"""
    {
        "id": "T2_valid_fw",
        "text": "Sur Site1 VLAN10 réseau 192.168.10.0/24. Ajoute PC02 IP 192.168.10.20. "
                "Applique deny all par défaut et autorise HTTP/HTTPS sortant.",
        "expect_invalid": False,
    },
"""

TESTS0 = [    
    {
        "id": "Test basic 1",
        "text": "Ajoute un PC02 sur Site1 avec IP 192.168.10.20 dans VLAN10",
        "expect_invalid": True,
    },
]


# -----------------------------
# Helpers
# -----------------------------
def load_infra_current() -> Dict[str, Any]:
    if not DATA_INFRA.exists():
        raise FileNotFoundError(f"Missing {DATA_INFRA}. Expected your base infra state file.")
    return json.loads(DATA_INFRA.read_text(encoding="utf-8"))


def canonical_hash(obj: Any) -> str:
    """
    Hash stable representation of JSON (sorted keys).
    """
    dumped = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def extract_prefixes_by_site(infra: Dict[str, Any]) -> Dict[str, List[ipaddress.IPv4Network]]:
    by_site: Dict[str, List[ipaddress.IPv4Network]] = {}
    for p in infra.get("prefixes", []):
        site = p.get("site") or "default"
        try:
            net = ipaddress.ip_network(p["prefix"], strict=False)
        except Exception:
            continue
        by_site.setdefault(site, []).append(net)
    return by_site


def ip_in_site_prefixes(ip_str: str, site: str, prefixes_by_site: Dict[str, List[ipaddress.IPv4Network]]) -> bool:
    ip_only = ip_str.split("/")[0].strip()
    try:
        ip_obj = ipaddress.ip_address(ip_only)
    except Exception:
        return False

    nets = prefixes_by_site.get(site) or []
    return any(ip_obj in n for n in nets)


def intent_get_sites(intent: Dict[str, Any]) -> List[str]:
    scope = intent.get("scope") or {}
    sites = scope.get("sites") or []
    return [s for s in sites if isinstance(s, str) and s.strip()]


def intent_iter_changes(intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    rc = intent.get("requested_changes") or []
    return [x for x in rc if isinstance(x, dict)]


def find_add_ip_actions(intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ch in intent_iter_changes(intent):
        if (ch.get("type") or "").lower() == "add_ip":
            out.append(ch)
    return out


def find_add_vlan_actions(intent: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ch in intent_iter_changes(intent):
        if (ch.get("type") or "").lower() == "add_vlan":
            out.append(ch)
    return out


# -----------------------------
# Strict deterministic checks
# -----------------------------
def strict_network_checks(
    intent_result: Dict[str, Any],
    infra_current: Dict[str, Any],
    expect_invalid: bool,
) -> Tuple[int, List[str]]:
    """
    Returns (score_points, issues[])
    Score here is out of 60 (network+structure strict).
    We'll add stability+time later.
    """
    issues: List[str] = []
    score = 0

    # 1) Status correctness
    status = intent_result.get("status")
    intent = intent_result.get("intent") if isinstance(intent_result.get("intent"), dict) else intent_result

    # score: pipeline returned a structured object
    if isinstance(intent, dict):
        score += 10
    else:
        issues.append("Intent is not a dict.")
        return score, issues

    # 2) Expected invalid vs valid
    # We accept that invalid case could return INVALID_INTENT or VALID_* but with missing_information/questions.
    missing_info = intent_result.get("missing_information") or intent.get("missing_information") or []
    questions = intent_result.get("questions") or []
    has_questions = bool(missing_info) or bool(questions)

    if expect_invalid:
        # Need to show the model/pipeline noticed something wrong
        if status in ("INVALID_INTENT", "INVALID_INTENT_AFTER_REPAIR"):
            score += 10
        elif has_questions:
            score += 10
        else:
            issues.append("Expected invalid case but got no INVALID status and no questions/missing_information.")
    else:
        # valid
        if status in ("VALID_INTENT", "VALID_INTENT_AFTER_REPAIR") or status is None:
            score += 10
        else:
            issues.append(f"Expected valid case but got status={status}.")

    # 3) Schema-ish fields present
    if "requested_changes" in intent and isinstance(intent["requested_changes"], list):
        score += 10
    else:
        issues.append("requested_changes missing or not a list.")

    # 4) VLAN site coherence (if add_vlan appears)
    add_vlans = find_add_vlan_actions(intent)
    if add_vlans:
        ok_vlan_site = True
        for ch in add_vlans:
            payload = ch.get("payload") or {}
            if not isinstance(payload, dict):
                ok_vlan_site = False
                continue
            if not payload.get("site"):
                ok_vlan_site = False
        if ok_vlan_site:
            score += 10
        else:
            issues.append("add_vlan action(s) missing payload.site.")
    else:
        # not required for every prompt, but your tests mention VLAN
        issues.append("No add_vlan action found (might be OK if VLAN already exists).")

    # 5) IP ∈ prefix (STRICT)
    prefixes_by_site = extract_prefixes_by_site(infra_current)
    sites = intent_get_sites(intent) or ["Site1"]  # fallback (your tests always reference Site1)
    site = sites[0]

    add_ips = find_add_ip_actions(intent)
    if add_ips:
        ok_all = True
        for ch in add_ips:
            payload = ch.get("payload") or {}
            addr = (payload.get("address") or "").strip()
            if not addr:
                ok_all = False
                continue
            if not ip_in_site_prefixes(addr, site, prefixes_by_site):
                ok_all = False
        if expect_invalid:
            # invalid test expects IP outside, so we want NOT ok
            if not ok_all:
                score += 10
            else:
                issues.append("Expected IP outside prefix, but intent IP appears within known prefixes.")
        else:
            if ok_all:
                score += 10
            else:
                issues.append("IP not in site prefixes (or missing address) for a valid case.")
    else:
        issues.append("No add_ip action found.")

    return score, issues


def build_infra_candidate_and_check(
    intent_result: Dict[str, Any],
    infra_current: Dict[str, Any],
    expect_invalid: bool,
    model: str
) -> Tuple[int, List[str]]:
    """
    Take intent (validated or not), try to generate infra_candidate via your existing function.
    Score out of 20 here.
    """
    issues: List[str] = []
    score = 0

    intent = intent_result.get("intent") if isinstance(intent_result.get("intent"), dict) else intent_result
    status = intent_result.get("status")

    if expect_invalid and status in ("INVALID_INTENT", "INVALID_INTENT_AFTER_REPAIR"):
        # We don't require candidate generation if intent is invalid; give partial credit.
        return 10, ["Intent invalid as expected; candidate generation skipped."]

    # Try generate candidate
    candidate = generate_infra_candidate(intent, infra_current, model=model)
    
    #try:
        #candidate = generate_infra_candidate(intent_result, infra_current, model=model)  # depending on your signature
    #except TypeError:
        # your signature might be generate_infra_candidate(intent, infra_current)
        #candidate = generate_infra_candidate(intent, infra_current, model=model)
    #except Exception as e:
    #    return 0, [f"Failed to generate infra_candidate: {e}"]
    
    

    # Basic sanity checks on candidate for valid tests
    if not isinstance(candidate, dict):
        return 0, ["infra_candidate is not a dict."]

    # Check PC02 created for valid tests (T1/T2)
    if not expect_invalid:
        devices = candidate.get("devices") or []
        has_pc02 = any(isinstance(d, dict) and (d.get("name") == "PC02") for d in devices)
        if has_pc02:
            score += 10
        else:
            issues.append("infra_candidate missing device PC02.")

        ips = candidate.get("ips") or []
        has_ip = any(isinstance(ip, dict) and (ip.get("device") == "PC02") and ("192.168.10.20" in (ip.get("address") or "")) for ip in ips)
        if has_ip:
            score += 10
        else:
            issues.append("infra_candidate missing IP 192.168.10.20 for PC02.")
    else:
        # invalid case: we accept no candidate or partial; if candidate exists, it should not silently accept wrong IP
        score += 10

    return score, issues


# -----------------------------
# Running one model on one test (multiple runs)
# -----------------------------
def run_one_model_one_test(model: str, test: Dict[str, Any], infra_current: Dict[str, Any]) -> Dict[str, Any]:
    times: List[float] = []
    hashes: List[str] = []
    run_details: List[Dict[str, Any]] = []

    known_sites = ["Site1", "Site2"]

    for i in range(N_RUNS):
        start = time.perf_counter()
        # IMPORTANT: ensure model is selected
        llm = get_llm(model=model)

        # parse_intent uses your pipeline (and should use get_llm internally).
        # If your pipeline takes an llm instance, adapt here.
        
        try:
            result = parse_intent(
                test["text"],
                known_sites=known_sites,
                model=model
            )
        except Exception as e:
            result = {
                "status": "INVALID_INTENT",
                "intent": None,
                "issues": [{"code": "SCHEMA_ERROR", "message": str(e)}],
                "questions": [],
            }

        elapsed = time.perf_counter() - start

        times.append(elapsed)

        # hash for stability
        h = canonical_hash(result)
        hashes.append(h)

        run_details.append({
            "run": i + 1,
            "time_s": elapsed,
            "hash": h,
            "result": result,
        })

    # Stability score: how many unique outputs
    unique_hashes = sorted(set(hashes))
    stability_unique = len(unique_hashes)

    # Compute strict scores using best run (or the most common run)
    # We'll pick the most frequent hash (mode)
    most_common_hash = max(set(hashes), key=hashes.count)
    representative = next(d["result"] for d in run_details if d["hash"] == most_common_hash)

    strict_score_60, strict_issues = strict_network_checks(
        representative,
        infra_current=infra_current,
        expect_invalid=test["expect_invalid"]
    )

    candidate_score_20, candidate_issues = build_infra_candidate_and_check(
        representative,
        infra_current=infra_current,
        expect_invalid=test["expect_invalid"],
        model=model
    )

    # Time score out of 10: based on avg
    avg_t = statistics.mean(times)
    p95_t = statistics.quantiles(times, n=20)[18] if len(times) >= 5 else max(times)

    # You can adjust thresholds; here is UI-oriented
    if avg_t <= 5:
        time_score = 10
    elif avg_t <= 10:
        time_score = 7
    elif avg_t <= 20:
        time_score = 4
    else:
        time_score = 0

    # Stability score out of 10: fewer unique hashes is better
    # 1 unique => 10, 2 unique => 7, 3 unique => 4, >=4 => 0
    if stability_unique == 1:
        stability_score = 10
    elif stability_unique == 2:
        stability_score = 7
    elif stability_unique == 3:
        stability_score = 4
    else:
        stability_score = 0

    total = strict_score_60 + candidate_score_20 + time_score + stability_score  # out of 100

    return {
        "model": model,
        "test_id": test["id"],
        "avg_time_s": avg_t,
        "p95_time_s": p95_t,
        "stability_unique_outputs": stability_unique,
        "scores": {
            "strict_60": strict_score_60,
            "candidate_20": candidate_score_20,
            "time_10": time_score,
            "stability_10": stability_score,
            "total_100": total,
        },
        "issues": strict_issues + candidate_issues,
        "representative_hash": most_common_hash,
        "unique_hashes": unique_hashes,
        "runs": [
            {"run": d["run"], "time_s": d["time_s"], "hash": d["hash"]}
            for d in run_details
        ],
        # Store one full representative output for auditing
        "representative_output": representative,
    }


def main():
    infra_current = load_infra_current()

    results: List[Dict[str, Any]] = []
    for model in TOP3_MODELS:
        for test in TESTS:
            r = run_one_model_one_test(model, test, infra_current)
            results.append(r)

            print(
                f"{r['model']} | {r['test_id']} | "
                f"total={r['scores']['total_100']}/100 | "
                f"avg={r['avg_time_s']:.2f}s p95={r['p95_time_s']:.2f}s | "
                f"stable={r['stability_unique_outputs']} unique"
            )

            if r["issues"]:
                print("  issues:", "; ".join(r["issues"][:5]) + (" ..." if len(r["issues"]) > 5 else ""))

    # Aggregate per model across tests
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_model.setdefault(r["model"], []).append(r)

    summary = []
    for model, rows in by_model.items():
        total = sum(x["scores"]["total_100"] for x in rows)
        avg_time = statistics.mean(x["avg_time_s"] for x in rows)
        p95_time = max(x["p95_time_s"] for x in rows)
        summary.append({
            "model": model,
            "total_score_sum": total,
            "avg_time_s": avg_time,
            "worst_p95_time_s": p95_time,
        })

    summary.sort(key=lambda x: (-x["total_score_sum"], x["avg_time_s"]))

    print("\n=== STRICT NETWORK BENCHMARK RANKING ===")
    for s in summary:
        print(
            f"{s['model']}: total_sum={s['total_score_sum']} "
            f"(3 tests) | avg_time={s['avg_time_s']:.2f}s | worst_p95={s['worst_p95_time_s']:.2f}s"
        )

    # Write outputs for sharing
    out_path = OUT_DIR / "benchmark_strict_network_results.json"
    out_path.write_text(json.dumps({"summary": summary, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
