"""Cliente simulado: responde às etapas a partir do gabarito do dataset.

Serve para testar o encadeamento e demonstrar o painel sem chave e sem custo.
NÃO mede a qualidade do Atest.AI: as respostas são o próprio gabarito.
"""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from .config import Settings
from .domain import LlmCall, Match
from .llm_schemas import (
    AttachmentIdentification,
    PhotoAnalysis,
    QuoteReview,
    ScopeReading,
)
from .repository import GroundTruth, load_ground_truth

T = TypeVar("T", bound=BaseModel)
MATCH = {True: "yes", False: "no", None: "undetermined"}


# Rótulo em português da classificação, para o texto do motivo simulado (aparece no painel).
CLASSIFICATION_LABELS = {"compliant": "aderente", "out_of_scope": "fora do escopo", "to_justify": "a justificar"}


class SimulatedClient:
    """Cliente que responde pelo gabarito, com ruído opcional para simular erros de um modelo real."""

    simulated = True
    via_batch = False

    def __init__(self, cfg: Settings, delay_s: float = 0.0, noise: float = 0.0):
        self.cfg = cfg
        self.delay_s = delay_s  # o painel usa um atraso pequeno para o progresso ficar visível
        # ruído: probabilidade de o "modelo simulado" errar cada decisão. Serve para ver as métricas de validação
        # se comportarem como num modelo real (com erros). 0 = devolve exatamente o gabarito.
        self.noise = noise

    def structured(
        self,
        *,
        task: str,
        system: str,
        parts: list,
        output: type[T],
        model: str,
        max_tokens: int,
        meta: dict[str, Any],
        fallback: str | None = None,
    ) -> tuple[T, LlmCall]:
        start = datetime.now()
        gt = load_ground_truth(self.cfg.ground_truth_dir, meta["ticket"])
        if gt is None:
            raise FileNotFoundError(
                f"O modo simulado só funciona com chamados do dataset (que têm gabarito); {meta['ticket']} não tem. Use o modo API."
            )
        if self.delay_s:
            time.sleep(self.delay_s * random.uniform(0.6, 1.4))
        raw = getattr(self, f"_{task}")(gt, meta)
        if self.noise:
            raw = self._perturb(task, raw, random.Random(f"{meta['ticket']}-{task}-{self.noise}"))
        obj = output.model_validate(raw)
        return obj, LlmCall(
            task=task,
            provider="simulated",
            model=f"simulado ({model})",
            start=start,
            duration_s=round((datetime.now() - start).total_seconds(), 2),
            simulated=True,
            response=obj.model_dump(mode="json"),
        )

    def _perturb(self, task: str, d: dict, rnd: random.Random) -> dict:
        """Erros típicos de um modelo: perder ou inventar um apontamento, ler mal uma foto."""
        r = self.noise
        if task == "scope":
            if rnd.random() < r:
                d["vague_scope"] = not d["vague_scope"]
            if rnd.random() < r / 2:
                d["consistent_with_category_symptom"] = not d["consistent_with_category_symptom"]
        elif task == "quote_review":
            for it in d["items"]:
                if rnd.random() < r:
                    it["classification"] = "compliant" if it["classification"] != "compliant" else rnd.choice(["out_of_scope", "to_justify"])
                if rnd.random() < r / 2:
                    it["plausible_quantity"] = not it["plausible_quantity"]
        elif task == "photos":
            for f in d["photos"]:
                if rnd.random() < r:
                    f["matches_scope"] = "yes" if f["matches_scope"] == "no" else ("no" if rnd.random() < 0.5 else f["matches_scope"])
                if rnd.random() < r / 3:
                    f["readable"] = not f["readable"]
            if rnd.random() < r:
                d["has_before_photo"] = not d["has_before_photo"]
            if rnd.random() < r:
                d["done_service"] = "no" if d["done_service"] == "yes" else "yes"
        elif task == "identify_attachments":
            for a in d["attachments"]:
                if rnd.random() < r / 3:
                    a["category"] = "other"
        return d

    # ------------------------------------------------------------------ respostas
    def _identify_attachments(self, g: GroundTruth, meta: dict) -> dict:
        attachments = []
        for index, name in zip(meta["indices"], meta["attachments"], strict=True):
            r = g.attachments[name]
            attachments.append(
                {"index": index, "category": r["category"], "moment": r["moment"], "readable": r["readable"], "short_description": r["description"]}
            )
        return AttachmentIdentification(attachments=attachments).model_dump()

    def _scope(self, g: GroundTruth, meta: dict) -> dict:
        vague = "vague_scope" in g.findings
        return ScopeReading(
            local="(simulado)",
            environment="(simulado)",
            equipment="",
            requested_services=["(simulado a partir do gabarito)"],
            mentioned_quantities=[],
            acceptance_criteria=["(simulado)"],
            expected_evidence=[],
            before_evidence_applicable=g.before_applicable,
            consistent_with_category_symptom="inconsistent_scope" not in g.findings,
            coherence_note="O escopo descreve troca de lâmpadas; categoria e sintoma indicam hidráulica/vazamento"
            if "inconsistent_scope" in g.findings
            else "",
            vague_scope=vague,
            vague_reason="O texto não diz qual porta nem qual defeito" if vague else "",
        ).model_dump()

    def _quote_review(self, g: GroundTruth, meta: dict) -> dict:
        items = []
        for i in g.items:
            dup = 0
            if "duplicate_item" in i["findings"]:
                dup = next(j["n"] for j in g.items if j["lpu_code"] == i["lpu_code"] and j["n"] < i["n"])
            items.append(
                {
                    "n": i["n"],
                    "classification": i["classification"],
                    "reason": f"(simulado) {CLASSIFICATION_LABELS.get(i['classification'], i['classification'])}",
                    "expected_quantity_max": -1 if "unverifiable_quantity" in i["findings"] else i.get("expected_quantity_max") or -1,
                    "plausible_quantity": not ({"quantity_above_expected", "unverifiable_quantity"} & set(i["findings"])),
                    "duplicate_of": dup,
                    "lpu_code": i["lpu_code"],
                }
            )
        return QuoteReview(items=items, notes="").model_dump()

    def _photos(self, g: GroundTruth, meta: dict) -> dict:
        photos = []
        for index, name in zip(meta["indices"], meta["attachments"], strict=True):
            r = g.attachments[name]
            photos.append(
                {
                    "index": index,
                    "environment": "",
                    "what_it_shows": r["description"],
                    "moment": r["moment"],
                    "readable": r["readable"],
                    "matches_scope": MATCH[r["matches_scope"]],
                    "reason": "(simulado)",
                    "covered_items": [],
                }
            )
        done = Match.NO if "missing_after_photo" in g.findings else Match.PARTIAL if "after_photo_unconfirmed_location" in g.findings else Match.YES
        before = any(g.attachments[n]["moment"] == "before" and g.attachments[n]["readable"] for n in meta["attachments"])
        return PhotoAnalysis(
            photos=photos,
            has_before_photo=before,
            done_justification="(simulado)",
            done_service=done,
            items_without_photo=[i["n"] for i in g.items if "item_without_photo" in i.get("findings", [])]
            or ([g.items[-1]["n"]] if "item_without_photo" in g.findings and g.items else []),
            notes="",
        ).model_dump()

    def _assessment(self, g: GroundTruth, meta: dict) -> dict:
        from .assessment import AssessmentWriter

        return AssessmentWriter.from_template(meta["result"]).model_dump()
