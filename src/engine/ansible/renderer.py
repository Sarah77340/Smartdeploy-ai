from pathlib import Path
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))


def render_ansible_baseline(
    infra: dict,
    output_dir: str,
    ssh_user: str,
    ssh_port: int = 22,
    allow_http: bool = True,
    allow_https: bool = True,
    target_device: str | None = None,
):
    """
    Render exactly 2 files: hosts.ini and site.yml

    Selection logic:
    - If target_device is provided, use it
    - Else pick a device that has at least one IP in infra["ips"]
    - Else raise a clear error
    """

    devices = infra.get("devices", [])
    ips = infra.get("ips", [])

    if not devices:
        raise ValueError("No devices found in infra['devices'].")

    # Build device -> list of IP entries
    ips_by_device: dict[str, list[dict]] = {}
    for ip in ips:
        dev = ip.get("device")
        if dev:
            ips_by_device.setdefault(dev, []).append(ip)

    # Choose device
    device_name = None
    if target_device:
        device_name = target_device
        if device_name not in {d.get("name") for d in devices}:
            raise ValueError(f"target_device '{device_name}' not found in infra['devices'].")

        if device_name not in ips_by_device:
            raise ValueError(
                f"target_device '{device_name}' has no IP in infra['ips']. "
                f"Devices that have IPs: {sorted(ips_by_device.keys())}"
            )
    else:
        # Prefer a device with role 'Ordinateur' that has an IP, otherwise any device with IP
        ordinateurs = [d for d in devices if (d.get("device_role") or "").lower() == "ordinateur"]
        with_ip = [d for d in ordinateurs if d.get("name") in ips_by_device]
        if with_ip:
            device_name = with_ip[0]["name"]
        elif ips_by_device:
            device_name = sorted(ips_by_device.keys())[0]
        else:
            raise ValueError(
                "No IPs found in infra['ips'] for any device. "
                f"Devices present: {[d.get('name') for d in devices]}"
            )

    # Pick first IP and strip mask
    ip_entry = ips_by_device[device_name][0]
    host_ip = (ip_entry.get("address") or "").split("/")[0].strip()
    if not host_ip:
        raise ValueError(f"Device '{device_name}' has an IP entry but 'address' is empty: {ip_entry}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    hosts_tpl = env.get_template("hosts.ini.j2")
    site_tpl = env.get_template("site.yml.j2")

    (Path(output_dir) / "hosts.ini").write_text(
        hosts_tpl.render(
            device_name=device_name,
            host_ip=host_ip,
            ssh_user=ssh_user,
            ssh_port=ssh_port,
        ),
        encoding="utf-8",
    )

    (Path(output_dir) / "site.yml").write_text(
        site_tpl.render(
            ssh_port=ssh_port,
            allow_http=str(allow_http).lower(),
            allow_https=str(allow_https).lower(),
        ),
        encoding="utf-8",
    )
