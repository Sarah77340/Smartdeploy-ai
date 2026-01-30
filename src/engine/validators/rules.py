def validate_intent_plan(intent: dict) -> list:
    issues = []

    for i, change in enumerate(intent.get("requested_changes", [])):
        ctype = change.get("type")
        payload = change.get("payload", {})

        # Règle 1 : add_device ne doit pas contenir d'IP
        if ctype == "add_device" and "ip_address" in payload:
            issues.append({
                "code": "IP_IN_DEVICE_ACTION",
                "message": "IP must be in an 'add_ip' action, not inside add_device.",
                "path": f"requested_changes[{i}].payload.ip_address"
            })

        # Règle 2 : add_ip doit contenir address + device
        if ctype == "add_ip":
            if "address" not in payload or "device" not in payload:
                issues.append({
                    "code": "INVALID_ADD_IP_PAYLOAD",
                    "message": "add_ip requires 'address' and 'device'",
                    "path": f"requested_changes[{i}]"
                })

        # Règle 3 : add_vlan doit avoir site + name ou vid
        if ctype == "add_vlan":
            if "site" not in payload:
                issues.append({
                    "code": "VLAN_SITE_MISSING",
                    "message": "VLAN must be attached to a site.",
                    "path": f"requested_changes[{i}]"
                })

    return issues

def normalize_intent_plan(intent: dict) -> tuple[dict, list, list]:
    """
    Returns: (normalized_intent, issues, questions)
    issues: non-blocking warnings
    questions: missing info to ask user
    """
    issues = []
    questions = []

    # 1) Default site from scope if missing in payload
    scope_sites = (intent.get("scope") or {}).get("sites") or []
    default_site = scope_sites[0] if scope_sites else None

    for ch in intent.get("requested_changes", []):
        ctype = ch.get("type")
        payload = ch.get("payload") or {}

        if default_site and "site" not in payload and ctype in ("add_device", "add_vlan", "add_prefix"):
            payload["site"] = default_site

        # 2) Normalize IP address to include mask (default /24)
        if ctype == "add_ip":
            addr = payload.get("address")
            if isinstance(addr, str) and "/" not in addr:
                payload["address"] = addr.strip() + "/24"
                issues.append({
                    "code": "ASSUMED_IP_MASK",
                    "severity": "WARN",
                    "message": "IP mask missing; assumed /24.",
                    "path": "requested_changes[].payload.address"
                })

            # 3) Interface missing -> question (or default)
            iface = payload.get("interface")
            if iface is None or (isinstance(iface, str) and iface.strip() == ""):
                questions.append({
                    "id": "NEED_INTERFACE",
                    "text": f"Quelle interface pour l'IP {payload.get('address','')} sur {payload.get('device','')} ? (ex: eth0)",
                    "path": "requested_changes[].payload.interface"
                })

        ch["payload"] = payload

    # 4) Confidence fallback rule
    # If no missing_information and no questions, set confidence >= 0.7
    if (intent.get("missing_information") == [] or intent.get("missing_information") is None) and not questions:
        intent["confidence"] = max(float(intent.get("confidence") or 0.0), 0.7)
    else:
        # If questions exist, keep it lower
        intent["confidence"] = max(float(intent.get("confidence") or 0.0), 0.4)

    return intent, issues, questions


def validate_infra_candidate(infra: dict) -> list:
    issues = []

    devices = infra.get("devices", [])
    interfaces = infra.get("interfaces", [])
    vlans = infra.get("vlans", [])
    prefixes = infra.get("prefixes", [])
    ips = infra.get("ips", [])

    # Index rapides
    device_names = {d.get("name") for d in devices}
    iface_by_device = {}
    for itf in interfaces:
        iface_by_device.setdefault(itf.get("device"), set()).add(itf.get("name"))

    # 1) device_type vide
    for i, d in enumerate(devices):
        if d.get("name") and (d.get("device_type") is None or str(d.get("device_type")).strip() == ""):
            issues.append({
                "code": "DEVICE_TYPE_MISSING",
                "severity": "FAIL",
                "path": f"devices[{i}].device_type",
                "message": f"Device '{d.get('name')}' has empty device_type."
            })

    # 2) IP: device doit exister + interface doit exister si renseignée
    for i, ip in enumerate(ips):
        dev = ip.get("device")
        iface = ip.get("interface")
        if dev and dev not in device_names:
            issues.append({
                "code": "IP_DEVICE_UNKNOWN",
                "severity": "FAIL",
                "path": f"ips[{i}].device",
                "message": f"IP references unknown device '{dev}'."
            })
        if dev and iface:
            if iface not in (iface_by_device.get(dev) or set()):
                issues.append({
                    "code": "IP_INTERFACE_UNKNOWN",
                    "severity": "WARN",
                    "path": f"ips[{i}].interface",
                    "message": f"Interface '{iface}' not found on device '{dev}'."
                })

    # 3) VLAN doublons par (site, name)
    seen = set()
    for i, v in enumerate(vlans):
        key = (v.get("site"), v.get("name"))
        if key in seen:
            issues.append({
                "code": "VLAN_DUPLICATE",
                "severity": "FAIL",
                "path": f"vlans[{i}]",
                "message": f"Duplicate VLAN name '{v.get('name')}' in site '{v.get('site')}'."
            })
        else:
            seen.add(key)

    # 4) Prefix VLAN doit exister (par name)
    vlan_names_by_site = {}
    for v in vlans:
        vlan_names_by_site.setdefault(v.get("site"), set()).add(v.get("name"))

    for i, p in enumerate(prefixes):
        vlan = p.get("vlan")
        site = p.get("site")
        if vlan and site and vlan not in (vlan_names_by_site.get(site) or set()):
            issues.append({
                "code": "PREFIX_VLAN_UNKNOWN",
                "severity": "FAIL",
                "path": f"prefixes[{i}].vlan",
                "message": f"Prefix '{p.get('prefix')}' references unknown VLAN '{vlan}' in site '{site}'."
            })

    return issues


def normalize_infra_candidate(infra: dict) -> tuple[dict, list, list]:
    issues = []
    questions = []

    # 1) Supprimer VLANs "_new" si VLAN existe déjà
    vlans = infra.get("vlans", [])
    by_site_name = {}
    for v in vlans:
        by_site_name.setdefault((v.get("site"), v.get("name")), 0)
        by_site_name[(v.get("site"), v.get("name"))] += 1

    cleaned_vlans = []
    for v in vlans:
        name = v.get("name") or ""
        key = (v.get("site"), name)
        if name.endswith("_new"):
            # si VLAN sans _new existe déjà sur le même site → drop
            base = name[:-4]
            if (v.get("site"), base) in by_site_name:
                issues.append({
                    "code": "DROPPED_REDUNDANT_VLAN",
                    "severity": "WARN",
                    "message": f"Dropped redundant VLAN '{name}' because '{base}' already exists.",
                    "path": "vlans[]"
                })
                continue
        cleaned_vlans.append(v)

    infra["vlans"] = cleaned_vlans

    # 2) device_type manquant -> question
    for d in infra.get("devices", []):
        if d.get("name") and (d.get("device_type") is None or str(d.get("device_type")).strip() == ""):
            questions.append({
                "id": "NEED_DEVICE_TYPE",
                "text": f"Quel device_type pour {d.get('name')} ? (ex: Windows 10)",
                "path": f"devices[name={d.get('name')}].device_type"
            })

    return infra, issues, questions

def apply_infra_patch(infra: dict, patch: dict) -> dict:
    infra = dict(infra)

    infra.setdefault("devices", [])
    infra.setdefault("interfaces", [])
    infra.setdefault("ips", [])
    infra.setdefault("vlans", [])

    device_names = {d.get("name") for d in infra["devices"]}
    vlan_keys = {(v.get("site"), v.get("name")) for v in infra["vlans"]}
    iface_keys = {(i.get("device"), i.get("name")) for i in infra["interfaces"]}
    ip_keys = {(ip.get("device"), ip.get("address")) for ip in infra["ips"]}

    for op in patch.get("ops", []):
        kind = op.get("op")

        if kind == "add_device":
            d = op.get("device", {})
            if d.get("name") and d["name"] not in device_names:
                infra["devices"].append(d)
                device_names.add(d["name"])

        elif kind == "add_interface":
            itf = op.get("interface", {})
            key = (itf.get("device"), itf.get("name"))
            if itf.get("device") and itf.get("name") and key not in iface_keys:
                infra["interfaces"].append(itf)
                iface_keys.add(key)

        elif kind == "add_ip":
            ip = op.get("ip", {})
            key = (ip.get("device"), ip.get("address"))
            if ip.get("device") and ip.get("address") and key not in ip_keys:
                infra["ips"].append(ip)
                ip_keys.add(key)

        elif kind == "ensure_vlan":
            v = op.get("vlan", {})
            key = (v.get("site"), v.get("name"))
            if v.get("site") and v.get("name") and key not in vlan_keys:
                infra["vlans"].append(v)
                vlan_keys.add(key)

    return infra
