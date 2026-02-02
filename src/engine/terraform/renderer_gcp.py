from __future__ import annotations
from pathlib import Path
from typing import Any
from jinja2 import Environment, FileSystemLoader
import ipaddress
import re

TEMPLATE_DIR = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False)


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    out = []
    for c in s:
        out.append(c if c.isalnum() else "-")
    s2 = "".join(out).strip("-")
    while "--" in s2:
        s2 = s2.replace("--", "-")
    return s2 or "x"


def _tf_name(s: str) -> str:
    s = _slug(s).replace("-", "_")
    if s and s[0].isdigit():
        s = f"r_{s}"
    return s


def render_terraform_gcp(
    infra: dict[str, Any],
    output_dir: str,
    project_id: str,
    region: str = "europe-west1",
    zone: str = "europe-west1-b",
    allow_http: bool = True,
    allow_https: bool = True,
    ssh_port: int = 22,
) -> Path:

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    sites = infra.get("sites", [])
    prefixes = infra.get("prefixes", [])
    devices = infra.get("devices", [])
    ips = infra.get("ips", [])
    fw_in = infra.get("firewall_rules", [])

    # --- Networks ---
    networks = []
    for s in sites:
        site_name = s["name"]
        net_name = f"vpc-{_slug(site_name)}"
        networks.append({
            "site": site_name,
            "name": net_name,
            "tf_name": _tf_name(net_name),
        })

    if not networks:
        networks = [{"site": "default", "name": "vpc-default", "tf_name": "vpc_default"}]

    net_by_site = {n["site"]: n for n in networks}
    default_net = networks[0]

    # --- Subnets ---
    subnets = []
    for idx, p in enumerate(prefixes, start=1):
        site = p.get("site") or default_net["site"]
        net = net_by_site.get(site, default_net)
        sn_name = f"subnet-{_slug(site)}-{idx}"
        subnets.append({
            "site": site,
            "name": sn_name,
            "tf_name": _tf_name(sn_name),
            "cidr": p["prefix"],
            "network_tf_name": net["tf_name"],
        })

    if not subnets:
        subnets = [{
            "site": default_net["site"],
            "name": "subnet-default-1",
            "tf_name": "subnet_default_1",
            "cidr": "10.10.0.0/24",
            "network_tf_name": default_net["tf_name"],
        }]

    parsed_subnets = [(sn["tf_name"], ipaddress.ip_network(sn["cidr"])) for sn in subnets]

    def find_device_ip(dev_name: str) -> str | None:
        for ip in ips:
            if ip.get("device") == dev_name:
                addr = (ip.get("address") or "").split("/")[0].strip()
                return addr or None
        return None

    def pick_subnet_tf_for_ip(ip_str: str | None) -> str:
        if not ip_str:
            return subnets[0]["tf_name"]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return subnets[0]["tf_name"]
        for sn_tf, net in parsed_subnets:
            if ip_obj in net:
                return sn_tf
        return subnets[0]["tf_name"]

    def device_site(dev: dict) -> str:
        return dev.get("site") or default_net["site"]

    # --- VMs ---
    vms = []
    for d in devices:
        if (d.get("device_role") or "").lower() != "ordinateur":
            continue

        status = (d.get("status") or "").lower()
        if status and status not in ("active", "pending"):
            continue

        dev_name = d["name"]
        site = device_site(d)
        internal_ip = find_device_ip(dev_name)
        subnet_tf = pick_subnet_tf_for_ip(internal_ip)

        tags = [f"site-{_slug(site)}", "role-ordinateur"]

        vms.append({
            "name": _slug(dev_name),
            "tf_name": _tf_name(dev_name),
            "machine_type": "e2-micro",
            "image": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts",
            "subnet_tf_name": subnet_tf,
            "internal_ip": internal_ip,
            "tags": tags,
        })

    # --- Baseline Firewalls ---
    baseline_firewalls = []
    for n in networks:
        site_tag = f"site-{_slug(n['site'])}"
        target_tags = [site_tag, "role-ordinateur"]

        baseline_firewalls.append({
            "name": f"allow-ssh-{_slug(n['site'])}",
            "tf_name": _tf_name(f"allow_ssh_{n['site']}"),
            "network_tf_name": n["tf_name"],
            "protocol": "tcp",
            "ports_expr": "tostring(var.ssh_port)",
            "ports_list": None,
            "target_tags": target_tags,
        })

        if allow_http:
            baseline_firewalls.append({
                "name": f"allow-http-{_slug(n['site'])}",
                "tf_name": _tf_name(f"allow_http_{n['site']}"),
                "network_tf_name": n["tf_name"],
                "protocol": "tcp",
                "ports_expr": None,
                "ports_list": ["80"],
                "target_tags": target_tags,
            })

        if allow_https:
            baseline_firewalls.append({
                "name": f"allow-https-{_slug(n['site'])}",
                "tf_name": _tf_name(f"allow_https_{n['site']}"),
                "network_tf_name": n["tf_name"],
                "protocol": "tcp",
                "ports_expr": None,
                "ports_list": ["443"],
                "target_tags": target_tags,
            })


    # --- Custom Firewall Rules ---
    def parse_service(service: str) -> tuple[str, list[str]]:
        s = (service or "").strip().lower()
        m = re.match(r"^(tcp|udp)\s*/\s*(.+)$", s)
        if not m:
            return "tcp", []
        proto = m.group(1)
        ports = [p.strip() for p in m.group(2).split(",") if p.strip()]
        return proto, ports

    fw_rules = []
    for idx, r in enumerate(fw_in, start=1):
        if (r.get("action") or "").lower() != "allow":
            continue

        src = r.get("source") or "0.0.0.0/0"
        proto, ports = parse_service(r.get("service") or "")
        if not ports:
            continue

        rule_site = default_net["site"]
        try:
            src_net = ipaddress.ip_network(src, strict=False)
            for p in prefixes:
                p_net = ipaddress.ip_network(p["prefix"], strict=False)
                if src_net.subnet_of(p_net) or p_net.subnet_of(src_net) or src_net == p_net:
                    if p.get("site"):
                        rule_site = p["site"]
                        break
        except Exception:
            pass

        net = net_by_site.get(rule_site, default_net)
        target_tags = [f"site-{_slug(rule_site)}", "role-ordinateur"]

        fw_rules.append({
            "name": f"{_slug(r.get('name') or f'rule-{idx}')}-{_slug(rule_site)}",
            "tf_name": _tf_name(f"fw_{idx}_{rule_site}_{r.get('name') or 'rule'}"),
            "network_tf_name": net["tf_name"],

            "source_ranges": [src],          # plus de '"192.168.../24"' → juste la string
            "protocol": proto,
            "ports": ports,                  # liste propre ["80","443"], sans guillemets internes
            "target_tags": target_tags,
        })


    # --- Render Files ---
    (out / "variables.tf").write_text(
        env.get_template("variables.tf.j2").render(),
        encoding="utf-8"
    )

    (out / "terraform.tfvars").write_text(
        env.get_template("terraform.tfvars.j2").render(
            project_id=project_id,
            region=region,
            zone=zone,
            allow_http=str(allow_http).lower(),
            allow_https=str(allow_https).lower(),
            ssh_port=ssh_port,
        ),
        encoding="utf-8"
    )

    (out / "main.tf").write_text(
        env.get_template("main.tf.j2").render(
            networks=networks,
            subnets=subnets,
            vms=vms,
            baseline_firewalls=baseline_firewalls,
            fw_rules=fw_rules,
        ),
        encoding="utf-8"
    )

    return out
