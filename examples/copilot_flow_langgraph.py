"""Exemplo: onde o LangGraph entra no Atest.AI.

A análise de um chamado (checklist → escopo → orçamento → fotos → score → parecer) é uma sequência fixa, com regras
determinísticas e saídas estruturadas: um orquestrador simples em Python (atest/pipeline.py) resolve, e o LangGraph só
acrescentaria dependências. O LangGraph passa a valer a pena no fluxo EM VOLTA da análise, que tem o que ele resolve bem:

- pausa para decisão humana (modo copiloto) que pode levar horas ou dias, sem prender processo: `interrupt()`;
- estado durável entre a pausa e a retomada (checkpointer; aqui em memória, em produção Postgres ou SQLite);
- ciclo: a pessoa analista pede complemento, o fornecedor reenvia, o chamado volta para a análise;
- roteamento condicional: só os casos que precisam de gente param na fila.

Rode com `python examples/copilot_flow_langgraph.py` (modo simulado, sem chave). Requer `pip install langgraph`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atest.batch import ComponentFactory  # noqa: E402
from atest.config import load_settings  # noqa: E402
from atest.domain import Recommendation  # noqa: E402
from atest.repository import load_ticket  # noqa: E402

TICKET = "00533402"  # "Verificar porta. Urgente." + foto ilegível → análise detalhada

cfg = load_settings().with_overrides(**{"execution.mode": "simulated", "panel.simulated_delay_s": 0})
orchestrator = ComponentFactory(cfg).orchestrator()


class FlowState(TypedDict, total=False):
    ticket_id: str
    iteration: int
    recommendation: str
    score: int | None
    summary: str
    decision: str
    comment: str
    complement: str
    outcome: str


# --------------------------------------------------------------------------- nós
def analyze(e: FlowState) -> FlowState:
    """O pipeline inteiro do Atest.AI vira UM nó: não há ganho em quebrá-lo em nós do grafo."""
    ch = load_ticket(cfg.tickets_dir / e["ticket_id"])
    p = orchestrator.analyze(ch)
    print(f"  [análise #{e.get('iteration', 0) + 1}] {p.recommendation.label}, score {p.score}")
    return {"iteration": e.get("iteration", 0) + 1, "recommendation": p.recommendation.value, "score": p.score, "summary": p.summary}


def route(e: FlowState) -> Literal["proceed_automatically", "human_review", "send_back_to_supplier"]:
    r = Recommendation(e["recommendation"])
    if r is Recommendation.CHECKLIST_RETURNED:
        return "send_back_to_supplier"  # checklist incompleto volta direto, sem ocupar a pessoa analista
    if r is Recommendation.APPROVE:
        return "proceed_automatically"
    return "human_review"


def human_review(e: FlowState) -> Command[Literal["proceed_automatically", "send_back_to_supplier", "wait_for_complement"]]:
    """Pausa até a pessoa analista decidir. O estado fica no checkpointer; nenhum processo fica esperando."""
    response = interrupt(
        {
            "ticket": e["ticket_id"],
            "recommendation": e["recommendation"],
            "score": e["score"],
            "summary": e["summary"],
            "options": ["approve", "return_to_supplier", "request_complement"],
        }
    )
    target = {"approve": "proceed_automatically", "return_to_supplier": "send_back_to_supplier", "request_complement": "wait_for_complement"}
    return Command(goto=target[response["decision"]], update={"decision": response["decision"], "comment": response.get("comment", "")})


def wait_for_complement(e: FlowState) -> FlowState:
    """Segunda pausa: espera o fornecedor reenviar fotos/documentos; depois o chamado volta para a análise (ciclo)."""
    new = interrupt({"ticket": e["ticket_id"], "request": e.get("comment") or "Enviar complemento"})
    return {"complement": new["description"]}


def proceed_automatically(e: FlowState) -> FlowState:
    return {"outcome": f"segue para pagamento (decisão: {e.get('decision') or 'automática'})"}


def send_back_to_supplier(e: FlowState) -> FlowState:
    return {"outcome": "devolvido ao fornecedor"}


# --------------------------------------------------------------------------- grafo
g = StateGraph(FlowState)
for no in (analyze, human_review, wait_for_complement, proceed_automatically, send_back_to_supplier):
    g.add_node(no.__name__, no)
g.add_edge(START, "analyze")
g.add_conditional_edges("analyze", route)
g.add_edge("wait_for_complement", "analyze")
g.add_edge("proceed_automatically", END)
g.add_edge("send_back_to_supplier", END)
flow = g.compile(checkpointer=InMemorySaver())  # produção: langgraph-checkpoint-postgres, thread_id = id do chamado


if __name__ == "__main__":
    conf = {"configurable": {"thread_id": TICKET}}

    def pause(res: dict) -> dict | None:
        return res["__interrupt__"][0].value if "__interrupt__" in res else None

    print(f"Chamado {TICKET}")
    res = flow.invoke({"ticket_id": TICKET}, conf)
    print("  ⏸ fila da pessoa analista:", pause(res))

    # ... horas depois, a pessoa analista decide pelo painel:
    res = flow.invoke(Command(resume={"decision": "request_complement", "comment": "Enviar foto nítida da mola instalada"}), conf)
    print("  ⏸ aguardando o fornecedor:", pause(res))

    # ... o fornecedor reenvia; o chamado volta para a análise e de novo para a fila:
    res = flow.invoke(Command(resume={"description": "Foto nítida da mola aérea MA-200 instalada"}), conf)
    print("  ⏸ fila da pessoa analista:", pause(res))

    res = flow.invoke(Command(resume={"decision": "approve"}), conf)
    print(f"  ✓ {res['outcome']} após {res['iteration']} análises")
    print("  histórico de estados guardados:", sum(1 for _ in flow.get_state_history(conf)))
