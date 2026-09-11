"""Le plancher : diagnostic deterministe, zero appel LLM.

Ce n'est pas un homme de paille. C'est ce qu'un ingenieur ecrit en une
apres-midi : une dizaine de seuils sur les metriques, une detection de famille
sur le vocabulaire des journaux, et un repli sur le cas passe le plus proche.
Il recoit exactement la meme information que la baseline mono-agent -- y compris
les fiches historiques -- sinon il serait handicape sur onze incidents et le
plancher serait artificiellement bas.

Son role dans le projet : si ce bloc de code atteint le meme taux de reussite
que les agents, le jeu de donnees ne prouve rien et il faut le durcir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from council.agents.retrieval import CaseRetriever
from council.data.audit import log_families
from council.data.taxonomy import CAUSES_OF_FAMILY, RootCause
from council.models import Incident, MetricWindow

# Repli quand absolument rien ne se declenche. Choisi une fois pour toutes :
# c'est la cause la plus frequente dans la vraie vie, pas la plus frequente
# dans ce jeu de donnees -- le plancher n'a pas le droit de connaitre la
# distribution qu'on lui demande de retrouver.
DEFAULT_CAUSE = RootCause.DEPLOY_REGRESSION

Rule = tuple[str, Callable[[MetricWindow], bool], RootCause]


def _max_of(window: MetricWindow, field: str) -> float:
    return max(float(getattr(sample, field)) for sample in window.samples)


def _min_of(window: MetricWindow, field: str) -> float:
    return min(float(getattr(sample, field)) for sample in window.samples)


def _rps_ratio(window: MetricWindow) -> float:
    low = _min_of(window, "rps")
    return _max_of(window, "rps") / low if low > 0 else 1.0


# ORDRE SIGNIFICATIF : du plus specifique au plus general. `rps` passe avant
# `cpu` parce qu'un pic de trafic fait TOUJOURS monter le CPU -- tester le CPU
# d'abord classerait tous les pics de trafic en saturation CPU.
METRIC_RULES: tuple[Rule, ...] = (
    ("disque > 90 %", lambda w: _max_of(w, "disk_pct") > 90.0, RootCause.DISK_FULL),
    (
        "taux de succes du cache < 0,50",
        lambda w: _min_of(w, "cache_hit_ratio") < 0.50,
        RootCause.CACHE_STAMPEDE,
    ),
    (
        "p99 aval > 1000 ms",
        lambda w: _max_of(w, "downstream_p99_ms") > 1000.0,
        RootCause.DOWNSTREAM_TIMEOUT,
    ),
    (
        "attente pool > 300 ms",
        lambda w: _max_of(w, "db_pool_wait_ms") > 300.0,
        RootCause.DB_POOL_EXHAUSTION,
    ),
    (
        "latence reseau > 100 ms",
        lambda w: _max_of(w, "net_latency_ms") > 100.0,
        RootCause.NETWORK_PARTITION,
    ),
    ("trafic multiplie par > 2,5", lambda w: _rps_ratio(w) > 2.5, RootCause.TRAFFIC_SPIKE),
    ("memoire > 90 %", lambda w: _max_of(w, "mem_pct") > 90.0, RootCause.MEMORY_LEAK),
    ("cpu > 90 %", lambda w: _max_of(w, "cpu_pct") > 90.0, RootCause.CPU_SATURATION),
    (
        "deploiement dans la fenetre",
        lambda w: any(change.kind == "deploy" for change in w.changes),
        RootCause.DEPLOY_REGRESSION,
    ),
    (
        "bascule de configuration dans la fenetre",
        lambda w: any(change.kind == "config" for change in w.changes),
        RootCause.CONFIG_CHANGE,
    ),
)


@dataclass(frozen=True)
class KeywordVerdict:
    cause: RootCause
    rule: str


def classify(incident: Incident, retriever: CaseRetriever | None = None) -> KeywordVerdict:
    for name, predicate, cause in METRIC_RULES:
        if predicate(incident.metrics):
            return KeywordVerdict(cause=cause, rule=f"metrique: {name}")

    families = log_families(incident.logs)
    if len(families) == 1:
        family = next(iter(families))
        # Le vocabulaire est partage par les trois causes de la famille : le
        # plancher ne peut pas aller plus loin qu'un choix arbitraire parmi
        # elles. C'est exactement la limite qu'on veut mesurer.
        return KeywordVerdict(cause=CAUSES_OF_FAMILY[family][0], rule=f"journaux: famille {family}")

    if retriever is not None:
        top = retriever.search(incident.history_query(), k=1)
        if top and top[0].score > 0.0:
            return KeywordVerdict(
                cause=top[0].entry.root_cause, rule=f"historique: {top[0].entry.id}"
            )

    return KeywordVerdict(cause=DEFAULT_CAUSE, rule="repli par defaut")
