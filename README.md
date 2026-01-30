# SmartDeploy partie AI Engine 

## Prérequis
- Python 
- Ollama installé et lancé
- Modèle téléchargé `mistral`

## Installation (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -U pip
pip install -e .
```

## Démarrer Ollama
```powershell
ollama serve
```

## Télécharger modèle
```powershell
ollama pull mistral
```

## Tester mistral :
```powershell
ollama run mistral "Réponds uniquement par: {\"ok\": true}"
```

## Données d'entrée :
Dans data/
- infra.json : état courant (inventaire interne)
- netbox_export.json : snapshot NetBox (pas utilisé)

## Lancer test complet du pipeline
```powershell
python run_pipeline_test.py
```

Sorties :
Dans data/output/
- Sortie complète de l’étape IA (pour compréhension du besoin) : data/output/<run_id>.intent_result.json
- Patch minimal à appliquer : data/output/<run_id>.infra_patch.json
- Fichier voulu pour l'infra : data/output/<run_id>.infra_candidate.json