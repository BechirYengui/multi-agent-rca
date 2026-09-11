"""Trace d'execution : une ligne JSON par transition, relisible sans le code.

Le but n'est pas le confort de debogage, c'est l'auditabilite. Apres coup, on
doit pouvoir reconstituer POURQUOI le systeme a conclu ce qu'il a conclu, sans
relancer un seul appel facture. `council replay <run_id>` ne fait rien d'autre
que relire ce fichier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Tracer:
    run_id: str
    path: Path | None = None
    records: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, incident_id: str, node: str, event: str, **fields: Any) -> None:
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "incident_id": incident_id,
            "node": node,
            "event": event,
            **fields,
        }
        self.records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_trace(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def render_reasoning(records: list[dict[str, Any]], incident_id: str) -> str:
    """Reconstitue le raisonnement d'un incident a partir des seules traces."""
    selected = [r for r in records if r["incident_id"] == incident_id]
    if not selected:
        return f"aucune trace pour {incident_id}"
    lines = [f"# {incident_id}", ""]
    for record in selected:
        node, event = record["node"], record["event"]
        if event == "hypothesis":
            cause = record.get("cause") or "abstention"
            lines.append(
                f"- `{node}` -> **{cause}** (confiance {record.get('confidence', 0):.2f}, "
                f"{record.get('evidence_count', 0)} preuve(s))"
            )
        elif event == "routing":
            lines.append(
                f"- `{node}` -> **{record['route']}** [{record['kind']}] — {record['reason']}"
            )
        elif event == "clarification":
            lines.append(
                f"- `{node}` -> relance {record['round_index']} vers "
                f"`{record['target']}` : {record['question']}"
            )
            verb = "a change d'avis" if record.get("changed_mind") else "maintient"
            answer = record.get("answer_cause") or "abstention"
            lines.append(f"  reponse : {answer} ({verb})")
        elif event == "verdict":
            cause = record.get("cause") or "PAS DE CONSENSUS"
            lines.append(
                f"- `{node}` -> **{cause}** (confiance {record.get('confidence', 0):.2f}, "
                f"{record.get('llm_calls', 0)} appels, {record.get('usd', 0):.4f} $)"
            )
        else:
            lines.append(f"- `{node}` -> {event}")
    return "\n".join(lines) + "\n"
