"""Assemblage des 45 incidents. Deterministe a graine fixee.

Chaque incident tire ses valeurs d'un generateur aleatoire seme sur
`f"{seed}:{incident_id}"` et non sur un flux unique parcouru dans l'ordre :
ajouter un incident au milieu de la table ne doit pas decaler les valeurs de
tous les suivants, sinon les chiffres deja publies changeraient sans raison.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from council.config import DATASET_SEED
from council.data.kb import build_entries
from council.data.specs import SPECS, IncidentSpec
from council.data.taxonomy import Category
from council.data.templates import (
    CHANGE_EVENT_CAUSES,
    LOG_SIGNATURES,
    METRIC_SIGNATURES,
    N_SAMPLES,
    NEUTRAL_LINES,
    SAMPLE_STEP_MIN,
    build_samples,
    change_event,
    neutral_series,
)
from council.models import (
    ChangeEvent,
    Dataset,
    Incident,
    KnowledgeBase,
    LogLine,
    LogWindow,
    MetricWindow,
    StackTrace,
)

GENERATOR_VERSION = "1.0"
_EPOCH = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)


def _rng(seed: int, incident_id: str) -> random.Random:
    return random.Random(f"{seed}:{incident_id}")


def _summary(service: str, rng: random.Random) -> str:
    # Volontairement pauvre et identique en structure pour les 45 : le resume
    # est vu par les trois agents, il ne doit avantager aucun d'eux.
    return (
        f"Taux d'erreur eleve sur {service} depuis {rng.choice([12, 18, 25, 31, 40])} "
        f"minutes, alerte declenchee par la supervision."
    )


def _neutral_log_lines(service: str, rng: random.Random, count: int) -> list[LogLine]:
    lines: list[LogLine] = []
    for _ in range(count):
        level, template = rng.choice(NEUTRAL_LINES)
        message = template.format(ms=rng.randint(8, 240), n=rng.choice([50, 200, 500, 1000]))
        lines.append(
            LogLine(
                minute=rng.randrange(0, N_SAMPLES * SAMPLE_STEP_MIN),
                level=level,  # type: ignore[arg-type]
                service=service,
                message=message,
            )
        )
    return lines


def _build_metrics(spec: IncidentSpec, rng: random.Random) -> MetricWindow:
    series = neutral_series(rng)
    changes: list[ChangeEvent] = []
    if spec.metric_cause is not None:
        METRIC_SIGNATURES[spec.metric_cause](series, rng)
        if spec.metric_cause in CHANGE_EVENT_CAUSES:
            changes.append(change_event(spec.metric_cause, spec.service, rng))
    return MetricWindow(
        service=spec.service,
        window_minutes=N_SAMPLES * SAMPLE_STEP_MIN,
        samples=build_samples(series),
        changes=changes,
    )


def _build_logs(spec: IncidentSpec, rng: random.Random) -> LogWindow:
    lines = _neutral_log_lines(spec.service, rng, rng.randint(6, 9))
    traces: list[StackTrace] = []

    if spec.log_cause is not None:
        signature = LOG_SIGNATURES[spec.log_cause]
        for level, message in signature.lines:
            lines.append(
                LogLine(
                    minute=rng.randrange(15, N_SAMPLES * SAMPLE_STEP_MIN),
                    level=level,  # type: ignore[arg-type]
                    service=spec.service,
                    message=message,
                )
            )
        traces.extend(signature.traces)

    if spec.fingerprint:
        lines.append(
            LogLine(
                minute=rng.randrange(10, N_SAMPLES * SAMPLE_STEP_MIN),
                level="ERROR",
                service=spec.service,
                message=spec.fingerprint,
            )
        )

    lines.sort(key=lambda line: line.minute)
    return LogWindow(service=spec.service, lines=lines, traces=traces)


def build_incident(spec: IncidentSpec, seed: int = DATASET_SEED) -> Incident:
    rng = _rng(seed, spec.id)
    index = int(spec.id.split("-")[1])
    return Incident(
        id=spec.id,
        category=spec.category,
        root_cause=spec.root_cause,
        decoy_cause=spec.decoy_cause,
        dominance_note=spec.dominance,
        service=spec.service,
        started_at=_EPOCH + timedelta(hours=index * 7, minutes=index * 13),
        summary=_summary(spec.service, rng),
        metrics=_build_metrics(spec, rng),
        logs=_build_logs(spec, rng),
    )


def build_dataset(seed: int = DATASET_SEED) -> Dataset:
    return Dataset(
        seed=seed,
        generator_version=GENERATOR_VERSION,
        incidents=[build_incident(spec, seed) for spec in SPECS],
    )


def build_knowledge_base(seed: int = DATASET_SEED) -> KnowledgeBase:
    return KnowledgeBase(seed=seed, generator_version=GENERATOR_VERSION, entries=build_entries())


def expected_counts() -> dict[Category, int]:
    counts: dict[Category, int] = dict.fromkeys(Category, 0)
    for spec in SPECS:
        counts[spec.category] += 1
    return counts
