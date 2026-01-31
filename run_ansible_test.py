import json
from pathlib import Path
from src.engine.ansible.renderer import render_ansible_baseline

DATA_DIR = Path("data/output")

candidates = list(DATA_DIR.glob("*.infra_candidate.json"))

if not candidates:
    raise FileNotFoundError("No *.infra_candidate.json file found in /data")

infra_file = candidates[0]
print(f"Using infra file: {infra_file.name}")

infra = json.load(open(infra_file, encoding="utf-8"))

render_ansible_baseline(
    infra,
    output_dir="ansible_output",
    ssh_user="ubuntu",
    ssh_port=22,
    allow_http=True,
    allow_https=True
)

print("Ansible files generated in ansible_output/")
