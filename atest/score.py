"""Score de conformidade 0–100, faixas de recomendação e regras de trava, conforme a régua do deck.

Determinístico: o modelo não dá nota. Ele aponta divergências e a régua (config/rubric.toml) converte os
apontamentos em notas, score, confiança e recomendação.

Proporcional ao que o fornecedor enviou: cada tipo desconta a severidade × a fração que atinge (1 foto ruim em 6
pesa menos que 6 em 6; R$ 20 num orçamento de R$ 10 mil pesa menos que o orçamento inteiro). O valor em questão
limita a nota de Orçamento, e faltas do fornecedor (serviço pedido sem item, item fora do escopo, muito do orçamento
em questão) devolvem o chamado qualquer que seja a nota.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel

from .domain import (
    Confidence,
    Extent,
    Finding,
    Grades,
    Recommendation,
    Rubric,
    ValidationResult,
)
from .formatting import brl

# Motivo exibido para cada faixa de score (sem trava e com confiança suficiente).
BAND_REASONS = {
    Recommendation.APPROVE: "Score de 85 ou mais, sem travas",
    Recommendation.APPROVE_WITH_CAVEATS: "Score entre 70 e 84",
    Recommendation.RETURN_TO_SUPPLIER: "Score abaixo de 70, com apontamentos",
}

# Redutores de confiança que não são tipos de apontamento da régua (vêm das etapas), com o rótulo em português.
EXTRA_REDUCERS = {
    "unreadable_quote": "orçamento não lido",
    "photos_not_analyzed": "fotos não analisadas pelo modelo",
    "documents_not_analyzed": "documentos não lidos pelo modelo",
    "related_not_checked": "chamados da agência não comparados pelo modelo",
}


@dataclass
class Measures:
    """O que o fornecedor enviou, para medir a fração que cada apontamento atinge."""

    total_value: float = 0.0
    photos: int = 0
    items: int = 0  # itens físicos a conferir nas fotos
    documents: int = 0
    services: int = 0  # serviços pedidos no chamado
    services_missing: int = 0  # sem item no orçamento
    services_partial: int = 0  # cobertos só em parte (contam metade)


def _plural(n: float, one: str, many: str) -> str:
    return f"{n:g} {one if n == 1 else many}"


class ScoreResult(BaseModel):
    """Notas por validação, score ponderado, confiança e recomendação."""

    grades: Grades
    score: int
    confidence: Confidence
    confidence_reducers: list[str]
    recommendation: Recommendation
    recommendation_reason: str


class ScoreCalculator:
    """Aplica a régua: cria apontamentos tipados e converte a lista de apontamentos em score e recomendação.

    Attributes:
        rubric: régua (config/rubric.toml): tipos de apontamento, descontos por severidade, pesos das validações,
            faixas de recomendação, limites de confiança e de valor em questão.
    """

    def __init__(self, rubric: Rubric):
        """
        Args:
            rubric: régua a aplicar (a padrão ou a da esteira, via `rubric.for_workstream`).
        """
        self.rubric = rubric

    def finding(
        self, kind: str, evidence: str, reference: str = "", amount: float = 0.0
    ) -> Finding:
        """Cria um apontamento do tipo `kind` com severidade, desconto, fase e trava definidos na régua.

        Args:
            kind: tipo do apontamento; precisa existir em [finding_types] da régua.
            evidence: o que foi visto (texto para a pessoa analista).
            reference: o que o apontamento atinge (ex.: "item 3: Pintura", nome da foto, "escopo").
            amount: valor em questão em R$ (item inteiro ou só o excedente, conforme o tipo).

        Returns:
            O `Finding` com desconto cheio da severidade (a proporcionalidade é aplicada depois, em `proportional`).

        Raises:
            KeyError: `kind` não está na régua.
        """
        spec = self.rubric.finding_types[kind]
        return Finding(
            kind=kind,
            validation=spec.validation,
            severity=spec.severity,
            discount=self.rubric.discount_by_severity[spec.severity],
            description=spec.description,
            evidence=evidence,
            reference=reference,
            lock=spec.lock,
            reduces_confidence=spec.reduces_confidence,
            phase=spec.phase,
            amount_at_issue=round(amount, 2),
            returns=spec.returns,
            review=spec.review,
        )

    # ------------------------------------------------------------------ proporcional ao que foi enviado
    def proportional(
        self, findings: list[Finding], measures: Measures | None
    ) -> list[Finding]:
        """Desconto de cada tipo = severidade × (piso + (1 − piso) × fração atingida), igual em todos os do tipo.

        Sem medidas (gabarito, testes), a fração é 1: o tipo desconta a severidade inteira.

        Args:
            findings: apontamentos com o desconto cheio da severidade.
            measures: o que o fornecedor enviou (fotos, itens, documentos, serviços, valor total); None = fração 1.

        Returns:
            Cópias dos apontamentos com `discount`, `extent` (fração 0–1) e `extent_label` (fração em palavras,
            ex.: "2 de 6 fotos") preenchidos. O piso vem de [proportional_floor] da régua.
        """
        # Piso: mesmo atingindo pouco do que foi enviado, o tipo desconta ao menos esta fração da severidade.
        floor = self.rubric.proportional_floor
        # Agrupa por (validação, tipo): todos os apontamentos do mesmo tipo dividem uma única fração.
        groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
        for f in findings:
            groups[(f.validation.value, f.kind)].append(f)
        update: dict[tuple[str, str], dict] = {}
        for key, fs in groups.items():
            spec = self.rubric.finding_types.get(fs[0].kind)
            # Fração atingida (0–1) e a mesma fração em palavras; sem medidas, a fração é 1 (desconto cheio).
            share, label = (
                (1.0, "")
                if spec is None or measures is None
                else self._share(spec.extent, fs, measures)
            )
            full = self.rubric.discount_by_severity[fs[0].severity]
            update[key] = {
                "discount": round(full * (floor + (1 - floor) * share)),
                "extent": round(share, 3),
                "extent_label": label,
            }
        return [
            f.model_copy(update=update[(f.validation.value, f.kind)]) for f in findings
        ]

    @staticmethod
    def _share(extent: Extent, fs: list[Finding], m: Measures) -> tuple[float, str]:
        """Fração do que foi enviado que os apontamentos do tipo atingem, e a mesma fração em palavras.

        Args:
            extent: base de medida do tipo na régua (valor, serviços, itens, fotos ou documentos).
            fs: apontamentos do tipo.
            m: o que o fornecedor enviou.

        Returns:
            (fração entre 0 e 1, texto como "2 de 6 fotos"); (1.0, "") quando não há base para medir.
        """
        # Valor: R$ em questão sobre o total do orçamento.
        if extent == Extent.VALUE:
            amount = sum(f.amount_at_issue for f in fs)
            if m.total_value <= 0 or amount <= 0:
                return 1.0, ""
            share = min(1.0, amount / m.total_value)
            return share, f"{100 * share:.0f}% do orçamento"
        # Serviços: pedidos sem item contam inteiro, cobertos em parte contam metade (mínimo de meio serviço).
        if extent == Extent.SERVICES:
            if m.services <= 0:
                return 1.0, ""
            hit = m.services_missing + 0.5 * m.services_partial
            share = min(1.0, max(hit, 0.5) / m.services)
            parts = [f"{m.services_missing} sem item"] if m.services_missing else []
            parts += [f"{m.services_partial} só em parte"] if m.services_partial else []
            return (
                share,
                f"{' e '.join(parts) or 'serviços'} de {_plural(m.services, 'serviço pedido', 'serviços pedidos')}",
            )
        # Itens, fotos e documentos: quantos distintos foram atingidos sobre o total enviado.
        # (itens: os números citados na referência, ex. "itens 2, 5"; fotos e documentos: o nome do arquivo)
        if extent == Extent.ITEMS:
            hit = len({n for f in fs for n in re.findall(r"\d+", f.reference)}) or len(
                fs
            )
            total, one, many = m.items, "item", "itens"
        elif extent == Extent.PHOTOS:
            hit, total, one, many = (
                len({f.reference or str(i) for i, f in enumerate(fs)}),
                m.photos,
                "foto",
                "fotos",
            )
        elif extent == Extent.DOCUMENTS:
            hit, total, one, many = (
                len({f.reference or str(i) for i, f in enumerate(fs)}),
                m.documents,
                "documento",
                "documentos",
            )
        else:
            return 1.0, ""
        if total <= 0:
            return 1.0, ""
        hit = min(hit, total)
        return hit / total, f"{hit:g} de {_plural(total, one, many)}"

    def materiality_findings(
        self,
        findings: list[Finding],
        amount_at_issue_pct: float,
        total: float = 0.0,
        amount: float = 0.0,
    ) -> list[Finding]:
        """Valor em questão limita a nota de Orçamento a 100 − % em questão: desconta o que falta para chegar ao teto.

        Cada tipo desconta uma vez por validação; sem isto, seis itens com o mesmo problema pesariam como um só,
        mesmo com metade do orçamento em questão.

        Args:
            findings: apontamentos já proporcionais (sem o de materialidade).
            amount_at_issue_pct: % do orçamento em questão (0–100).
            total: valor total do orçamento em R$, só para a evidência.
            amount: valor em questão em R$, só para a evidência.

        Returns:
            Lista com um apontamento `relevant_amount_at_issue` cujo desconto leva a nota de Orçamento ao teto
            (100 − %); vazia se o tipo não existe na régua, se o % está abaixo de [relevant_amount_at_issue_pct]
            ou se a nota já está no teto.
        """
        kind = "relevant_amount_at_issue"
        # Tipo desligado na régua, ou % em questão abaixo do mínimo relevante: nada a fazer.
        if (
            kind not in self.rubric.finding_types
            or amount_at_issue_pct <= 0
            or amount_at_issue_pct < self.rubric.relevant_amount_at_issue_pct
        ):
            return []
        # Teto da nota de Orçamento (ex.: 40% em questão → nota no máximo 60) e quanto falta descontar para chegar nele.
        cap = max(0, round(100 - amount_at_issue_pct))
        gap = self._grades(findings)[ValidationResult.QUOTE] - cap
        # Os outros apontamentos já deixaram a nota no teto ou abaixo dele.
        if gap <= 0:
            return []
        value = f" ({brl(amount)} de {brl(total)})" if total else ""
        evidence = f"{amount_at_issue_pct:.0f}% do orçamento em questão{value}: a nota de Orçamento fica limitada a {cap}"
        label = f"{amount_at_issue_pct:.0f}% do orçamento em questão"
        # O desconto é exatamente o que falta para o teto (não a severidade da régua).
        f = self.finding(kind, evidence, "orçamento")
        return [
            f.model_copy(
                update={
                    "discount": gap,
                    "extent": round(min(1.0, amount_at_issue_pct / 100), 3),
                    "extent_label": label,
                }
            )
        ]

    def expected(
        self,
        kinds: list[str],
        amount_at_issue_pct: float = 0.0,
        findings: list[Finding] | None = None,
        measures: Measures | None = None,
    ) -> tuple[list[str], ScoreResult]:
        """Gabarito: tipos esperados (com o de valor relevante, se couber) e o resultado da régua para eles.

        Com `findings` (um por foto, item ou documento atingido) e `measures` (o que o chamado tem), o desconto é
        proporcional como no pipeline; sem eles, cada tipo desconta a severidade inteira.

        Args:
            kinds: tipos de apontamento esperados no chamado (usados quando `findings` é None).
            amount_at_issue_pct: % do orçamento em questão esperado.
            findings: apontamentos esperados, um por coisa atingida; None cria um por tipo de `kinds`.
            measures: o que o chamado tem, para o desconto proporcional; None = desconto cheio.

        Returns:
            (tipos esperados em ordem alfabética, inclusive o de materialidade se couber; resultado da régua).
        """
        if findings is None:
            findings = [
                self.finding(k, "") for k in kinds if k != "relevant_amount_at_issue"
            ]
        findings = self.proportional(
            [f for f in findings if f.kind != "relevant_amount_at_issue"], measures
        )
        findings += self.materiality_findings(findings, amount_at_issue_pct)
        return sorted({f.kind for f in findings}), self.compute(
            findings, amount_at_issue_pct=amount_at_issue_pct
        )

    def reducer_label(self, kind: str) -> str:
        """Rótulo em português de um redutor de confiança (tipo da régua ou redutor extra das etapas)."""
        spec = self.rubric.finding_types.get(kind)
        text = (
            spec.description
            if spec
            else EXTRA_REDUCERS.get(kind, kind.replace("_", " "))
        )
        return text[:1].lower() + text[1:]

    @staticmethod
    def filter_phase(findings: list[Finding], phase: int) -> list[Finding]:
        """Mantém só os apontamentos que valem na fase configurada da régua."""
        return [f for f in findings if f.phase <= phase]

    def absorbers(self, findings: list[Finding]) -> dict[tuple[str, str], str]:
        """(validação, tipo absorvido) → tipo que absorve, para os tipos presentes nos apontamentos.

        Ex.: `missing_after_photo` absorve `photo_mismatch`: a foto de outro ambiente e a falta da foto do depois
        costumam ser o mesmo problema; descontar os dois puniria duas vezes.
        """
        present = {(f.validation.value, f.kind) for f in findings}
        out: dict[tuple[str, str], str] = {}
        for validation, kind in sorted(present):
            spec = self.rubric.finding_types.get(kind)
            for absorbed in spec.absorbs if spec else []:
                if absorbed != kind and (validation, absorbed) in present:
                    out.setdefault((validation, absorbed), kind)
        return out

    def mark_absorbed(self, findings: list[Finding]) -> list[Finding]:
        """Cópias dos apontamentos com `absorbed_by` preenchido (para o parecer e o painel)."""
        by = self.absorbers(findings)
        return [
            f.model_copy(
                update={"absorbed_by": by.get((f.validation.value, f.kind), "")}
            )
            for f in findings
        ]

    def compute(
        self,
        findings: list[Finding],
        extra_reducers: list[str] | None = None,
        amount_at_issue_pct: float = 0.0,
    ) -> ScoreResult:
        """Notas, score, confiança e recomendação a partir dos apontamentos.

        Cada tipo desconta uma vez por validação (como no simulador do deck); todos seguem listados como evidência.
        Tipos absorvidos por outro presente na mesma validação (`absorbs` na régua) não descontam.

        Variáveis principais:
            grades: nota 0–100 de cada validação (escopo, orçamento, fotos) = 100 − soma dos descontos dos tipos.
            score: média das notas ponderada por [weights] da régua.
            reducers: tipos que reduzem a confiança + redutores extras das etapas; a contagem define a confiança.

        Args:
            findings: apontamentos finais (proporcionais, filtrados pela fase, com materialidade).
            extra_reducers: redutores de confiança que não são apontamentos (ex.: "unreadable_quote").
            amount_at_issue_pct: % do orçamento em questão, usado nas regras de recomendação.

        Returns:
            Notas, score, confiança, redutores, recomendação e o motivo da recomendação.
        """
        # Nota 0–100 de cada validação (Escopo, Orçamento, Fotos).
        grades = self._grades(findings)
        # Score = média das notas ponderada pelos pesos da régua.
        score = round(
            sum(grades[v] * self.rubric.weights[v] for v in ValidationResult)
            / sum(self.rubric.weights.values())
        )
        # Confiança: quanto mais motivos de incerteza na entrada, menor (alta / média / baixa).
        reducers = sorted(
            {f.kind for f in findings if f.reduces_confidence}
            | set(extra_reducers or [])
        )
        confidence = self._confidence(len(reducers))
        # Recomendação: travas e faltas do fornecedor vêm antes da faixa do score.
        recommendation, reason = self._recommendation(
            findings, score, confidence, reducers, amount_at_issue_pct
        )
        return ScoreResult(
            grades=Grades(**{v.value: n for v, n in grades.items()}),
            score=score,
            confidence=confidence,
            confidence_reducers=reducers,
            recommendation=recommendation,
            recommendation_reason=reason,
        )

    def _grades(self, findings: list[Finding]) -> dict[ValidationResult, int]:
        """Nota de cada validação: 100 − soma dos descontos, um por tipo, sem os tipos absorvidos (mínimo 0)."""
        # validação → {tipo: desconto}; o dicionário garante que cada tipo desconta uma única vez.
        discounts: dict[ValidationResult, dict[str, int]] = {
            v: {} for v in ValidationResult
        }
        absorbed = self.absorbers(findings)
        for f in findings:
            if (f.validation.value, f.kind) not in absorbed:
                discounts[f.validation][f.kind] = f.discount
        return {v: max(0, 100 - sum(discounts[v].values())) for v in ValidationResult}

    def _confidence(self, n_reducers: int) -> Confidence:
        """Confiança pela quantidade de redutores, com os limites de [confidence] da régua."""
        if n_reducers >= self.rubric.confidence.low_with_n_reducers:
            return Confidence.LOW
        if n_reducers >= self.rubric.confidence.medium_with_n_reducers:
            return Confidence.MEDIUM
        return Confidence.HIGH

    def _recommendation(
        self,
        findings: list[Finding],
        score: int,
        confidence: Confidence,
        reducers: list[str],
        amount_at_issue_pct: float = 0.0,
    ) -> tuple[Recommendation, str]:
        """Recomendação e motivo, pelas regras da régua nesta ordem de prioridade:

        1. trava de integridade (`lock`) → devolver travado, qualquer que seja a nota;
        2. conferência da pessoa analista (`review`, não absorvida; ex.: possível chamado duplicado) → análise
           detalhada: antes de pedir ajuste ao fornecedor, é preciso saber se o chamado deve seguir;
        3. falta do fornecedor (`returns`, não absorvida) → devolver ao fornecedor;
        4. confiança baixa → revisão detalhada;
        5. % em questão ≥ [max_amount_at_issue_for_caveats_pct] → devolver ao fornecedor;
        6. faixa do score ([bands]); "aprovar" com % em questão acima de [max_amount_at_issue_for_approve_pct]
           cai para "aprovar com ressalvas". Confiança média acrescenta o aviso ao motivo.

        Args:
            findings: apontamentos finais.
            score: score ponderado 0–100.
            confidence: confiança calculada.
            reducers: redutores de confiança (para o motivo da revisão detalhada).
            amount_at_issue_pct: % do orçamento em questão.

        Returns:
            (recomendação, motivo em português).
        """
        locks = [f for f in findings if f.lock]
        if locks:  # trava de integridade vence qualquer nota
            return (
                Recommendation.RETURN_LOCKED,
                f"Trava de integridade: {locks[0].description.lower()}. Devolver qualquer que seja a nota",
            )
        absorbed = self.absorbers(findings)
        # conferência da pessoa analista (ex.: outro chamado da agência para o mesmo problema): vem antes de devolver,
        # porque o chamado pode nem precisar seguir
        reviews = [
            f
            for f in findings
            if f.review and (f.validation.value, f.kind) not in absorbed
        ]
        if reviews:
            refs = ", ".join(dict.fromkeys(f.reference for f in reviews if f.reference))
            return (
                Recommendation.DETAILED_REVIEW,
                f"Conferir antes de seguir: {self.reducer_label(reviews[0].kind)}"
                + (f" ({refs})" if refs else ""),
            )
        # falta do fornecedor: o que precisa ajustar já está claro, então volta antes de qualquer análise detalhada
        gaps = list(
            dict.fromkeys(
                self.reducer_label(f.kind)
                for f in findings
                if f.returns and (f.validation.value, f.kind) not in absorbed
            )
        )
        if gaps:
            return (
                Recommendation.RETURN_TO_SUPPLIER,
                f"O fornecedor precisa ajustar: {'; '.join(gaps)}",
            )
        if confidence == Confidence.LOW:
            labels = "; ".join(self.reducer_label(r) for r in reducers)
            return (
                Recommendation.DETAILED_REVIEW,
                f"Confiança baixa ({labels}): entrada insuficiente para concluir",
            )
        # muito do orçamento em questão (com entrada suficiente para concluir): volta para o fornecedor ajustar
        cap = self.rubric.max_amount_at_issue_for_caveats_pct
        if cap and amount_at_issue_pct >= cap:
            return Recommendation.RETURN_TO_SUPPLIER, (
                f"{amount_at_issue_pct:.0f}% do orçamento está em questão (a partir de {cap:g}% volta ao fornecedor): "
                "o fornecedor precisa ajustar"
            )
        # Faixa do score: a de maior nota mínima que o score alcança (ex.: ≥ 85 aprovar, ≥ 70 com ressalvas).
        band = next(
            b
            for b in sorted(self.rubric.bands, key=lambda b: -b.score_min)
            if score >= b.score_min
        )
        limit = self.rubric.max_amount_at_issue_for_approve_pct
        if (
            band.recommendation == Recommendation.APPROVE
            and limit
            and amount_at_issue_pct > limit
        ):
            # nota alta, mas parte relevante do orçamento em questão: não aprova direto
            reason = f"Score {score}, mas {amount_at_issue_pct:.0f}% do orçamento está em questão (acima de {limit:g}%)"
            if confidence == Confidence.MEDIUM:
                reason += "; confiança média: revisar com atenção"
            return Recommendation.APPROVE_WITH_CAVEATS, reason
        reason = BAND_REASONS[band.recommendation]
        if confidence == Confidence.MEDIUM:
            reason += "; confiança média: revisar com atenção"
        return band.recommendation, reason
