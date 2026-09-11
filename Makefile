.DEFAULT_GOAL := help
UV := uv

.PHONY: help install test lint format dataset dataset-report benchmark clean

help: ## Affiche cette aide
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Installe les dependances (phase 1 : aucun acces reseau requis ensuite)
	$(UV) sync --group dev

install-all: ## Installe tout, y compris anthropic / langgraph / matplotlib
	$(UV) sync --all-extras --group dev

test: ## Lance les tests (hors reseau, 0 $)
	$(UV) run pytest

lint: ## ruff + mypy strict
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy

format: ## Formate le code
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

dataset: ## Regenere data/incidents/ et data/kb/ (deterministe, seed fixe)
	$(UV) run council dataset build

dataset-report: ## Recalcule les 3 gardes anti-triche + le plancher mots-cles
	$(UV) run council dataset audit

benchmark: ## Phase 4
	@echo "Pas encore implemente (phase 4)."

clean: ## Supprime les caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
