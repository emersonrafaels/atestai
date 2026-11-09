"""Persistência em SQLite: execuções, pareceres, chamadas ao modelo, feedback do modo copiloto e validações.

SQLite atende ao piloto (um arquivo, sem servidor). Para produção, o mesmo esquema migra para Postgres.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .domain import Assessment, Recommendation

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
    mode TEXT NOT NULL, batch_mode TEXT NOT NULL, phase INTEGER NOT NULL, environment TEXT,
    models TEXT NOT NULL, tickets TEXT NOT NULL,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0, cost_brl REAL DEFAULT 0,
    evaluation TEXT, errors TEXT, output_folder TEXT, batches TEXT, label TEXT, signature TEXT, validation TEXT
);
CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ticket_id TEXT NOT NULL, generated_at TEXT NOT NULL,
    workstream TEXT, category TEXT, recommendation TEXT NOT NULL, score INTEGER, confidence TEXT,
    quoted_value REAL, amount_at_issue REAL, cost_usd REAL, cost_brl REAL, duration_s REAL,
    mode TEXT, rubric_version TEXT, prompts_version TEXT, json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assessments_ticket ON assessments(ticket_id);
CREATE INDEX IF NOT EXISTS ix_assessments_run ON assessments(run_id);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id INTEGER REFERENCES assessments(id), run_id TEXT, ticket_id TEXT,
    task TEXT, model TEXT, started_at TEXT, duration_s REAL, input_tokens INTEGER, output_tokens INTEGER,
    cache_read_tokens INTEGER, cache_write_tokens INTEGER, cost_usd REAL, from_cache INTEGER, via_batch INTEGER,
    batch_id TEXT, simulated INTEGER
);
CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, assessment_id INTEGER NOT NULL REFERENCES assessments(id), ticket_id TEXT NOT NULL,
    created_at TEXT NOT NULL, action TEXT NOT NULL, final_decision TEXT, atest_recommendation TEXT,
    unfounded_findings TEXT, comment TEXT, author TEXT
);
"""

# Colunas adicionadas depois da primeira versão do esquema: (tabela, coluna, tipo).
MIGRATIONS: list[tuple[str, str, str]] = []


class FeedbackAction(StrEnum):
    """Decisão da pessoa analista sobre um parecer."""

    ACCEPT = "accept"  # concorda com o parecer
    ADJUST = "adjust"  # concorda em parte: marca apontamentos improcedentes e/ou muda a decisão
    DISAGREE = "disagree"  # discorda da recomendação


class FeedbackInput(BaseModel):
    """Feedback enviado pelo painel."""

    action: FeedbackAction
    final_decision: Recommendation | None = None
    unfounded_findings: list[str] = Field(default_factory=list, description="tipos de apontamento marcados como errados")
    comment: str = Field("", max_length=2000)
    author: str = Field("analyst", max_length=80)


class Feedback(FeedbackInput):
    """Feedback gravado, com o parecer a que se refere."""

    id: int
    assessment_id: int
    ticket_id: str
    created_at: datetime
    atest_recommendation: Recommendation


class Database:
    """Acesso ao banco. Thread-safe: o painel grava de várias execuções em paralelo."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(self.path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA foreign_keys=ON")
        self._con.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        for table, column, kind in MIGRATIONS:
            columns = {r[1] for r in self._con.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                self._con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self._con:
            yield self._con

    def _rows(self, sql: str, args: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._con.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict[str, Any]:
        return self._rows(sql, args)[0]

    # ------------------------------------------------------------------ execuções
    def create_run(
        self,
        run_id: str,
        *,
        mode: str,
        batch_mode: str,
        phase: int,
        environment: str,
        models: dict,
        tickets: list[str],
        label: str = "",
        signature: str = "",
    ) -> None:
        """Registra o início de uma execução."""
        with self._transaction() as c:
            c.execute(
                """INSERT INTO runs (id, created_at, status, mode, batch_mode, phase, environment, models, tickets, label, signature)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    datetime.now().isoformat(),
                    "running",
                    mode,
                    batch_mode,
                    phase,
                    environment,
                    json.dumps(models),
                    json.dumps(tickets),
                    label,
                    signature,
                ),
            )

    def complete_run(
        self,
        run_id: str,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cost_brl: float,
        evaluation: dict | None,
        errors: dict,
        output_folder: str | None,
        batches: list[str],
    ) -> None:
        """Fecha a execução com totais de tokens e custo, avaliação e erros."""
        with self._transaction() as c:
            c.execute(
                """UPDATE runs SET status='completed', completed_at=?, input_tokens=?, output_tokens=?, cost_usd=?, cost_brl=?,
                   evaluation=?, errors=?, output_folder=?, batches=? WHERE id=?""",
                (
                    datetime.now().isoformat(),
                    input_tokens,
                    output_tokens,
                    cost_usd,
                    cost_brl,
                    json.dumps(evaluation) if evaluation else None,
                    json.dumps(errors),
                    output_folder,
                    json.dumps(batches),
                    run_id,
                ),
            )

    def save_validation(self, run_id: str, report: dict) -> None:
        """Guarda o relatório de validação (métricas contra o gabarito) da execução."""
        with self._transaction() as c:
            c.execute("UPDATE runs SET validation=? WHERE id=?", (json.dumps(report, ensure_ascii=False), run_id))

    def validation(self, run_id: str) -> dict | None:
        r = self._rows("SELECT validation FROM runs WHERE id=?", (run_id,))
        return json.loads(r[0]["validation"]) if r and r[0]["validation"] else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Execuções mais recentes, com um resumo da validação (o relatório completo sai em /api/runs/{id}/validation)."""
        rows = self._rows("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            for k in ("models", "tickets", "evaluation", "errors", "batches"):
                r[k] = json.loads(r[k]) if r[k] else None
            v = json.loads(r.pop("validation") or "null")
            r["validation"] = None if v is None else self._validation_summary(v)
        return rows

    @staticmethod
    def _validation_summary(v: dict) -> dict[str, Any]:
        return {
            "n": v["n"],
            "accuracy": v["accuracy"],
            "kappa": v["kappa"],
            "finding_f1": v["findings_micro"]["f1"],
            "problem_catch_f1": v["problem_catch"]["f1"],
            "score_mae": v["score_mae"],
            "gate_passed": v["gate_passed"],
        }

    # ------------------------------------------------------------------ pareceres
    def save_assessment(self, p: Assessment) -> int:
        """Grava o parecer e as chamadas ao modelo; devolve o id do registro (também preenchido em `p.record_id`)."""
        with self._transaction() as c:
            cur = c.execute(
                """INSERT INTO assessments (run_id, ticket_id, generated_at, workstream, category, recommendation, score, confidence,
                   quoted_value, amount_at_issue, cost_usd, cost_brl, duration_s, mode, rubric_version, prompts_version, json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    p.run_id,
                    p.ticket_id,
                    p.generated_at.isoformat(),
                    p.workstream.value,
                    p.category.value,
                    p.recommendation.value,
                    p.score,
                    p.confidence.value if p.confidence else None,
                    p.quoted_value,
                    p.amount_at_issue,
                    p.cost_usd,
                    p.cost_brl,
                    p.duration_s,
                    p.mode,
                    p.rubric_version,
                    p.prompts_version,
                    "{}",
                ),
            )
            pid = int(cur.lastrowid)
            p.record_id = pid
            c.execute("UPDATE assessments SET json=? WHERE id=?", (p.model_dump_json(), pid))
            c.executemany(
                """INSERT INTO llm_calls (assessment_id, run_id, ticket_id, task, model, started_at, duration_s, input_tokens,
                   output_tokens, cache_read_tokens, cache_write_tokens, cost_usd, from_cache, via_batch, batch_id, simulated)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        pid,
                        p.run_id,
                        p.ticket_id,
                        call.task,
                        call.model,
                        call.start.isoformat(),
                        call.duration_s,
                        call.input_tokens,
                        call.output_tokens,
                        call.cache_read_tokens,
                        call.cache_write_tokens,
                        call.cost_usd,
                        int(call.from_cache),
                        int(call.via_batch),
                        call.batch_id,
                        int(call.simulated),
                    )
                    for call in p.llm_calls
                ],
            )
        return pid

    def assessment(self, pid: int) -> Assessment | None:
        r = self._rows("SELECT json FROM assessments WHERE id=?", (pid,))
        return Assessment.model_validate_json(r[0]["json"]) if r else None

    def run_assessments(self, run_id: str) -> list[Assessment]:
        rows = self._rows("SELECT json FROM assessments WHERE run_id=? ORDER BY ticket_id", (run_id,))
        return [Assessment.model_validate_json(r["json"]) for r in rows]

    def ticket_history(self, ticket_id: str) -> list[dict[str, Any]]:
        """Pareceres anteriores do chamado, do mais novo ao mais antigo, com o último feedback de cada um."""
        return self._rows(
            """SELECT p.id, p.run_id, p.generated_at, p.recommendation, p.score, p.mode, p.cost_brl,
                      (SELECT action FROM feedbacks f WHERE f.assessment_id = p.id ORDER BY f.id DESC LIMIT 1) AS feedback
               FROM assessments p WHERE ticket_id=? ORDER BY p.id DESC""",
            (ticket_id,),
        )

    # ------------------------------------------------------------------ feedback
    def save_feedback(self, assessment_id: int, fb: FeedbackInput) -> Feedback:
        """Grava a decisão da pessoa analista. Levanta KeyError se o parecer não existir."""
        p = self.assessment(assessment_id)
        if p is None:
            raise KeyError(assessment_id)
        created = datetime.now()
        with self._transaction() as c:
            cur = c.execute(
                """INSERT INTO feedbacks (assessment_id, ticket_id, created_at, action, final_decision, atest_recommendation,
                   unfounded_findings, comment, author) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    assessment_id,
                    p.ticket_id,
                    created.isoformat(),
                    fb.action.value,
                    fb.final_decision.value if fb.final_decision else None,
                    p.recommendation.value,
                    json.dumps(fb.unfounded_findings),
                    fb.comment,
                    fb.author,
                ),
            )
        return Feedback(
            **fb.model_dump(),
            id=int(cur.lastrowid),
            assessment_id=assessment_id,
            ticket_id=p.ticket_id,
            created_at=created,
            atest_recommendation=p.recommendation,
        )

    def feedbacks(self, assessment_id: int) -> list[Feedback]:
        out = []
        for r in self._rows("SELECT * FROM feedbacks WHERE assessment_id=? ORDER BY id", (assessment_id,)):
            r["unfounded_findings"] = json.loads(r["unfounded_findings"] or "[]")
            out.append(Feedback.model_validate(r))
        return out

    # ------------------------------------------------------------------ métricas (observabilidade + calibração)
    def metrics(self) -> dict[str, Any]:
        """Números da aba Operação: volume, custo, tempo, uso por tarefa e concordância do feedback."""
        general = self._one("""SELECT COUNT(*) AS assessments, COUNT(DISTINCT ticket_id) AS tickets,
                      COALESCE(SUM(CASE WHEN mode='api' THEN cost_usd END),0) AS cost_usd,
                      COALESCE(SUM(CASE WHEN mode='api' THEN cost_brl END),0) AS cost_brl,
                      AVG(CASE WHEN mode='api' THEN cost_brl END) AS avg_cost_brl,
                      AVG(duration_s) AS avg_duration_s,
                      COALESCE(SUM(amount_at_issue),0) AS amount_at_issue FROM assessments""")
        runs = self._one("""SELECT COUNT(*) AS runs,
                          SUM(CASE WHEN errors IS NOT NULL AND errors <> '{}' THEN 1 ELSE 0 END) AS with_errors FROM runs""")
        return {
            **general,
            **runs,
            "by_recommendation": self._rows("SELECT recommendation, COUNT(*) AS n FROM assessments GROUP BY recommendation ORDER BY n DESC"),
            "cost_by_workstream": self._rows("""SELECT workstream, COUNT(*) AS n, SUM(cost_brl) AS cost_brl, AVG(cost_brl) AS avg_brl
                                                 FROM assessments WHERE mode='api' GROUP BY workstream"""),
            "by_task": self._rows("""SELECT task, model, COUNT(*) AS calls, AVG(duration_s) AS avg_duration_s,
                                          SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
                                          SUM(cache_read_tokens) AS cache_read_tokens, SUM(cost_usd) AS cost_usd,
                                          SUM(via_batch) AS via_batch, SUM(from_cache) AS from_cache
                                          FROM llm_calls WHERE simulated=0 GROUP BY task, model ORDER BY cost_usd DESC"""),
            "feedback": self._rows("SELECT action, COUNT(*) AS n FROM feedbacks GROUP BY action"),
            "feedback_agreement": self._one("""SELECT COUNT(*) AS total, SUM(CASE WHEN action='accept' THEN 1 ELSE 0 END) AS accepted,
                                          SUM(CASE WHEN final_decision IS NOT NULL AND final_decision <> atest_recommendation
                                              THEN 1 ELSE 0 END) AS different_decision FROM feedbacks"""),
            "unfounded_findings": self._rows("""SELECT j.value AS kind, COUNT(*) AS n FROM feedbacks f,
                                                    json_each(f.unfounded_findings) j GROUP BY j.value ORDER BY n DESC"""),
            "by_day": self._rows("""SELECT substr(generated_at,1,10) AS day, COUNT(*) AS n, SUM(cost_brl) AS cost_brl
                                       FROM assessments GROUP BY day ORDER BY day"""),
        }
