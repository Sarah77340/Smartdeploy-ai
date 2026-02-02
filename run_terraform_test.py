import json
from pathlib import Path
from src.engine.terraform.renderer_gcp import render_terraform_gcp

DATA_DIR = Path("data/output")

candidates = sorted(DATA_DIR.glob("*.infra_candidate.json"))

if not candidates:
    raise FileNotFoundError("No *.infra_candidate.json file found in data/output")

infra_file = candidates[-1]
print(f"Using infra file: {infra_file.name}")

infra = json.load(open(infra_file, encoding="utf-8"))

render_terraform_gcp(
    infra=infra,
    output_dir="terraform_output",
    project_id="YOUR_GCP_PROJECT_ID",
    region="europe-west1",
    zone="europe-west1-b",
    allow_http=True,
    allow_https=True,
    ssh_port=22,
)

print("Terraform files generated in terraform_output/")
