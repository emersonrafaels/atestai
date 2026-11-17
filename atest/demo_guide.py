"""Guia de demonstração (`data/demo_guide.toml`): o que esperar de cada conjunto e o roteiro dos Casos Salesforce.

Os chamados do conjunto `casos` não têm gabarito; o guia guarda o que foi plantado em cada um (o mesmo do LEIAME.txt da
pasta) num formato que o painel mostra na aba Cenários, para lembrar o que mostrar de cada chamado.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

from .domain import Recommendation


class DatasetGuide(BaseModel):
    """O que é um conjunto de chamados e o que esperar dele."""

    label: str
    what: str
    expect: str
    tips: list[str] = Field(default_factory=list)


class GuideGroup(BaseModel):
    """Tema do roteiro (duplicidade, foto reaproveitada...), na ordem de exibição."""

    id: str
    label: str
    description: str = ""


class GuideCase(BaseModel):
    """Roteiro de um chamado: resultado esperado, apontamentos e o que mostrar na tela."""

    id: str
    group: str
    title: str
    expect: list[Recommendation] = Field(
        default_factory=list,
        description="recomendações esperadas; mais de uma = o modelo real pode variar entre elas",
    )
    findings: list[str] = Field(
        default_factory=list, description="tipos de apontamento esperados (régua)"
    )
    show: list[str] = Field(default_factory=list, description="o que mostrar, em ordem")
    linked: list[str] = Field(
        default_factory=list, description="outros chamados que entram na história"
    )
    note: str = ""


class DemoGuide(BaseModel):
    datasets: dict[str, DatasetGuide] = Field(default_factory=dict)
    groups: list[GuideGroup] = Field(default_factory=list)
    cases: list[GuideCase] = Field(default_factory=list)


def load_demo_guide(path: Path) -> DemoGuide:
    """Lê o guia; sem o arquivo, devolve um guia vazio (o painel só não mostra o roteiro)."""
    if not path.exists():
        return DemoGuide()
    with path.open("rb") as f:
        return DemoGuide.model_validate(tomllib.load(f))
