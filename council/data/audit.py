"""Les trois gardes anti-triche du jeu de donnees.

Un jeu synthetique peut se tricher tout seul de trois facons. Chacune a ici sa
mesure, et chacune est un test qui echoue :

1. **Fuite de signal** : un incident « infra pure » dont les journaux nomment
   deja la cause. Mesure : quelles familles de symptomes chaque vue porte-t-elle,
   confronte a ce que la categorie autorise.
2. **Trop facile** : si une heuristique a base de mots-cles et de seuils suffit,
   comparer un agent unique a trois agents ne prouve rien. Mesure : le taux de
   reussite du plancher, qui doit rester dans [35 %, 60 %] (le hasard est a
   25 % : quatre familles de trois causes).
3. **Recouvrement lexical avec la base historique** : si la fiche passee reprend
   les mots de l'incident, l'agent Historique gagne par copie. Mesure : indice
   de Jaccard median entre la requete de l'incident et la fiche qui le resout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from council.data.taxonomy import (
    FAMILY_OF,
    FAMILY_TOKENS,
    NEUTRAL_BANDS,
    RPS_NEUTRAL_RATIO,
    Category,
    SymptomFamily,
)
from council.models import Dataset, Incident, KnowledgeBase, LogWindow, MetricWindow
from council.text import jaccard, token_set

JACCARD_MAX_MEDIAN = 0.30
FLOOR_MIN = 0.35
FLOOR_MAX = 0.60


def metric_signals(window: MetricWindow) -> set[str]:
    """Ce que la vue « metriques » porte comme signal discriminant.

    Retourne les noms des metriques hors bande neutre, plus `change_event` si la
    fenetre contient un deploiement ou une bascule de configuration.
    `error_rate` est exclue par construction : elle est elevee dans les 45
    incidents, c'est le symptome et non un indice.
    """
    signals: set[str] = set()
    for name, (low, high) in NEUTRAL_BANDS.items():
        values = [getattr(sample, name) for sample in window.samples]
        if low is not None and min(values) < low:
            signals.add(name)
        if high is not None and max(values) > high:
            signals.add(name)
    rps = [sample.rps for sample in window.samples]
    if min(rps) > 0 and max(rps) / min(rps) > RPS_NEUTRAL_RATIO:
        signals.add("rps")
    if window.changes:
        signals.add("change_event")
    return signals


def log_families(window: LogWindow) -> set[SymptomFamily]:
    """Familles de symptomes dont le vocabulaire apparait dans les journaux."""
    tokens: set[str] = set()
    for line in window.lines:
        tokens |= token_set(line.message)
    for trace in window.traces:
        tokens |= token_set(trace.exception)
        for frame in trace.frames:
            tokens |= token_set(frame)
    return {family for family, family_tokens in FAMILY_TOKENS.items() if tokens & family_tokens}


@dataclass
class LeakFinding:
    incident_id: str
    rule: str
    detail: str


@dataclass
class AuditReport:
    leaks: list[LeakFinding] = field(default_factory=list)
    jaccard_values: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def jaccard_median(self) -> float:
        return median(self.jaccard_values.values()) if self.jaccard_values else 0.0

    @property
    def jaccard_max(self) -> float:
        return max(self.jaccard_values.values(), default=0.0)

    @property
    def ok(self) -> bool:
        return not self.leaks and self.jaccard_median < JACCARD_MAX_MEDIAN


def _check_incident(incident: Incident) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    metrics = metric_signals(incident.metrics)
    families = log_families(incident.logs)
    truth_family = FAMILY_OF[incident.root_cause]

    def fail(rule: str, detail: str) -> None:
        findings.append(LeakFinding(incident.id, rule, detail))

    if incident.category is Category.INFRA_PURE:
        if not metrics:
            fail("infra:metriques-muettes", "aucun signal metrique")
        if families:
            fail(
                "infra:fuite-journaux", f"familles trouvees dans les journaux : {sorted(families)}"
            )
    elif incident.category is Category.APP_PURE:
        if metrics:
            fail("app:fuite-metriques", f"signaux metriques : {sorted(metrics)}")
        if families != {truth_family}:
            fail("app:journaux", f"attendu {{{truth_family}}}, trouve {sorted(families)}")
    elif incident.category is Category.HISTORY_REQUIRED:
        if metrics:
            fail("hist:fuite-metriques", f"signaux metriques : {sorted(metrics)}")
        if families:
            fail("hist:fuite-journaux", f"familles trouvees : {sorted(families)}")
    elif incident.category is Category.AMBIGUOUS:
        if not metrics:
            fail("ambigu:metriques-muettes", "le leurre ne laisse aucune trace metrique")
        if families != {truth_family}:
            fail("ambigu:journaux", f"attendu {{{truth_family}}}, trouve {sorted(families)}")
        if incident.decoy_cause is None:
            fail("ambigu:leurre-absent", "decoy_cause manquant")
        elif FAMILY_OF[incident.decoy_cause] is truth_family:
            fail("ambigu:meme-famille", "la verite et le leurre sont dans la meme famille")
        if not incident.dominance_note:
            fail("ambigu:dominance", "aucune justification de la verite terrain")
    return findings


def audit(dataset: Dataset, kb: KnowledgeBase, kb_matches: dict[str, str]) -> AuditReport:
    report = AuditReport()
    by_kb_id = {entry.id: entry for entry in kb.entries}

    for incident in dataset.incidents:
        report.leaks.extend(_check_incident(incident))
        report.counts[incident.category] = report.counts.get(incident.category, 0) + 1

        if incident.category is Category.HISTORY_REQUIRED:
            kb_id = kb_matches.get(incident.id, "")
            entry = by_kb_id.get(kb_id)
            if entry is None:
                report.leaks.append(
                    LeakFinding(incident.id, "hist:fiche-absente", f"KB {kb_id!r} introuvable")
                )
                continue
            if entry.root_cause is not incident.root_cause:
                report.leaks.append(
                    LeakFinding(
                        incident.id,
                        "hist:fiche-incoherente",
                        f"la fiche {kb_id} conclut a {entry.root_cause}",
                    )
                )
            report.jaccard_values[incident.id] = jaccard(
                incident.history_query(), entry.searchable_text()
            )
    return report
