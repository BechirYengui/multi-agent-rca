"""Le harnais : les quatre bras, sur les memes incidents.

Pourquoi quatre et non deux. Comparer « systeme multi-agents » a « agent
unique » ne separe pas deux choses pourtant differentes : **decouper le probleme
en trois vues** et **avoir un arbitre LLM**. Les deux bras intermediaires les
isolent, et l'un des deux ne coute rien :

| Bras | Appels LLM / incident | Ce qu'il isole |
|---|---|---|
| `floor` | 0 | la difficulte reelle du jeu de donnees |
| `baseline` | 1 | l'apport de la decomposition |
| `vote` | 0 (rejoue les hypotheses du conseil) | l'apport de l'arbitre |
| `council` | 3 a 8 | -- |

Si `council` ne bat pas `vote`, l'arbitre ne sert a rien et le rapport le dira.

Ecriture incrementale : chaque ligne est ecrite des qu'elle existe. Un
depassement de budget ou un plantage au 31e incident laisse 30 incidents
exploitables, pas un fichier vide.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from council.agents.arbiter import Arbiter
from council.agents.base import BaseSpecialist
from council.agents.baseline import BaselineAgent
from council.agents.keyword import classify
from council.agents.retrieval import CaseRetriever
from council.budget import BudgetExceeded
from council.llm.client import LLMClient
from council.models import Dataset, Hypothesis, Incident, SpecialistName
from council.orchestration.graph import build_graph, investigate_state
from council.orchestration.trace import Tracer

# Ordre de depart pour departager deux hypotheses de meme confiance dans le bras
# `vote`. Fige pour que le bras soit deterministe -- sinon son score bougerait
# d'une execution a l'autre sans qu'aucun appel LLM n'ait change.
VOTE_TIEBREAK = (SpecialistName.INFRA, SpecialistName.APP, SpecialistName.HISTORY)


@dataclass(frozen=True)
class ArmResult:
    run_id: str
    pass_index: int
    arm: str
    incident_id: str
    category: str
    truth: str
    predicted: str | None
    confidence: float
    consensus: str | None
    rounds: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    usd: float
    latency_ms: float

    @property
    def correct(self) -> bool:
        return self.predicted == self.truth

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def pick_by_confidence(hypotheses: Sequence[Hypothesis]) -> Hypothesis | None:
    """Agregation triviale : l'hypothese la plus confiante, hors abstentions."""
    answered = [h for h in hypotheses if h.cause is not None]
    if not answered:
        return None
    return max(
        answered,
        key=lambda h: (h.confidence, -VOTE_TIEBREAK.index(h.agent)),
    )


class BenchmarkRunner:
    def __init__(
        self,
        dataset: Dataset,
        retriever: CaseRetriever,
        specialists: Sequence[BaseSpecialist],
        client: LLMClient,
        *,
        run_id: str,
        out_dir: Path,
        effort_specialist: str = "low",
        effort_arbiter: str = "high",
        baseline_efforts: Sequence[str] = ("medium", "high"),
        k: int = 5,
        max_rounds: int = 2,
    ) -> None:
        self.dataset = dataset
        self.client = client
        self.run_id = run_id
        self.out_dir = out_dir
        self.baseline = BaselineAgent(retriever, k=k)
        self.baseline_efforts = list(baseline_efforts)
        self.effort_specialist = effort_specialist
        self.tracer = Tracer(run_id=run_id, path=out_dir / "trace.jsonl")
        self.graph = build_graph(
            specialists=specialists,
            arbiter=Arbiter(effort=effort_arbiter),
            client=client,
            tracer=self.tracer,
            effort_specialist=effort_specialist,
            max_rounds=max_rounds,
        )
        self.results: list[ArmResult] = []
        self.partial = False

    # -- un bras, un incident ------------------------------------------------

    def _result(self, incident: Incident, arm: str, pass_index: int, **fields: Any) -> ArmResult:
        base: dict[str, Any] = {
            "confidence": 0.0,
            "consensus": None,
            "rounds": 0,
            "llm_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "usd": 0.0,
            "latency_ms": 0.0,
        }
        base.update(fields)
        return ArmResult(
            run_id=self.run_id,
            pass_index=pass_index,
            arm=arm,
            incident_id=incident.id,
            category=incident.category.value,
            truth=incident.root_cause.value,
            **base,
        )

    def _run_incident(self, incident: Incident, pass_index: int) -> list[ArmResult]:
        out: list[ArmResult] = []

        started = time.perf_counter()
        floor = classify(incident, self.baseline.retriever)
        out.append(
            self._result(
                incident,
                "floor",
                pass_index,
                predicted=floor.cause.value,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        )

        for effort in self.baseline_efforts:
            started = time.perf_counter()
            hypothesis, usage = self.baseline.analyse(incident, self.client, effort)
            out.append(
                self._result(
                    incident,
                    f"baseline@{effort}",
                    pass_index,
                    predicted=None if hypothesis.cause is None else hypothesis.cause.value,
                    confidence=hypothesis.confidence,
                    llm_calls=1,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usd=usage.usd,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            )

        started = time.perf_counter()
        state = investigate_state(self.graph, incident)
        elapsed = (time.perf_counter() - started) * 1000
        verdict = state["verdict"]
        hypotheses: list[Hypothesis] = state["hypotheses"]

        out.append(
            self._result(
                incident,
                "council",
                pass_index,
                predicted=None if verdict.cause is None else verdict.cause.value,
                confidence=verdict.confidence,
                consensus=verdict.consensus.value,
                rounds=verdict.rounds,
                llm_calls=verdict.llm_calls,
                input_tokens=verdict.input_tokens,
                output_tokens=verdict.output_tokens,
                usd=verdict.usd,
                latency_ms=elapsed,
            )
        )

        # Bras `vote` : rejoue les trois hypotheses du PREMIER tour. Zero appel,
        # zero dollar -- il ne consomme que ce que le conseil a deja paye.
        initial = hypotheses[:3]
        winner = pick_by_confidence(initial)
        out.append(
            self._result(
                incident,
                "vote",
                pass_index,
                predicted=None
                if winner is None
                else (winner.cause.value if winner.cause else None),
                confidence=0.0 if winner is None else winner.confidence,
                consensus=None,
            )
        )
        return out

    # -- la campagne ---------------------------------------------------------

    def run(self, passes: int = 1, limit: int | None = None) -> list[ArmResult]:
        incidents = self.dataset.incidents[:limit] if limit else self.dataset.incidents
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / "arms.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for pass_index in range(1, passes + 1):
                for incident in incidents:
                    try:
                        rows = self._run_incident(incident, pass_index)
                    except BudgetExceeded:
                        self.partial = True
                        return self.results
                    for row in rows:
                        handle.write(json.dumps(row.as_dict(), ensure_ascii=False) + "\n")
                    handle.flush()
                    self.results.extend(rows)
        return self.results


def read_results(path: Path) -> list[ArmResult]:
    with path.open(encoding="utf-8") as handle:
        return [ArmResult(**json.loads(line)) for line in handle if line.strip()]


UNANIMOUS_PAYLOAD: dict[str, Any] = {
    "cause": "disk_full",
    "confidence": 0.8,
    "evidence": ["a", "b"],
    "alternatives": [],
    "reasoning": "r",
}
ARBITER_PAYLOAD: dict[str, Any] = {
    "cause": "disk_full",
    "confidence": 0.9,
    "rejected": [],
    "reasoning": "r",
    "question": "une observation de plus ?",
    "rationale": "r",
    "tracks": [],
    "next_step": "n",
}


def _stubborn(*, system: str, user: str, tag: str) -> dict[str, Any]:
    """Scenario le plus cher : l'agent Historique diverge et ne cede jamais."""
    if tag.startswith("arbiter"):
        return ARBITER_PAYLOAD
    if tag.startswith("history"):
        return {**UNANIMOUS_PAYLOAD, "cause": "memory_leak"}
    return UNANIMOUS_PAYLOAD


def estimate_benchmark(
    dataset: Dataset,
    retriever: CaseRetriever,
    specialists: Sequence[BaseSpecialist],
    *,
    out_dir: Path,
    baseline_efforts: Sequence[str] = ("medium", "high"),
    k: int = 5,
    max_rounds: int = 2,
) -> dict[str, tuple[int, int, int]]:
    """Encadre le cout d'un run complet AVANT le premier appel facture.

    Le nombre d'allers-retours depend des reponses : on ne peut pas le connaitre
    d'avance. On donne donc un ENCADREMENT, en rejouant le vrai pipeline contre
    deux clients simules -- l'un ou tout le monde s'accorde du premier coup (le
    moins cher), l'autre ou le divergent s'entete jusqu'au plafond (le plus cher).
    Le run reel tombera entre les deux.

    Retourne, par scenario : (appels, jetons d'entree, jetons de sortie).
    """
    from council.llm.client import ASSUMED_OUTPUT_TOKENS, FakeClient, estimate_tokens

    out: dict[str, tuple[int, int, int]] = {}
    for label, responder in (
        ("minimum (accord immediat)", lambda **_: UNANIMOUS_PAYLOAD),
        ("maximum (divergence tetue)", _stubborn),
    ):
        client = FakeClient(responder)
        runner = BenchmarkRunner(
            dataset=dataset,
            retriever=retriever,
            specialists=specialists,
            client=client,
            run_id="dry-run",
            out_dir=out_dir,
            baseline_efforts=baseline_efforts,
            k=k,
            max_rounds=max_rounds,
        )
        runner.run()
        out[label] = (
            len(client.calls),
            sum(estimate_tokens(call.system + call.user) for call in client.calls),
            ASSUMED_OUTPUT_TOKENS * len(client.calls),
        )
    return out
