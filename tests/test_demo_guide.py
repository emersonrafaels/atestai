"""Guia de demonstração (data/demo_guide.toml): coerente com os chamados e com a régua."""

import json

from atest.config import load_settings
from atest.demo_guide import load_demo_guide


def test_demo_guide_covers_salesforce_cases():
    cfg = load_settings()
    guide = load_demo_guide(cfg.data_dir / "demo_guide.toml")
    datasets = {
        p.parent.name: json.loads(p.read_text(encoding="utf-8")).get("dataset")
        for p in cfg.tickets_dir.glob("*/ticket.json")
    }
    casos = {tid for tid, d in datasets.items() if d == "casos"}
    ids = [c.id for c in guide.cases]
    assert len(ids) == len(set(ids)), "chamado repetido no guia"
    assert (
        set(ids) == casos
    ), "o roteiro deve cobrir todos os Casos Salesforce, e só eles"
    groups = {g.id for g in guide.groups}
    kinds = set(cfg.rubric.finding_types)
    for c in guide.cases:
        assert c.group in groups, c.id
        assert c.expect and c.show, c.id
        assert set(c.findings) <= kinds, (c.id, set(c.findings) - kinds)
        assert set(c.linked) <= set(datasets), (c.id, set(c.linked) - set(datasets))
    assert {"scenarios", "validation", "itau", "casos"} <= set(guide.datasets)


def test_missing_guide_is_empty(tmp_path):
    g = load_demo_guide(tmp_path / "nao_existe.toml")
    assert not g.cases and not g.datasets
