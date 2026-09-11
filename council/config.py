"""Configuration : tout par variable d'environnement, rien en dur."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
INCIDENTS_PATH = DATA_DIR / "incidents" / "incidents.json"
KB_PATH = DATA_DIR / "kb" / "past_incidents.json"
RESULTS_DIR = PROJECT_ROOT / "results"
CACHE_DIR = PROJECT_ROOT / ".cache"

# Graine unique du projet. La changer change le jeu de donnees, donc invalide
# tous les chiffres deja publies : ne la toucher qu'en connaissance de cause.
DATASET_SEED = 20260911


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COUNCIL_", env_file=".env", extra="ignore")

    model: str = "claude-sonnet-5"
    effort_specialist: str = "low"
    effort_arbiter: str = "high"
    budget_usd: float = 25.0
    cache_enabled: bool = True
    max_clarification_rounds: int = 2


def load_settings() -> Settings:
    return Settings()
