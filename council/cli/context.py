"""Ce que toutes les commandes partagent : chargement, construction, client.

Rassemble ici pour qu'une commande se lise comme ce qu'elle fait, et non comme
la repetition du meme prelude a cinq exemplaires.
"""

from __future__ import annotations

from datetime import UTC, datetime

from council.agents.app import AppSpecialist
from council.agents.base import BaseSpecialist
from council.agents.history import HistorySpecialist
from council.agents.infra import InfraSpecialist
from council.agents.retrieval import CaseRetriever
from council.budget import BudgetGuard
from council.config import CACHE_DIR, INCIDENTS_PATH, KB_PATH, Settings, load_settings
from council.llm.client import AnthropicClient
from council.models import Dataset, KnowledgeBase


def load_dataset() -> Dataset:
    return Dataset.model_validate_json(INCIDENTS_PATH.read_text(encoding="utf-8"))


def load_kb() -> KnowledgeBase:
    return KnowledgeBase.model_validate_json(KB_PATH.read_text(encoding="utf-8"))


def load_retriever() -> CaseRetriever:
    return CaseRetriever(load_kb().entries)


def build_specialists(retriever: CaseRetriever, k: int) -> list[BaseSpecialist]:
    return [InfraSpecialist(), AppSpecialist(), HistorySpecialist(retriever, k=k)]


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def make_client(
    model: str, budget: float, *, no_cache: bool = False
) -> tuple[AnthropicClient, BudgetGuard, Settings]:
    """Construit le client, son disjoncteur et les reglages, d'un seul tenant.

    Les trois vont toujours ensemble : un client sans disjoncteur serait un
    client qui peut vider un compte, et le cache se decide au meme endroit que
    le modele parce que la cle de cache contient le modele.
    """
    settings = load_settings()
    chosen = model or settings.model
    guard = BudgetGuard(limit_usd=budget or settings.budget_usd)
    client = AnthropicClient(
        model=chosen,
        budget=guard,
        cache_dir=CACHE_DIR / "llm",
        cache_enabled=settings.cache_enabled and not no_cache,
    )
    return client, guard, settings
