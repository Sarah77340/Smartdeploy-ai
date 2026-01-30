import json
from src.engine.pipeline import parse_intent, generate_infra_candidate, generate_infra_patch
from src.engine.validators.rules import apply_infra_patch, validate_infra_candidate


# 1. Charger l'infra actuelle
infra_current = json.load(open("data/infra.json", encoding="utf-8"))

# 2. Demande utilisateur
user_text = "Ajoute un PC02 sur Site1 avec IP 192.168.10.20 dans VLAN10"

# 3. Étape IA #1 : intent parsing + validation + repair + normalisation
intent_result = parse_intent(user_text, known_sites=["Site1", "Site2"])

print("\n=== INTENT RESULT ===")
print(json.dumps(intent_result, indent=2))

if intent_result["status"] not in ("VALID_INTENT", "VALID_INTENT_AFTER_REPAIR"):
    print("Intent invalide, arrêt.")
    exit()

intent = intent_result["intent"]

# 4. Étape IA #2 : génération infra patch
patch = generate_infra_patch(intent)
print("\n=== PATCH OPS ===")
print(json.dumps(patch, indent=2))

candidate = apply_infra_patch(infra_current, patch)
print("\n=== INFRA CANDIDATE (APPLIED PATCH) ===")
print(json.dumps(candidate, indent=2))

infra_issues = validate_infra_candidate(candidate)

print("\n=== INFRA VALIDATION ===")
for issue in infra_issues:
    print(issue)

if not infra_issues:
    print("Infra candidate is VALID")
else:
    print("Infra candidate has blocking issues")