"""Cache disque des reponses LLM.

Deux usages, opposes et tous deux legitimes :

- **Reproductibilite d'un rapport** : `temperature` n'existe plus sur Opus 5 et
  Sonnet 5 (parametre retire, 400 si envoye). On ne peut donc pas rendre les
  appels deterministes cote modele. Le cache est le seul moyen de regenerer un
  rapport a l'identique sans le repayer.
- **Mesure de la variance** : elle exige l'inverse. Les passes de variance
  tournent avec le cache desactive (`COUNCIL_CACHE_ENABLED=0`), et c'est une
  mesure voulue, pas un contournement.

La cle inclut le modele ET le niveau d'effort : deux reglages differents sont
deux experiences differentes, jamais la meme entree de cache.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def cache_key(model: str, effort: str, system: str, user: str, schema: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "model": model,
            "effort": effort,
            "system": system,
            "user": user,
            "schema": schema,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, directory: Path, *, enabled: bool = True) -> None:
        self.directory = directory
        self.enabled = enabled
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            return None
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def put(self, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        self._path(key).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
