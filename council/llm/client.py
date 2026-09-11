"""Acces au modele : un seul point de passage, pour que le cout soit comptable.

Tout appel LLM du projet transite par `LLMClient.structured`. C'est ce qui rend
possible trois choses qui, eparpillees, seraient fausses : le plafond de
depense, le cache, et le comptage de jetons par agent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Protocol

from council.budget import BudgetGuard
from council.llm.cache import ResponseCache, cache_key
from council.models import CallUsage

# Estimation hors ligne du nombre de jetons d'entree, pour la verification du
# budget AVANT l'appel. Volontairement pessimiste (3,2 caracteres par jeton au
# lieu des ~3,6 observes en francais) : un disjoncteur doit se declencher trop
# tot, jamais trop tard. Les chiffres publies, eux, viennent de `usage`.
CHARS_PER_TOKEN = 3.2
ASSUMED_OUTPUT_TOKENS = 900


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: str,
        tag: str,
    ) -> tuple[dict[str, Any], CallUsage]: ...


class AnthropicClient:
    """Client reel. Importe `anthropic` paresseusement : les tests n'en ont pas besoin."""

    def __init__(
        self,
        model: str,
        budget: BudgetGuard,
        cache_dir: Path,
        *,
        cache_enabled: bool = True,
        max_tokens: int = 4096,
    ) -> None:
        self.model = model
        self.budget = budget
        self.cache = ResponseCache(cache_dir, enabled=cache_enabled)
        self.max_tokens = max_tokens
        self._client: Any | None = None

    def _api(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depend de l'extra `llm`
                raise LLMError(
                    "le paquet `anthropic` n'est pas installe : `uv sync --all-extras`"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: str,
        tag: str,
    ) -> tuple[dict[str, Any], CallUsage]:
        key = cache_key(self.model, effort, system, user, schema)
        cached = self.cache.get(key)
        if cached is not None:
            self.budget.record_cache_hit()
            return cached["payload"], CallUsage(
                model=self.model,
                input_tokens=cached["usage"]["input_tokens"],
                output_tokens=cached["usage"]["output_tokens"],
                usd=0.0,
                latency_ms=0.0,
                from_cache=True,
            )

        # Verification AVANT l'appel : un depassement doit couter l'appel qu'on
        # n'a pas fait, pas celui qu'on vient de payer.
        from council.budget import cost_usd

        projected = cost_usd(self.model, estimate_tokens(system + user), ASSUMED_OUTPUT_TOKENS)
        self.budget.check(projected)

        started = time.perf_counter()
        response = self._api().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": schema},
        )
        latency_ms = (time.perf_counter() - started) * 1000

        if response.stop_reason == "refusal":  # pragma: no cover - rare
            raise LLMError(f"refus du modele sur {tag} : {response.stop_details}")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:  # pragma: no cover - le format json_schema le garantit
            raise LLMError(f"aucun bloc texte dans la reponse pour {tag}")
        payload: dict[str, Any] = json.loads(text)

        usd = self.budget.record(
            self.model, response.usage.input_tokens, response.usage.output_tokens
        )
        usage = CallUsage(
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            usd=usd,
            latency_ms=latency_ms,
            from_cache=False,
        )
        self.cache.put(
            key,
            {
                "tag": tag,
                "payload": payload,
                "usage": {
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                },
            },
        )
        return payload, usage


class RecordedCall:
    __slots__ = ("effort", "schema", "system", "tag", "user")

    def __init__(self, system: str, user: str, schema: dict[str, Any], effort: str, tag: str):
        self.system = system
        self.user = user
        self.schema = schema
        self.effort = effort
        self.tag = tag


class FakeClient:
    """Client simule : aucun reseau, aucune cle, aucun cout.

    Il enregistre les invites emises. C'est ce qui permet a
    `tests/test_isolation.py` d'affirmer non pas que les vues sont etanches en
    theorie, mais que ce qui part vraiment vers l'API ne contient pas la verite
    terrain.
    """

    def __init__(
        self,
        responder: Any,
        model: str = "claude-sonnet-5",
        *,
        input_tokens: int = 1000,
        output_tokens: int = 400,
    ) -> None:
        self.model = model
        self._responder = responder
        self.calls: list[RecordedCall] = []
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens

    def structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        effort: str,
        tag: str,
    ) -> tuple[dict[str, Any], CallUsage]:
        self.calls.append(RecordedCall(system, user, schema, effort, tag))
        payload: dict[str, Any] = self._responder(system=system, user=user, tag=tag)
        return payload, CallUsage(
            model=self.model,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            usd=0.0,
            latency_ms=0.0,
            from_cache=False,
        )
