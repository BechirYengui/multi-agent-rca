"""Modeles typees du domaine.

Point non negociable : `Incident.root_cause` est la verite terrain. Elle ne doit
JAMAIS atteindre un agent. Les trois methodes de vue (`infra_view`, `app_view`,
`history_query`) sont le seul chemin autorise vers les agents, et
`tests/test_isolation.py` verifie que leur serialisation ne contient ni la cause,
ni le leurre, ni la categorie.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from council.data.taxonomy import Category, RootCause


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MetricSample(_Frozen):
    minute: int
    cpu_pct: float
    mem_pct: float
    disk_pct: float
    net_latency_ms: float
    downstream_p99_ms: float
    db_pool_wait_ms: float
    cache_hit_ratio: float
    rps: float
    error_rate: float


class ChangeEvent(_Frozen):
    kind: Literal["deploy", "config"]
    minutes_before: int
    service: str
    summary: str


class MetricWindow(_Frozen):
    service: str
    window_minutes: int
    samples: list[MetricSample]
    changes: list[ChangeEvent]


class LogLine(_Frozen):
    minute: int
    level: Literal["INFO", "WARN", "ERROR"]
    service: str
    message: str


class StackTrace(_Frozen):
    exception: str
    frames: list[str]
    occurrences: int


class LogWindow(_Frozen):
    service: str
    lines: list[LogLine]
    traces: list[StackTrace]


class PastIncident(_Frozen):
    """Une fiche de la base de connaissances : un incident passe, deja resolu."""

    id: str
    title: str
    symptoms: str
    diagnosis: str
    resolution: str
    root_cause: RootCause
    resolved_on: date

    def searchable_text(self) -> str:
        return f"{self.title} {self.symptoms} {self.diagnosis}"


class Incident(_Frozen):
    id: str
    category: Category
    root_cause: RootCause
    decoy_cause: RootCause | None = None
    dominance_note: str = ""
    service: str
    started_at: datetime
    summary: str = Field(description="Une ligne neutre, vue par les trois agents")
    metrics: MetricWindow
    logs: LogWindow

    # --- Les seules vues transmissibles a un agent ---------------------------

    def infra_view(self) -> dict[str, object]:
        return {
            "incident_id": self.id,
            "service": self.service,
            "started_at": self.started_at.isoformat(),
            "summary": self.summary,
            "metrics": self.metrics.model_dump(mode="json"),
        }

    def app_view(self) -> dict[str, object]:
        return {
            "incident_id": self.id,
            "service": self.service,
            "started_at": self.started_at.isoformat(),
            "summary": self.summary,
            "logs": self.logs.model_dump(mode="json"),
        }

    def history_query(self) -> str:
        """Ce que l'agent Historique envoie au moteur de recherche.

        Volontairement pauvre : le resume et les messages d'erreur, rien d'autre.
        Ni metriques, ni traces -- l'agent Historique ne doit pas pouvoir refaire
        le travail des deux autres.
        """
        errors = " ".join(line.message for line in self.logs.lines if line.level == "ERROR")
        return f"{self.summary} {errors}".strip()


class Dataset(_Frozen):
    seed: int
    generator_version: str
    incidents: list[Incident]


class KnowledgeBase(_Frozen):
    seed: int
    generator_version: str
    entries: list[PastIncident]


# --------------------------------------------------------------------------- #
# Sorties d'agents (phase 2)
# --------------------------------------------------------------------------- #


class SpecialistName(StrEnum):
    INFRA = "infra"
    APP = "app"
    HISTORY = "history"


class Hypothesis(_Frozen):
    """Ce qu'un specialiste produit, et rien de plus.

    `cause = None` signifie « je n'ai pas de quoi trancher » -- ce n'est pas une
    treizieme cause. La distinction compte pour l'arbitre : un agent qui
    s'abstient n'est pas un agent qui contredit, et les traiter pareil ferait
    passer une absence de donnees pour un desaccord.
    """

    agent: SpecialistName
    cause: RootCause | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str]
    alternatives: list[RootCause] = Field(default_factory=list)
    reasoning: str

    @property
    def abstained(self) -> bool:
        return self.cause is None

    def ranked(self) -> list[RootCause]:
        """Cause principale puis alternatives, sans doublon."""
        out: list[RootCause] = [] if self.cause is None else [self.cause]
        for alternative in self.alternatives:
            if alternative not in out:
                out.append(alternative)
        return out


class CallUsage(_Frozen):
    model: str
    input_tokens: int
    output_tokens: int
    usd: float
    latency_ms: float
    from_cache: bool


class ConsensusKind(StrEnum):
    """Forme de l'accord entre les trois specialistes.

    La distinction `unanimous` / `convergent_partial` n'est pas cosmetique : deux
    agents d'accord et un troisieme qui s'abstient n'est pas la meme chose que
    trois agents d'accord. Le second cas vaut trois voix, le premier deux.
    """

    UNANIMOUS = "unanimous"
    CONVERGENT_PARTIAL = "convergent_partial"
    MAJORITY = "majority"
    SINGLE_SOURCE = "single_source"
    SPLIT = "split"
    NONE = "none"


class Clarification(_Frozen):
    """Une relance de l'arbitre vers l'agent divergent."""

    round_index: int
    target: SpecialistName
    question: str
    answer_cause: RootCause | None
    answer_confidence: float
    changed_mind: bool


class RejectedTrack(_Frozen):
    cause: RootCause
    reason: str


class Track(_Frozen):
    """Une piste d'un rapport sans consensus."""

    cause: RootCause
    confidence: float
    supported_by: list[SpecialistName]
    summary: str


class Verdict(_Frozen):
    """Le rapport final.

    `cause = None` signifie explicitement « pas de consensus ». Ce n'est pas un
    echec du systeme : sur un incident reellement ambigu, c'est la bonne reponse,
    et la phase 4 la compte comme telle.
    """

    incident_id: str
    cause: RootCause | None
    confidence: float = Field(ge=0.0, le=1.0)
    consensus: ConsensusKind
    rejected: list[RejectedTrack] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
    reasoning: str = ""
    rounds: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    latency_ms: float = 0.0
    recommend_human_review: bool = False
