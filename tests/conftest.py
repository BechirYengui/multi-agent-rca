from __future__ import annotations

import pytest

from council.agents.retrieval import CaseRetriever
from council.cli import kb_matches
from council.data.generator import build_dataset, build_knowledge_base
from council.models import Dataset, KnowledgeBase


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return build_dataset()


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    return build_knowledge_base()


@pytest.fixture(scope="session")
def retriever(kb: KnowledgeBase) -> CaseRetriever:
    return CaseRetriever(kb.entries)


@pytest.fixture(scope="session")
def matches() -> dict[str, str]:
    return kb_matches()
