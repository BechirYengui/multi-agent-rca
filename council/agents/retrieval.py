"""Recherche dans la base d'incidents passes.

BM25 par defaut, et non des embeddings. La base fait 30 fiches : charger
`sentence-transformers` (~800 Mo avec torch) sur une machine dont la racine est
un disque mecanique, pour trier trente documents, ne se justifie que si BM25
echoue. La mesure qui tranche est le rappel@k des couples (incident,
fiche qui le resout) -- publiee dans `docs/dataset.md`. Le seuil decide
d'avance : sous 0,80 de rappel@3, on ajoute les embeddings et on publie les
deux chiffres.
"""

from __future__ import annotations

from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from council.models import PastIncident
from council.text import tokenize


@dataclass(frozen=True)
class RetrievedCase:
    entry: PastIncident
    score: float


class CaseRetriever:
    def __init__(self, entries: list[PastIncident]) -> None:
        self._entries = entries
        self._bm25 = BM25Okapi([tokenize(entry.searchable_text()) for entry in entries])

    def search(self, query: str, k: int = 3) -> list[RetrievedCase]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(
            zip(self._entries, scores, strict=True), key=lambda pair: pair[1], reverse=True
        )
        return [RetrievedCase(entry=entry, score=float(score)) for entry, score in ranked[:k]]

    def recall_at_k(self, pairs: dict[str, str], queries: dict[str, str], k: int) -> float:
        """Part des couples (incident, fiche attendue) dont la fiche sort dans le top k."""
        if not pairs:
            return 0.0
        hits = 0
        for incident_id, expected_kb_id in pairs.items():
            found = [case.entry.id for case in self.search(queries[incident_id], k=k)]
            hits += int(expected_kb_id in found)
        return hits / len(pairs)
