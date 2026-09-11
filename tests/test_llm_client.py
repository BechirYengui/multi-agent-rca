"""Cache, comptage et disjoncteur : les trois choses qui rendent le cout maitrisable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from council.budget import BudgetExceeded, BudgetGuard, cost_usd
from council.llm.cache import ResponseCache, cache_key
from council.llm.client import AnthropicClient, LLMError
from council.llm.schemas import specialist_schema

PAYLOAD = (
    '{"cause": "disk_full", "confidence": 0.8, "evidence": [], '
    '"alternatives": [], "reasoning": "x"}'
)


class _Block:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Response:
    stop_reason = "end_turn"
    stop_details = None

    def __init__(self, text: str, input_tokens: int = 1200, output_tokens: int = 500) -> None:
        self.content = [_Block(text)]
        self.usage = _Usage(input_tokens, output_tokens)


class _Messages:
    def __init__(self, response: _Response) -> None:
        self._response = response
        self.calls = 0

    def create(self, **_: Any) -> _Response:
        self.calls += 1
        return self._response


class _Api:
    def __init__(self, response: _Response) -> None:
        self.messages = _Messages(response)


def _client(tmp_path: Path, guard: BudgetGuard, api: _Api, **kwargs: Any) -> AnthropicClient:
    client = AnthropicClient("claude-sonnet-5", guard, tmp_path / "llm", **kwargs)
    # Injection deliberee de l'objet API : aucun reseau dans les tests.
    client._client = api
    return client


def _call(client: AnthropicClient) -> tuple[dict[str, Any], Any]:
    return client.structured(
        system="consignes", user="donnees", schema=specialist_schema(), effort="low", tag="t:1"
    )


def test_tarif_valeur_de_reference() -> None:
    # Sonnet 5 : 2 $ / 10 $ par million, releve du 2026-09-11.
    assert cost_usd("claude-sonnet-5", 1_000_000, 0) == pytest.approx(2.0)
    assert cost_usd("claude-sonnet-5", 0, 1_000_000) == pytest.approx(10.0)
    with pytest.raises(KeyError, match="Tarif inconnu"):
        cost_usd("modele-invente", 1, 1)


def test_le_second_appel_identique_ne_coute_rien(tmp_path: Path) -> None:
    guard = BudgetGuard(limit_usd=10.0)
    api = _Api(_Response(PAYLOAD))
    client = _client(tmp_path, guard, api)

    first, usage_first = _call(client)
    second, usage_second = _call(client)

    assert first == second
    assert api.messages.calls == 1, "le second appel aurait du sortir du cache"
    assert usage_first.from_cache is False
    assert usage_second.from_cache is True
    assert usage_second.usd == 0.0
    assert guard.usage.calls == 1
    assert guard.usage.cached_calls == 1


def test_cache_desactive_refait_l_appel(tmp_path: Path) -> None:
    """Le mode utilise pour mesurer la variance entre passes."""
    guard = BudgetGuard(limit_usd=10.0)
    api = _Api(_Response(PAYLOAD))
    client = _client(tmp_path, guard, api, cache_enabled=False)
    _call(client)
    _call(client)
    assert api.messages.calls == 2


def test_la_cle_de_cache_distingue_modele_et_effort() -> None:
    schema = specialist_schema()
    base = cache_key("claude-sonnet-5", "low", "s", "u", schema)
    assert base != cache_key("claude-opus-5", "low", "s", "u", schema)
    assert base != cache_key("claude-sonnet-5", "high", "s", "u", schema)
    assert base == cache_key("claude-sonnet-5", "low", "s", "u", schema)


def test_le_plafond_coupe_AVANT_l_appel(tmp_path: Path) -> None:
    """Un depassement doit couter l'appel qu'on n'a pas fait, pas celui qu'on a paye."""
    guard = BudgetGuard(limit_usd=0.0)
    api = _Api(_Response(PAYLOAD))
    client = _client(tmp_path, guard, api)

    with pytest.raises(BudgetExceeded):
        _call(client)
    assert api.messages.calls == 0
    assert guard.spent_usd == 0.0


def test_le_budget_s_accumule(tmp_path: Path) -> None:
    guard = BudgetGuard(limit_usd=10.0)
    api = _Api(_Response(PAYLOAD))
    client = _client(tmp_path, guard, api, cache_enabled=False)
    _call(client)
    _call(client)
    expected = 2 * cost_usd("claude-sonnet-5", 1200, 500)
    assert guard.spent_usd == pytest.approx(expected)
    assert guard.remaining_usd == pytest.approx(10.0 - expected)


def test_un_refus_du_modele_est_une_erreur_explicite(tmp_path: Path) -> None:
    guard = BudgetGuard(limit_usd=10.0)
    response = _Response(PAYLOAD)
    response.stop_reason = "refusal"
    client = _client(tmp_path, guard, _Api(response))
    with pytest.raises(LLMError, match="refus"):
        _call(client)


def test_le_cache_desactive_n_ecrit_rien(tmp_path: Path) -> None:
    cache = ResponseCache(tmp_path / "vide", enabled=False)
    cache.put("k", {"payload": {}})
    assert cache.get("k") is None
    assert not (tmp_path / "vide").exists()
