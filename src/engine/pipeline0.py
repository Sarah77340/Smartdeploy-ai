from src.engine.llm.ollama_openai import OllamaProvider, OllamaConfig
from src.engine.validators.jsonschema_validate import validate_json_schema
from src.engine.validators.rules import validate_intent_plan
from src.engine.validators.rules import normalize_intent_plan

INTENT_SCHEMA_PATH = "src/engine/schemas/intent.schema.json"


def repair_intent0(intent: dict, issues: list) -> dict:
    llm = OllamaProvider(OllamaConfig(model="mistral", temperature=0.0))

    system_prompt = (
        "You fix invalid network intent JSON.\n"
        "Return ONLY corrected JSON. No explanation."
    )

    user_prompt = f"""
The following intent JSON is invalid:

{intent}

Problems detected:
{issues}

Fix the JSON while keeping the same structure.
Do not remove requested changes, only correct them.
"""

    return llm.chat_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

def repair_intent(intent: dict, issues: list, known_sites: list[str]) -> dict:
    llm = OllamaProvider(OllamaConfig(model="mistral", temperature=0.0))

    system_prompt = (
        "You fix invalid network intent JSON.\n"
        "Output ONLY valid JSON. No markdown. No extra text.\n"
        "You MUST keep the same top-level structure and keys.\n"
        "IMPORTANT: In requested_changes, each item MUST contain ONLY: {\"type\": ..., \"payload\": {...}}.\n"
        "Do NOT add extra keys like 'add_ip' or anything else.\n"
    )

    user_prompt = f"""
You must output JSON with EXACTLY these keys:
- scope
- requested_changes
- assumptions
- missing_information
- confidence

Rules:
- requested_changes is a LIST of actions.
- Each action is an object with EXACTLY two keys: "type" and "payload".
- "type" must be one of: add_device, add_vlan, add_prefix, add_ip, add_firewall_rule, update_device, update_ip
- Put ONE action per list item.
- For an IP, create a SEPARATE action with type "add_ip" and payload fields:
  {{"address": "x.x.x.x/xx", "device": "NAME", "interface": "NAME"}}
- Allowed sites: {known_sites}
- confidence must be > 0 when the intent is clear.

Current (invalid) intent JSON:
{intent}

Detected issues:
{issues}

Return the corrected JSON only.
"""

    return llm.chat_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])


def parse_intent(user_text: str, known_sites: list[str]) -> dict:
    llm = OllamaProvider(OllamaConfig(model="mistral", temperature=0.0))

    system_prompt = (
        "You convert user requests into a STRICT JSON plan.\n"
        "Output ONLY valid JSON. No markdown. No comments.\n"
        "IMPORTANT: Each requested_changes item MUST have exactly one type from the enum.\n"
        "Never put multiple types in one string."
    )

    example = """
Example output:
{
  "scope": {
    "sites": ["Site1"],
    "devices": ["PC02"],
    "device_roles": [],
    "tags": []
  },
  "requested_changes": [
    {"type": "add_device", "payload": {"name": "PC02", "site": "Site1"}},
    {"type": "add_ip", "payload": {"address": "192.168.10.20/24", "device": "PC02", "interface": "eth0"}},
    {"type": "add_vlan", "payload": {"name": "VLAN10", "site": "Site1"}}
  ],
  "assumptions": ["If mask is missing, assume /24"],
  "missing_information": [],
  "confidence": 0.85
}
""".strip()

    user_prompt = f"""
Return ONLY JSON.

Structure:
{{
  "scope": {{"sites": [], "devices": [], "device_roles": [], "tags": []}},
  "requested_changes": [{{"type": "", "payload": {{}}}}],
  "assumptions": [],
  "missing_information": [],
  "confidence": 0.0
}}

Rules:
- One action per requested_changes item.
- Valid types: add_device, add_vlan, add_prefix, add_ip, add_firewall_rule, update_device, update_ip
- Allowed sites: {known_sites}

User request:
{user_text}
"""

    out = llm.chat_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    validate_json_schema(out, INTENT_SCHEMA_PATH)
    issues = validate_intent_plan(out)

    if issues:
        repaired = repair_intent(out, issues, known_sites)

        # pour revalider
        validate_json_schema(repaired, INTENT_SCHEMA_PATH)
        issues_after = validate_intent_plan(repaired)

        if not issues_after:
            return {"status": "VALID_INTENT_AFTER_REPAIR", "intent": repaired}
        
        return {"status": "INVALID_INTENT", "issues": issues_after, "intent": repaired}

    return out
    