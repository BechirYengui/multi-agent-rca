"""Liste fermee des causes racines, familles de symptomes, et bandes neutres.

Deux principes de conception, qui commandent tout le jeu de donnees :

1. **Le vocabulaire de surface est partage a l'interieur d'une famille.**
   Trois causes d'une meme famille produisent les memes mots dans les journaux
   et les memes metriques touchees. Un `grep` ne peut donc jamais depasser le
   niveau de la famille : ce qui distingue les trois causes entre elles est une
   *forme* (croissance monotone, marche d'escalier, correlation a un evenement),
   pas un mot. C'est ce qui empeche le jeu de donnees d'etre resolu par une
   expression reguliere -- et c'est aussi comme cela que se presentent les vrais
   incidents.

2. **`error_rate` n'est pas une metrique discriminante.** Elle est elevee dans
   TOUS les incidents : c'est ce qui fait qu'il y a un incident. Si on la
   comptait comme un signal, aucune vue « metriques » ne serait jamais neutre et
   le garde anti-fuite ne vaudrait rien.
"""

from __future__ import annotations

from enum import StrEnum


class SymptomFamily(StrEnum):
    RESOURCE = "resource"
    CHANGE = "change"
    DEPENDENCY = "dependency"
    PLATFORM = "platform"


class RootCause(StrEnum):
    # RESOURCE
    MEMORY_LEAK = "memory_leak"
    CACHE_STAMPEDE = "cache_stampede"
    TRAFFIC_SPIKE = "traffic_spike"
    # CHANGE
    DEPLOY_REGRESSION = "deploy_regression"
    CONFIG_CHANGE = "config_change"
    DEPENDENCY_VERSION_BUG = "dependency_version_bug"
    # DEPENDENCY
    DB_POOL_EXHAUSTION = "db_connection_pool_exhaustion"
    DOWNSTREAM_TIMEOUT = "downstream_timeout"
    NETWORK_PARTITION = "network_partition"
    # PLATFORM
    CPU_SATURATION = "cpu_saturation"
    DISK_FULL = "disk_full"
    CERT_EXPIRY = "cert_expiry"


class Category(StrEnum):
    INFRA_PURE = "infra_pure"
    APP_PURE = "app_pure"
    HISTORY_REQUIRED = "history_required"
    AMBIGUOUS = "ambiguous"


FAMILY_OF: dict[RootCause, SymptomFamily] = {
    RootCause.MEMORY_LEAK: SymptomFamily.RESOURCE,
    RootCause.CACHE_STAMPEDE: SymptomFamily.RESOURCE,
    RootCause.TRAFFIC_SPIKE: SymptomFamily.RESOURCE,
    RootCause.DEPLOY_REGRESSION: SymptomFamily.CHANGE,
    RootCause.CONFIG_CHANGE: SymptomFamily.CHANGE,
    RootCause.DEPENDENCY_VERSION_BUG: SymptomFamily.CHANGE,
    RootCause.DB_POOL_EXHAUSTION: SymptomFamily.DEPENDENCY,
    RootCause.DOWNSTREAM_TIMEOUT: SymptomFamily.DEPENDENCY,
    RootCause.NETWORK_PARTITION: SymptomFamily.DEPENDENCY,
    RootCause.CPU_SATURATION: SymptomFamily.PLATFORM,
    RootCause.DISK_FULL: SymptomFamily.PLATFORM,
    RootCause.CERT_EXPIRY: SymptomFamily.PLATFORM,
}

CAUSES_OF_FAMILY: dict[SymptomFamily, list[RootCause]] = {
    family: sorted(c for c, f in FAMILY_OF.items() if f == family) for family in SymptomFamily
}

# Vocabulaire de surface, PAR FAMILLE et jamais par cause. Tokens normalises
# (minuscules, sans accents) : voir council.text.tokenize.
FAMILY_TOKENS: dict[SymptomFamily, frozenset[str]] = {
    SymptomFamily.RESOURCE: frozenset(
        {"memoire", "heap", "rss", "cache", "eviction", "recalcul", "saturation", "rps", "trafic"}
    ),
    SymptomFamily.CHANGE: frozenset(
        {
            "deploiement",
            "release",
            "version",
            "rollout",
            "flag",
            "configuration",
            "commit",
            "livraison",
        }
    ),
    SymptomFamily.DEPENDENCY: frozenset(
        {
            "timeout",
            "amont",
            "upstream",
            "pool",
            "connexion",
            "connexions",
            "retry",
            "circuit",
            "partition",
        }
    ),
    SymptomFamily.PLATFORM: frozenset(
        {"disque", "inode", "inodes", "cpu", "certificat", "tls", "handshake", "espace", "noeud"}
    ),
}

ALL_FAMILY_TOKENS: frozenset[str] = frozenset().union(*FAMILY_TOKENS.values())

# Metriques dont une valeur anormale constitue un SIGNAL sur la cause.
# `error_rate` en est volontairement absente (cf. docstring du module).
DISCRIMINANT_METRICS: tuple[str, ...] = (
    "cpu_pct",
    "mem_pct",
    "disk_pct",
    "net_latency_ms",
    "downstream_p99_ms",
    "db_pool_wait_ms",
    "cache_hit_ratio",
    "rps",
)

# Bande dans laquelle une metrique est consideree comme « rien a signaler ».
# (minimum, maximum) ; None = pas de borne de ce cote.
NEUTRAL_BANDS: dict[str, tuple[float | None, float | None]] = {
    "cpu_pct": (None, 70.0),
    "mem_pct": (None, 75.0),
    "disk_pct": (None, 85.0),
    "net_latency_ms": (None, 25.0),
    "downstream_p99_ms": (None, 260.0),
    "db_pool_wait_ms": (None, 25.0),
    "cache_hit_ratio": (0.85, None),
    # rps : la neutralite est RELATIVE (cf. council.data.audit.rps_is_neutral),
    # un service a 200 rps et un autre a 4000 sont tous deux normaux.
    "rps": (None, None),
}

# Variation relative de rps au-dela de laquelle la vue metriques porte un signal.
RPS_NEUTRAL_RATIO = 1.6

LABEL_FR: dict[RootCause, str] = {
    RootCause.MEMORY_LEAK: "fuite memoire",
    RootCause.CACHE_STAMPEDE: "effondrement de cache (stampede)",
    RootCause.TRAFFIC_SPIKE: "pic de trafic legitime",
    RootCause.DEPLOY_REGRESSION: "regression introduite par un deploiement",
    RootCause.CONFIG_CHANGE: "changement de configuration",
    RootCause.DEPENDENCY_VERSION_BUG: "bug dans une dependance mise a jour",
    RootCause.DB_POOL_EXHAUSTION: "epuisement du pool de connexions base",
    RootCause.DOWNSTREAM_TIMEOUT: "lenteur d'un service en aval",
    RootCause.NETWORK_PARTITION: "partition reseau entre zones",
    RootCause.CPU_SATURATION: "saturation CPU",
    RootCause.DISK_FULL: "disque plein",
    RootCause.CERT_EXPIRY: "certificat TLS expire",
}
