from src.engine.llm.ollama_openai import OllamaProvider, OllamaConfig
from src.engine.validators.jsonschema_validate import validate_json_schema
from src.engine.validators.rules import validate_intent_plan
from src.engine.validators.rules import normalize_intent_plan
from src.engine.validators.jsonschema_validate import validate_json_schema
from src.engine.validators.jsonschema_validate import validate_json_schema


INTENT_SCHEMA_PATH = "src/engine/schemas/intent.schema.json"
INFRA_SCHEMA_PATH = "src/engine/schemas/infra.schema.json"
PATCH_SCHEMA_PATH = "src/engine/schemas/infra_patch.schema.json"

def _validate_intent_or_issues(intent: dict) -> list:
    """Return list of issues (empty if valid). Raises if schema invalid."""
    validate_json_schema(intent, INTENT_SCHEMA_PATH)
    return validate_intent_plan(intent)


def _valid_return(status: str, intent: dict) -> dict:
    normalized, norm_issues, questions = normalize_intent_plan(intent)
    return {
        "status": status,
        "intent": normalized,
        "issues": norm_issues,
        "questions": questions,
    }


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
        "Output ONLY valid JSON. No markdown. No comments."
    )

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

    issues = _validate_intent_or_issues(out)
    if not issues:
        return _valid_return("VALID_INTENT", out)

    # Try repair once
    repaired = repair_intent(out, issues, known_sites)
    issues_after = _validate_intent_or_issues(repaired)

    if not issues_after:
        return _valid_return("VALID_INTENT_AFTER_REPAIR", repaired)

    return {
        "status": "INVALID_INTENT",
        "issues": issues_after,
        "intent": repaired
    }


def generate_infra_candidate(intent: dict, infra_current: dict) -> dict:
    llm = OllamaProvider(OllamaConfig(model="mistral", temperature=0.0))

    system_prompt = (
        "You generate a target infrastructure JSON.\n"
        "Output ONLY valid JSON matching the infra schema.\n"
        "Start from current infra and apply requested_changes."
    )

    user_prompt = f"""
Current infrastructure:
{infra_current}

Requested changes:
{intent['requested_changes']}

Rules:
- Do not remove existing objects.
- Add new objects when required.
- Keep structure consistent.
"""

    candidate = llm.chat_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    validate_json_schema(candidate, INFRA_SCHEMA_PATH)


def generate_infra_patch(intent: dict) -> dict:
    llm = OllamaProvider(OllamaConfig(model="mistral", temperature=0.0))

    system_prompt = (
        "You generate a minimal patch (operations list) to update an infrastructure inventory.\n"
        "Return ONLY JSON. No markdown.\n"
        "Do NOT output the full infrastructure, only the patch ops."
    )

    # On ne donne PAS infra_current pour éviter prompt énorme.
    # On donne juste les requested_changes + règles.
    user_prompt = f"""
Generate a JSON object:
{{
  "ops": [
    {{"op": "add_device", "device": {{"name": "...", "site": "...", "device_role": "Ordinateur", "device_type": "Windows 10", "status": "pending"}}}},
    {{"op": "add_interface", "interface": {{"device": "...", "name": "eth0", "type": "virtual"}}}},
    {{"op": "add_ip", "ip": {{"address": "x.x.x.x/xx", "device": "...", "interface": "eth0", "vlan": "VLAN10"}}}},
    {{"op": "ensure_vlan", "vlan": {{"name": "VLAN10", "site": "Site1"}}}}
  ]
}}

Rules:
- Only output the patch JSON (ops list).
- If interface is unknown/empty, use "eth0" as default and add an assumption in device status "pending".
- Choose device_type based on role: for a PC/Ordinateur use "Windows 10".
- VLAN name should be exactly the one requested.

Requested changes:
{intent["requested_changes"]}
"""

    patch = llm.chat_json([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    validate_json_schema(patch, PATCH_SCHEMA_PATH)
    return patch