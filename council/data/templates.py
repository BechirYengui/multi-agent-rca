"""Gabarits : formes de metriques et journaux, par cause racine.

Ce qui distingue deux causes d'une meme famille n'est jamais un mot, c'est une
forme temporelle :

- `disk_full` et `memory_leak` montent toutes deux de facon monotone, mais sur
  des metriques differentes ;
- `cpu_saturation` et `traffic_spike` font monter le CPU, mais seul le second
  fait monter `rps` en premier ;
- `db_connection_pool_exhaustion` et `downstream_timeout` produisent tous deux
  des delais, mais l'un dans l'attente locale d'une connexion, l'autre chez le
  service appele -- avec un CPU local plat dans les deux cas.

Un agent qui lit la serie peut trancher ; une expression reguliere, non.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass

from council.data.taxonomy import RootCause
from council.models import ChangeEvent, MetricSample, StackTrace

N_SAMPLES = 12
SAMPLE_STEP_MIN = 5

Series = dict[str, list[float]]


# --------------------------------------------------------------------------- #
# Metriques
# --------------------------------------------------------------------------- #


def neutral_series(rng: random.Random) -> Series:
    """Serie « rien a signaler ».

    Toutes les valeurs sont tirees dans des intervalles bornes, choisis pour
    rester strictement a l'interieur de NEUTRAL_BANDS. On n'utilise pas de
    tirage gaussien : une queue de distribution qui sort de la bande une fois
    sur cent ferait echouer le garde anti-fuite au hasard des graines.
    """
    base_disk = rng.uniform(38.0, 66.0)
    base_rps = rng.choice([180.0, 340.0, 620.0, 1150.0, 2400.0])
    series: Series = {
        "cpu_pct": [rng.uniform(28.0, 52.0) for _ in range(N_SAMPLES)],
        "mem_pct": [rng.uniform(42.0, 64.0) for _ in range(N_SAMPLES)],
        "disk_pct": [base_disk + rng.uniform(-1.0, 1.0) for _ in range(N_SAMPLES)],
        "net_latency_ms": [rng.uniform(3.0, 13.0) for _ in range(N_SAMPLES)],
        "downstream_p99_ms": [rng.uniform(90.0, 205.0) for _ in range(N_SAMPLES)],
        "db_pool_wait_ms": [rng.uniform(1.0, 12.0) for _ in range(N_SAMPLES)],
        "cache_hit_ratio": [rng.uniform(0.90, 0.97) for _ in range(N_SAMPLES)],
        "rps": [base_rps * rng.uniform(0.90, 1.10) for _ in range(N_SAMPLES)],
    }
    # L'incident existe : le taux d'erreur monte dans tous les cas. C'est le
    # symptome, pas un indice -- il n'est pas compte comme metrique discriminante.
    onset = rng.randint(3, 5)
    series["error_rate"] = [
        rng.uniform(0.001, 0.004) if i < onset else rng.uniform(0.04, 0.28)
        for i in range(N_SAMPLES)
    ]
    return series


def _ramp(start: float, end: float, n: int = N_SAMPLES) -> list[float]:
    if n == 1:
        return [end]
    step = (end - start) / (n - 1)
    return [start + step * i for i in range(n)]


def _step(low: float, high: float, onset: int) -> list[float]:
    return [low if i < onset else high for i in range(N_SAMPLES)]


def _sig_cpu_saturation(series: Series, rng: random.Random) -> None:
    # CPU qui sature alors que le trafic ne bouge pas : c'est cela qui separe
    # cette cause d'un pic de trafic.
    series["cpu_pct"] = [v + rng.uniform(-1.5, 1.5) for v in _ramp(58.0, 97.0)]


def _sig_disk_full(series: Series, rng: random.Random) -> None:
    series["disk_pct"] = [min(99.6, v + rng.uniform(-0.3, 0.3)) for v in _ramp(86.0, 99.4)]


def _sig_memory_leak(series: Series, rng: random.Random) -> None:
    series["mem_pct"] = [min(97.0, v + rng.uniform(-1.0, 1.0)) for v in _ramp(61.0, 95.0)]


def _sig_network_partition(series: Series, rng: random.Random) -> None:
    onset = rng.randint(3, 5)
    series["net_latency_ms"] = [
        rng.uniform(4.0, 11.0) if i < onset else rng.uniform(140.0, 320.0) for i in range(N_SAMPLES)
    ]


def _sig_traffic_spike(series: Series, rng: random.Random) -> None:
    # Le trafic monte EN PREMIER, le CPU suit proportionnellement.
    base = series["rps"][0]
    factor = _ramp(1.0, rng.uniform(3.0, 4.2))
    series["rps"] = [base * f * rng.uniform(0.96, 1.04) for f in factor]
    series["cpu_pct"] = [min(96.0, 34.0 * f * rng.uniform(0.97, 1.03)) for f in factor]


def _sig_db_pool(series: Series, rng: random.Random) -> None:
    # L'attente est locale : le service en aval, lui, repond toujours vite.
    series["db_pool_wait_ms"] = [max(1.0, v) for v in _ramp(6.0, rng.uniform(680.0, 1400.0))]
    series["downstream_p99_ms"] = [rng.uniform(90.0, 160.0) for _ in range(N_SAMPLES)]


def _sig_downstream_timeout(series: Series, rng: random.Random) -> None:
    # Miroir du cas precedent : c'est l'aval qui traine, l'attente locale est nulle.
    onset = rng.randint(3, 5)
    series["downstream_p99_ms"] = [
        rng.uniform(100.0, 190.0) if i < onset else rng.uniform(1800.0, 4200.0)
        for i in range(N_SAMPLES)
    ]
    series["db_pool_wait_ms"] = [rng.uniform(1.0, 9.0) for _ in range(N_SAMPLES)]


def _sig_cache_stampede(series: Series, rng: random.Random) -> None:
    onset = rng.randint(4, 6)
    series["cache_hit_ratio"] = [
        rng.uniform(0.91, 0.96) if i < onset else rng.uniform(0.05, 0.32) for i in range(N_SAMPLES)
    ]
    series["cpu_pct"] = _step(rng.uniform(34.0, 46.0), rng.uniform(78.0, 92.0), onset)


def _sig_cert_expiry(series: Series, rng: random.Random) -> None:
    # Bascule nette et totale : rien ne monte progressivement.
    onset = rng.randint(4, 6)
    series["downstream_p99_ms"] = [
        rng.uniform(95.0, 180.0) if i < onset else rng.uniform(265.0, 340.0)
        for i in range(N_SAMPLES)
    ]
    series["error_rate"] = [
        rng.uniform(0.001, 0.003) if i < onset else rng.uniform(0.92, 1.0) for i in range(N_SAMPLES)
    ]


def _sig_change_event(series: Series, rng: random.Random) -> None:
    # Ni deploiement ni bascule de flag ne deforment une metrique systeme :
    # le signal est l'EVENEMENT, correle a la marche du taux d'erreur.
    onset = rng.randint(3, 5)
    series["error_rate"] = [
        rng.uniform(0.001, 0.003) if i < onset else rng.uniform(0.18, 0.46)
        for i in range(N_SAMPLES)
    ]


METRIC_SIGNATURES: dict[RootCause, Callable[[Series, random.Random], None]] = {
    RootCause.CPU_SATURATION: _sig_cpu_saturation,
    RootCause.DISK_FULL: _sig_disk_full,
    RootCause.MEMORY_LEAK: _sig_memory_leak,
    RootCause.NETWORK_PARTITION: _sig_network_partition,
    RootCause.TRAFFIC_SPIKE: _sig_traffic_spike,
    RootCause.DB_POOL_EXHAUSTION: _sig_db_pool,
    RootCause.DOWNSTREAM_TIMEOUT: _sig_downstream_timeout,
    RootCause.CACHE_STAMPEDE: _sig_cache_stampede,
    RootCause.CERT_EXPIRY: _sig_cert_expiry,
    RootCause.DEPLOY_REGRESSION: _sig_change_event,
    RootCause.CONFIG_CHANGE: _sig_change_event,
    RootCause.DEPENDENCY_VERSION_BUG: _sig_change_event,
}

# Causes dont la signature metrique est un evenement de changement.
CHANGE_EVENT_CAUSES = frozenset({RootCause.DEPLOY_REGRESSION, RootCause.CONFIG_CHANGE})


def build_samples(series: Series) -> list[MetricSample]:
    return [
        MetricSample(
            minute=i * SAMPLE_STEP_MIN,
            cpu_pct=round(series["cpu_pct"][i], 1),
            mem_pct=round(series["mem_pct"][i], 1),
            disk_pct=round(series["disk_pct"][i], 1),
            net_latency_ms=round(series["net_latency_ms"][i], 1),
            downstream_p99_ms=round(series["downstream_p99_ms"][i], 1),
            db_pool_wait_ms=round(series["db_pool_wait_ms"][i], 1),
            cache_hit_ratio=round(series["cache_hit_ratio"][i], 3),
            rps=round(series["rps"][i], 1),
            error_rate=round(series["error_rate"][i], 4),
        )
        for i in range(N_SAMPLES)
    ]


def change_event(cause: RootCause, service: str, rng: random.Random) -> ChangeEvent:
    if cause is RootCause.DEPLOY_REGRESSION:
        return ChangeEvent(
            kind="deploy",
            minutes_before=rng.randint(4, 18),
            service=service,
            summary=f"release {rng.randint(2, 9)}.{rng.randint(0, 24)}.{rng.randint(0, 5)} "
            f"({rng.randint(3, 41)} commits)",
        )
    return ChangeEvent(
        kind="config",
        minutes_before=rng.randint(4, 18),
        service=service,
        summary=rng.choice(
            [
                "flag batch_writes bascule sur true",
                "flag strict_validation active a 100 %",
                "parametre max_payload_mb porte de 2 a 32",
                "flag new_pricing_engine ouvert a 100 % du trafic",
            ]
        ),
    )


# --------------------------------------------------------------------------- #
# Journaux
# --------------------------------------------------------------------------- #

# Aucun de ces messages ne doit contenir un token de FAMILY_TOKENS :
# tests/test_leakage.py le verifie a chaque incident genere.
NEUTRAL_LINES: tuple[tuple[str, str], ...] = (
    ("INFO", "requete traitee en {ms} ms"),
    ("INFO", "verification de sante repondue"),
    ("INFO", "lot de {n} messages consomme"),
    ("INFO", "session utilisateur ouverte"),
    ("INFO", "tache planifiee terminee"),
    ("WARN", "reponse degradee renvoyee au client"),
    ("WARN", "nouvelle tentative programmee"),
    ("ERROR", "echec du traitement de la requete (code 500)"),
    ("ERROR", "la requete a ete interrompue avant la fin"),
)


@dataclass(frozen=True)
class LogSignature:
    lines: tuple[tuple[str, str], ...]
    traces: tuple[StackTrace, ...] = ()


LOG_SIGNATURES: dict[RootCause, LogSignature] = {
    RootCause.MEMORY_LEAK: LogSignature(
        lines=(
            ("ERROR", "allocation refusee : plus de memoire disponible pour le processus"),
            ("WARN", "occupation du heap a 94 %, pauses GC de 2,1 s"),
            ("WARN", "RSS du processus en hausse continue depuis 40 minutes"),
        ),
        traces=(
            StackTrace(
                exception="OutOfMemoryError: heap space",
                frames=[
                    "app/order/pipeline.py:212 in accumulate_batch",
                    "app/order/pipeline.py:88 in run",
                    "app/runtime/worker.py:145 in loop",
                ],
                occurrences=37,
            ),
        ),
    ),
    RootCause.CACHE_STAMPEDE: LogSignature(
        lines=(
            ("ERROR", "taux de succes du cache effondre : 6 % sur la derniere minute"),
            ("WARN", "recalcul simultane de 12 400 entrees pour la meme cle"),
            ("WARN", "eviction massive declenchee par le rafraichissement periodique"),
        )
    ),
    RootCause.TRAFFIC_SPIKE: LogSignature(
        lines=(
            ("WARN", "trafic entrant multiplie par 3,4 en dix minutes"),
            ("WARN", "rps au-dessus du seuil d'admission, rejet des requetes en trop"),
            ("INFO", "montee en charge automatique demandee"),
        )
    ),
    RootCause.DEPLOY_REGRESSION: LogSignature(
        lines=(
            ("ERROR", "erreurs apparues a la minute exacte du deploiement de la release"),
            ("WARN", "la version precedente ne presentait pas ce comportement"),
            ("INFO", "rollout termine sur 100 % des instances"),
        )
    ),
    RootCause.CONFIG_CHANGE: LogSignature(
        lines=(
            ("ERROR", "rejet systematique depuis la bascule du flag de configuration"),
            ("WARN", "la configuration chargee differe de celle du demarrage"),
            ("INFO", "rechargement de la configuration effectue"),
        )
    ),
    RootCause.DEPENDENCY_VERSION_BUG: LogSignature(
        lines=(
            ("ERROR", "exception levee a l'interieur de la librairie tierce, version 3.4.1"),
            ("WARN", "le comportement differe de la version 3.3.9 utilisee la veille"),
        ),
        traces=(
            StackTrace(
                exception="TypeError: expected bytes, got str",
                frames=[
                    "site-packages/parseq/codec.py:311 in decode_frame",
                    "site-packages/parseq/reader.py:77 in read",
                    "app/billing/import.py:54 in ingest",
                ],
                occurrences=214,
            ),
        ),
    ),
    RootCause.DB_POOL_EXHAUSTION: LogSignature(
        lines=(
            ("ERROR", "delai depasse en attente d'une connexion dans le pool (30 s)"),
            ("WARN", "pool sature : 50 connexions sur 50 occupees, 180 demandes en file"),
            ("WARN", "la base repond en 12 ms, l'attente est cote client"),
        ),
        traces=(
            StackTrace(
                exception="PoolTimeout: no connection available after 30s",
                frames=[
                    "site-packages/dbkit/pool.py:142 in acquire",
                    "app/inventory/repository.py:61 in fetch_stock",
                    "app/inventory/api.py:29 in get_stock",
                ],
                occurrences=96,
            ),
        ),
    ),
    RootCause.DOWNSTREAM_TIMEOUT: LogSignature(
        lines=(
            ("ERROR", "timeout de 3 s depasse sur l'appel au service amont"),
            ("WARN", "circuit ouvert vers le fournisseur upstream apres 20 echecs"),
            ("WARN", "aucune attente locale : le temps est passe chez l'appele"),
        )
    ),
    RootCause.NETWORK_PARTITION: LogSignature(
        lines=(
            ("ERROR", "connexion refusee vers les instances de l'autre zone"),
            ("WARN", "partition suspectee : 2 zones sur 3 injoignables entre elles"),
            ("WARN", "plusieurs services sans rapport signalent le meme symptome"),
        )
    ),
    RootCause.CPU_SATURATION: LogSignature(
        lines=(
            ("ERROR", "cpu du noeud a 98 %, file d'execution saturee"),
            ("WARN", "throttling applique par le noeud sur le conteneur"),
            ("WARN", "le volume de requetes est pourtant identique a hier"),
        )
    ),
    RootCause.DISK_FULL: LogSignature(
        lines=(
            ("ERROR", "ecriture impossible : plus d'espace disque sur /var"),
            ("WARN", "disque a 99 %, inodes bientot epuises"),
            ("INFO", "purge des fichiers temporaires demandee"),
        )
    ),
    RootCause.CERT_EXPIRY: LogSignature(
        lines=(
            ("ERROR", "echec du handshake tls : le certificat du pair a expire"),
            ("WARN", "aucune negociation tls n'aboutit depuis la bascule"),
            ("WARN", "toutes les requetes echouent, aucune ne passe"),
        )
    ),
}
