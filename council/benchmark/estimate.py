"""Chiffrage a blanc : combien couterait un run, AVANT le premier appel facture.

Principe commun aux deux fonctions : **on ne recalcule jamais les invites de son
cote**. On fait tourner le pipeline reel contre un client simule qui enregistre
ce qui serait parti, puis on compte. Un estimateur qui reconstruirait les
invites finirait tot ou tard par mesurer autre chose que ce qui part vraiment --
et ce jour-la, personne ne s'en apercevrait.

Le benchmark retourne un ENCADREMENT et non un point : le nombre d'allers-retours
depend des reponses, donc ne peut pas etre connu d'avance. Un chiffre unique
serait faux par construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from council.agents.base import BaseSpecialist, Specialist
from council.agents.retrieval import CaseRetriever
from council.benchmark.calibration import run_calibration
from council.benchmark.runner import BenchmarkRunner
from council.budget import cost_usd
from council.llm.client import ASSUMED_OUTPUT_TOKENS, FakeClient, estimate_tokens
from council.models import Dataset


@dataclass(frozen=True)
class Estimate:
    calls: int
    input_tokens: int
    output_tokens: int

    def usd(self, model: str) -> float:
        return cost_usd(model, self.input_tokens, self.output_tokens)


def _estimate_from(client: FakeClient) -> Estimate:
    return Estimate(
        calls=len(client.calls),
        input_tokens=sum(estimate_tokens(call.system + call.user) for call in client.calls),
        output_tokens=ASSUMED_OUTPUT_TOKENS * len(client.calls),
    )


# Reponses du client simule. Leur contenu importe peu : seules comptent les
# invites EMISES, dont on mesure la taille.
ABSTAIN: dict[str, Any] = {
    "cause": "insufficient_evidence",
    "confidence": 0.0,
    "evidence": [],
    "alternatives": [],
    "reasoning": "chiffrage a blanc",
}
AGREE: dict[str, Any] = {
    "cause": "disk_full",
    "confidence": 0.8,
    "evidence": ["a", "b"],
    "alternatives": [],
    "reasoning": "r",
}
ARBITER: dict[str, Any] = {
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
        return ARBITER
    if tag.startswith("history"):
        return {**AGREE, "cause": "memory_leak"}
    return AGREE


def estimate_calibration(
    dataset: Dataset, specialists: Sequence[Specialist], effort: str = "low"
) -> Estimate:
    """Les trois specialistes sur les 45 incidents : un appel chacun, sans boucle."""
    client = FakeClient(lambda **_: ABSTAIN)
    run_calibration(dataset, specialists, client, effort)
    return _estimate_from(client)


def estimate_benchmark(
    dataset: Dataset,
    retriever: CaseRetriever,
    specialists: Sequence[BaseSpecialist],
    *,
    out_dir: Path,
    baseline_efforts: Sequence[str] = ("medium", "high"),
    k: int = 5,
    max_rounds: int = 2,
) -> dict[str, Estimate]:
    """Encadre le cout d'un run complet : accord immediat (mini) / divergence tetue (maxi)."""
    out: dict[str, Estimate] = {}
    for label, responder in (
        ("minimum (accord immediat)", lambda **_: AGREE),
        ("maximum (divergence tetue)", _stubborn),
    ):
        client = FakeClient(responder)
        BenchmarkRunner(
            dataset=dataset,
            retriever=retriever,
            specialists=specialists,
            client=client,
            run_id="dry-run",
            out_dir=out_dir,
            baseline_efforts=baseline_efforts,
            k=k,
            max_rounds=max_rounds,
        ).run()
        out[label] = _estimate_from(client)
    return out
