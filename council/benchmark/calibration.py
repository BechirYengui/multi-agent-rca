"""Mesure de chaque specialiste SEUL -- l'etape qui conditionne la phase 3.

Deux questions, et la reponse a la seconde decide de la conception de l'arbitre :

1. **Chaque agent est-il bon sur SA categorie ?** Si l'agent Application echoue
   sur les incidents applicatifs purs, aucun arbitre ne rattrapera ca, et il vaut
   mieux le savoir avant d'ecrire le graphe.
2. **La confiance annoncee porte-t-elle une information ?** L'arbitre route
   dessus. Si les trois agents annoncent plus de 0,8 sur plus de 80 % des cas, la
   regle de routage est batie sur du sable. Le repli est prevu dans le plan :
   faire deriver la confiance du nombre de preuves citees plutot que d'une
   auto-evaluation, puis re-mesurer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from council.agents.base import Specialist
from council.benchmark.stats import (
    ReliabilityBin,
    brier_score,
    reliability_bins,
    wilson_interval,
)
from council.data.taxonomy import Category
from council.llm.client import LLMClient
from council.models import Dataset, Incident

# Seuil au-dela duquel on considere que la confiance ne discrimine plus rien.
FLAT_CONFIDENCE_SHARE = 0.80
FLAT_CONFIDENCE_LEVEL = 0.80


@dataclass(frozen=True)
class SpecialistRecord:
    incident_id: str
    category: str
    truth: str
    agent: str
    cause: str | None
    confidence: float
    abstained: bool
    correct: bool
    truth_in_top3: bool
    evidence_count: int
    input_tokens: int
    output_tokens: int
    usd: float
    latency_ms: float
    from_cache: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _record(
    incident: Incident, specialist: Specialist, client: LLMClient, effort: str
) -> SpecialistRecord:
    hypothesis, usage = specialist.analyse(incident, client, effort)
    return SpecialistRecord(
        incident_id=incident.id,
        category=incident.category.value,
        truth=incident.root_cause.value,
        agent=hypothesis.agent.value,
        cause=None if hypothesis.cause is None else hypothesis.cause.value,
        confidence=hypothesis.confidence,
        abstained=hypothesis.abstained,
        correct=hypothesis.cause is incident.root_cause,
        truth_in_top3=incident.root_cause in hypothesis.ranked(),
        evidence_count=len(hypothesis.evidence),
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        usd=usage.usd,
        latency_ms=usage.latency_ms,
        from_cache=usage.from_cache,
    )


def run_calibration(
    dataset: Dataset,
    specialists: Sequence[Specialist],
    client: LLMClient,
    effort: str = "low",
    limit: int | None = None,
) -> list[SpecialistRecord]:
    incidents = dataset.incidents[:limit] if limit else dataset.incidents
    return [
        _record(incident, specialist, client, effort)
        for incident in incidents
        for specialist in specialists
    ]


@dataclass
class AgentReport:
    agent: str
    n: int = 0
    abstentions: int = 0
    correct: int = 0
    top3: int = 0
    brier: float = 0.0
    bins: list[ReliabilityBin] = field(default_factory=list)
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)
    confident_share: float = 0.0
    usd: float = 0.0

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0

    @property
    def accuracy_when_answering(self) -> float:
        answered = self.n - self.abstentions
        return self.correct / answered if answered else 0.0

    @property
    def abstention_rate(self) -> float:
        return self.abstentions / self.n if self.n else 0.0

    @property
    def interval(self) -> tuple[float, float]:
        return wilson_interval(self.correct, self.n)

    @property
    def confidence_is_flat(self) -> bool:
        return self.confident_share > FLAT_CONFIDENCE_SHARE


def summarize(records: list[SpecialistRecord]) -> dict[str, AgentReport]:
    grouped: dict[str, list[SpecialistRecord]] = defaultdict(list)
    for record in records:
        grouped[record.agent].append(record)

    reports: dict[str, AgentReport] = {}
    for agent, items in grouped.items():
        pairs = [(item.confidence, item.correct) for item in items]
        by_category: dict[str, tuple[int, int]] = {}
        for category in Category:
            subset = [item for item in items if item.category == category.value]
            if subset:
                by_category[category.value] = (
                    sum(int(item.correct) for item in subset),
                    len(subset),
                )
        reports[agent] = AgentReport(
            agent=agent,
            n=len(items),
            abstentions=sum(int(item.abstained) for item in items),
            correct=sum(int(item.correct) for item in items),
            top3=sum(int(item.truth_in_top3) for item in items),
            brier=brier_score(pairs),
            bins=reliability_bins(pairs),
            by_category=by_category,
            confident_share=(
                sum(int(item.confidence > FLAT_CONFIDENCE_LEVEL) for item in items) / len(items)
            ),
            usd=sum(item.usd for item in items),
        )
    return reports
