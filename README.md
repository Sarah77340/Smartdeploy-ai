# SmartDeploy – AI Engine



---

# Architecture Overview

```
User Text
   ↓
Intent AI (LLM)
   ↓
Validation & Repair
   ↓
Infra Patch Generation (LLM)
   ↓
Patch Apply (deterministic)
   ↓
Infra Validation
   ↓
Ansible Artifact Generation
```

---

# Prerequisites

| Tool | Where |
|------|------|
| Python 3.10+ | Windows |
| Ollama | Windows |
| Model `mistral` | Ollama |
| WSL + Ubuntu | For Ansible execution |
| Ansible + community.general | Inside WSL |

---

# Terminals Used

| Task | Terminal |
|------|----------|
| Python development, running AI pipeline | Windows PowerShell |
| Running Ansible playbooks | WSL (Ubuntu) |
| Ollama server & model testing | Windows PowerShell |

---

# Installation (Windows PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate
pip install -U pip
```

---

# Start Ollama (PowerShell)

```powershell
ollama serve
```

---

# Download Model

```powershell
ollama pull mistral
```

---

# Test Model

```powershell
ollama run mistral "Respond only with: {\"ok\": true}"
```

---

# Input Data

Located in `data/`:

| File | Description |
|------|-------------|
| `infra.json` | Current internal infrastructure state |
| `netbox_export.json` | NetBox snapshot (reference) |

---

# Test Scripts (PowerShell)

| Script | Purpose |
|--------|--------|
| `run_llm_test.py` | Tests raw LLM connectivity and JSON response format |
| `run_intent_test.py` | Tests natural language → intent parsing and validation |
| `run_infra_test.py` | Tests intent → infra patch → infra candidate generation |
| `run_pipeline_test.py` | Full AI pipeline end-to-end |
| `run_ansible_test.py` | Generates Ansible files from infra_candidate |

---

## Run Full AI Pipeline

```powershell
python run_pipeline_test.py
```

### Outputs (in `data/output/`)

| File | Description |
|------|-------------|
| `<run_id>.intent_result.json` | Parsed and validated user intent |
| `<run_id>.infra_patch.json` | Minimal changes to apply |
| `<run_id>.infra_candidate.json` | Target infrastructure state |

---

# Generate Ansible Files

```powershell
python run_ansible_test.py
```

Outputs:

```
ansible_output/
 ├── hosts.ini
 └── site.yml
```

---

# Run Ansible (WSL Ubuntu)

Open WSL:

```powershell
wsl
cd /mnt/c/Efrei/SmartDeploy/Projet/smartdeploy-ai
```

Install dependencies once:

```bash
sudo apt update
sudo apt install ansible -y
ansible-galaxy collection install community.general
```

Run playbook locally:

```bash
ansible-playbook -i ansible_output/hosts.ini ansible_output/site.yml --ask-become-pass
```

---

# Outputs Summary

| Step | Output |
|------|--------|
| Intent AI | `<run_id>.intent_result.json` |
| Patch AI | `<run_id>.infra_patch.json` |
| Infra Candidate | `<run_id>.infra_candidate.json` |
| Automation Artifacts | `hosts.ini`, `site.yml` |

---

# Project Stage

This is the MVP of SmartDeploy:
- AI planning engine
- Deterministic validation
- Patch-based infra generation
- Executable Ansible baseline

Next evolution: multi-host automation and advanced network templates.
