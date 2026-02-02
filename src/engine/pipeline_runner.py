from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from src.engine.pipeline import parse_intent, generate_infra_patch
from src.engine.validators.rules import apply_infra_patch, validate_infra_candidate


@dataclass
class PipelineConfig:
    known_sites: List[str]
    llm_model: str = "mistral"
    output_dir: str = "data/output"
    save_intent: bool = True
    save_patch: bool = True
    save_candidate: bool = True


@dataclass
class PipelineResult:
    run_id: str
    status: str  # OK | NEED_USER_INPUT | INVALID_INTENT | INVALID_INFRA | ERROR
    elapsed_ms: int

    # main objects
    intent_result: Optional[Dict[str, Any]] = None
    patch: Optional[Dict[str, Any]] = None
    infra_candidate: Optional[Dict[str, Any]] = None

    # validation
    infra_issues: Optional[List[Dict[str, Any]]] = None

    # files saved
    files: Optional[Dict[str, str]] = None  # {"intent": "...", "patch": "...", "infra_candidate": "..."}

    # debug/info
    error: Optional[Dict[str, Any]] = None


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _write_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)

def run_pipeline(
    user_text: str,
    infra_current: Dict[str, Any],
    cfg: PipelineConfig,
) -> PipelineResult:
    """
    Orchestrateur unique (à appeler depuis API/back).
    - Ne print rien
    - Retourne un résultat structuré (status + payload)
    - Écrit les artefacts JSON sur disque (optionnel)
    """
    started = time.time()
    run_id = uuid.uuid4().hex[:10]

    files: Dict[str, str] = {}
    try:
        _ensure_dir(cfg.output_dir)

        ### IA : intent parsing + validation + repair + normalisation
        intent_result = parse_intent(user_text, known_sites=cfg.known_sites, model=cfg.llm_model)

        # Sauvegarde intent_result (utile pour debug front)
        if cfg.save_intent:
            p = os.path.join(cfg.output_dir, f"{run_id}.intent_result.json")
            _write_json(p, intent_result)
            files["intent_result"] = p

        # Gestion statut intent
        status = intent_result.get("status")
        if status not in ("VALID_INTENT", "VALID_INTENT_AFTER_REPAIR"):
            elapsed_ms = int((time.time() - started) * 1000)
            return PipelineResult(
                run_id=run_id,
                status="INVALID_INTENT",
                elapsed_ms=elapsed_ms,
                intent_result=intent_result,
                files=files or None,
            )

        # Pour front si on doit répondre à des questions (interface manquante)
        questions = intent_result.get("questions") or []

        # si on veut bloquer avant de générer, mettre "return" ici
        intent = intent_result["intent"]

        ### IA : patch minimal
        patch = generate_infra_patch(intent, model=cfg.llm_model)

        if cfg.save_patch:
            p = os.path.join(cfg.output_dir, f"{run_id}.infra_patch.json")
            _write_json(p, patch)
            files["infra_patch"] = p

        ### Déterministe : appliquer patch
        candidate = apply_infra_patch(infra_current, patch)

        ### Validation infra (déterministe)
        infra_issues = validate_infra_candidate(candidate)
        if infra_issues:
            # Opt : sauvegarde pr debug
            if cfg.save_candidate:
                p = os.path.join(cfg.output_dir, f"{run_id}.infra_candidate.json")
                _write_json(p, candidate)
                files["infra_candidate"] = p

            elapsed_ms = int((time.time() - started) * 1000)
            return PipelineResult(
                run_id=run_id,
                status="INVALID_INFRA",
                elapsed_ms=elapsed_ms,
                intent_result=intent_result,
                patch=patch,
                infra_candidate=candidate,
                infra_issues=infra_issues,
                files=files or None,
            )

        ### Sauvegarde candidate validée
        if cfg.save_candidate:
            p = os.path.join(cfg.output_dir, f"{run_id}.infra_candidate.json")
            _write_json(p, candidate)
            files["infra_candidate"] = p

        elapsed_ms = int((time.time() - started) * 1000)

        # Pr bloquer tant que questions pas répondues :
        # return NEED_USER_INPUT ici
        if questions:
            return PipelineResult(
                run_id=run_id,
                status="NEED_USER_INPUT",
                elapsed_ms=elapsed_ms,
                intent_result=intent_result,
                patch=patch,
                infra_candidate=candidate,
                infra_issues=[],
                files=files or None,
            )

        return PipelineResult(
            run_id=run_id,
            status="OK",
            elapsed_ms=elapsed_ms,
            intent_result=intent_result,
            patch=patch,
            infra_candidate=candidate,
            infra_issues=[],
            files=files or None,
        )

    except Exception as e:
        elapsed_ms = int((time.time() - started) * 1000)
        return PipelineResult(
            run_id=run_id,
            status="ERROR",
            elapsed_ms=elapsed_ms,
            intent_result=None,
            patch=None,
            infra_candidate=None,
            infra_issues=None,
            files=files or None,
            error={
                "type": type(e).__name__,
                "message": str(e),
            },
        )
