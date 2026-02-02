import json
from dataclasses import asdict

from src.engine.pipeline_runner import run_pipeline, PipelineConfig


def main():
    # 1) Charger l'infra actuelle / fichier template etc..
    with open("data/infra.json", "r", encoding="utf-8") as f:
        infra_current = json.load(f)

    # 2) Example de prompt utilisateur
    user_text = "Ajoute un PC02 sur Site1 avec IP 192.168.10.20 dans VLAN10"

    # 3) Config pipeline
    cfg = PipelineConfig(
        known_sites=["Site1", "Site2"],
        llm_model="qwen2.5:latest",
        output_dir="data/output",
        save_intent=True,
        save_patch=True,
        save_candidate=True,
    )

    # 4) Run du pipeline
    result = run_pipeline(
        user_text=user_text,
        infra_current=infra_current,
        cfg=cfg,
    )

    # 5) Affichage (pour debug dev)
    print("\n=== PIPELINE RESULT ===")
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))

    # 6) Vérif fichiers
    print("\n=== FILES ===")
    if result.files:
        for k, v in result.files.items():
            print(f"{k}: {v}")
    else:
        print("No files saved.")


if __name__ == "__main__":
    main()
