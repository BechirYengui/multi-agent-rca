"""Les 45 specifications d'incidents, ecrites a la main.

Pourquoi a la main et pas au hasard : la repartition des causes, des categories
et des couples (cause, leurre) est le coeur experimental du jeu de donnees. Un
tirage aleatoire produirait des categories desequilibrees et des couples
ambigus absurdes (une cause et son propre leurre dans la meme famille, ou un
leurre qui explique mieux les faits que la verite terrain). Les VALEURS, elles,
restent tirees au sort a partir de la graine : seule la structure est figee.

Colonnes :
- `metric_cause` : la cause dont la vue « metriques » porte la signature.
  None => vue metriques strictement neutre.
- `log_cause`    : idem pour la vue « journaux ».
- `fingerprint`  : pour la categorie history_required, le motif distinctif
  (temporel ou conditionnel) qui ne nomme AUCUNE cause mais permet de retrouver
  le cas passe. Il ne contient aucun token de FAMILY_TOKENS, sans quoi
  l'incident basculerait de fait dans une autre categorie.
- `dominance`    : pour la categorie ambiguous, la phrase qui justifie que la
  verite terrain est bien celle-la et pas le leurre.
"""

from __future__ import annotations

from dataclasses import dataclass

from council.data.taxonomy import Category
from council.data.taxonomy import RootCause as C


@dataclass(frozen=True)
class IncidentSpec:
    id: str
    category: Category
    root_cause: C
    service: str
    metric_cause: C | None = None
    log_cause: C | None = None
    decoy_cause: C | None = None
    fingerprint: str = ""
    dominance: str = ""
    kb_match: str = ""


def _infra(n: int, cause: C, service: str) -> IncidentSpec:
    return IncidentSpec(
        id=f"INC-{n:03d}",
        category=Category.INFRA_PURE,
        root_cause=cause,
        service=service,
        metric_cause=cause,
        log_cause=None,
    )


def _app(n: int, cause: C, service: str) -> IncidentSpec:
    return IncidentSpec(
        id=f"INC-{n:03d}",
        category=Category.APP_PURE,
        root_cause=cause,
        service=service,
        metric_cause=None,
        log_cause=cause,
    )


def _hist(n: int, cause: C, service: str, fingerprint: str, kb_match: str) -> IncidentSpec:
    return IncidentSpec(
        id=f"INC-{n:03d}",
        category=Category.HISTORY_REQUIRED,
        root_cause=cause,
        service=service,
        metric_cause=None,
        log_cause=None,
        fingerprint=fingerprint,
        kb_match=kb_match,
    )


def _ambig(n: int, truth: C, decoy: C, service: str, dominance: str) -> IncidentSpec:
    """La vue metriques porte le LEURRE, la vue journaux porte la VERITE.

    La regle de dominance est la meme pour les dix : la verite terrain est la
    cause qui explique les DEUX observations ; le leurre n'explique que la
    sienne. C'est ce qui rend le cas difficile mais pas arbitraire.
    """
    return IncidentSpec(
        id=f"INC-{n:03d}",
        category=Category.AMBIGUOUS,
        root_cause=truth,
        service=service,
        metric_cause=decoy,
        log_cause=truth,
        decoy_cause=decoy,
        dominance=dominance,
    )


SPECS: tuple[IncidentSpec, ...] = (
    # --- 12 infra pures : la signature est dans les metriques, les journaux
    #     ne disent rien d'exploitable ------------------------------------------
    _infra(1, C.CPU_SATURATION, "checkout-api"),
    _infra(2, C.CPU_SATURATION, "search-api"),
    _infra(3, C.DISK_FULL, "ingest-worker"),
    _infra(4, C.DISK_FULL, "log-shipper"),
    _infra(5, C.NETWORK_PARTITION, "payment-gateway"),
    _infra(6, C.NETWORK_PARTITION, "session-store"),
    _infra(7, C.TRAFFIC_SPIKE, "catalog-api"),
    _infra(8, C.TRAFFIC_SPIKE, "media-cdn"),
    _infra(9, C.DEPLOY_REGRESSION, "checkout-api"),
    _infra(10, C.DEPLOY_REGRESSION, "notification-svc"),
    _infra(11, C.CONFIG_CHANGE, "auth-svc"),
    _infra(12, C.CONFIG_CHANGE, "pricing-svc"),
    # --- 12 applicatives pures : signature dans les journaux, metriques neutres --
    _app(13, C.MEMORY_LEAK, "order-worker"),
    _app(14, C.MEMORY_LEAK, "report-api"),
    _app(15, C.DEPENDENCY_VERSION_BUG, "billing-api"),
    _app(16, C.DEPENDENCY_VERSION_BUG, "doc-renderer"),
    _app(17, C.DB_POOL_EXHAUSTION, "inventory-api"),
    _app(18, C.DB_POOL_EXHAUSTION, "user-api"),
    _app(19, C.DOWNSTREAM_TIMEOUT, "shipping-api"),
    _app(20, C.DOWNSTREAM_TIMEOUT, "tax-service"),
    _app(21, C.CACHE_STAMPEDE, "recommendation-api"),
    _app(22, C.CACHE_STAMPEDE, "feed-indexer"),
    _app(23, C.CERT_EXPIRY, "partner-gateway"),
    _app(24, C.CERT_EXPIRY, "webhook-dispatcher"),
    # --- 11 necessitant l'historique : les deux vues sont neutres, seul un motif
    #     distinctif permet de retrouver un cas passe --------------------------
    _hist(
        25,
        C.DB_POOL_EXHAUSTION,
        "invoice-api",
        "les echecs arrivent par salves de huit minutes, toutes les six heures, "
        "toujours aux memes heures rondes",
        "KB-03",
    ),
    _hist(
        26,
        C.CERT_EXPIRY,
        "sso-broker",
        "seuls les appels sortants vers un partenaire echouent, et seulement depuis minuit pile",
        "KB-07",
    ),
    _hist(
        27,
        C.CONFIG_CHANGE,
        "geo-router",
        "seuls les clients d'une region geographique sont touches, les autres ne "
        "voient rien du tout",
        "KB-11",
    ),
    _hist(
        28,
        C.CACHE_STAMPEDE,
        "quote-engine",
        "un pic d'echecs a la minute zero de chaque heure, puis retour a la "
        "normale en deux minutes",
        "KB-14",
    ),
    _hist(
        29,
        C.DEPENDENCY_VERSION_BUG,
        "mail-relay",
        "seules les requetes dont la charge utile depasse deux megaoctets "
        "echouent, les petites passent",
        "KB-18",
    ),
    _hist(
        30,
        C.DOWNSTREAM_TIMEOUT,
        "stock-sync",
        "les echecs ne se produisent que pendant la fenetre de traitement "
        "nocturne d'un autre service",
        "KB-21",
    ),
    _hist(
        31,
        C.NETWORK_PARTITION,
        "ledger-api",
        "une instance sur trois seulement est touchee, toujours la meme, et cela "
        "change apres un redemarrage",
        "KB-24",
    ),
    _hist(
        32,
        C.MEMORY_LEAK,
        "report-api",
        "apres chaque redemarrage, quarante minutes sans aucun echec, puis les "
        "memes erreurs reviennent",
        "KB-26",
    ),
    _hist(
        33,
        C.DISK_FULL,
        "log-shipper",
        "les erreurs cessent d'elles-memes au bout de vingt minutes puis "
        "reviennent le lendemain a la meme heure",
        "KB-28",
    ),
    _hist(
        34,
        C.CPU_SATURATION,
        "search-api",
        "un seul serveur du groupe est touche ; retire du service, tout "
        "redevient normal immediatement",
        "KB-29",
    ),
    _hist(
        35,
        C.DEPLOY_REGRESSION,
        "pricing-svc",
        "le probleme revient a chaque fenetre hebdomadaire du jeudi soir, jamais "
        "les autres jours de la semaine",
        "KB-30",
    ),
    # --- 10 ambigus : metriques et journaux pointent vers deux causes
    #     differentes, toutes deux plausibles ---------------------------------
    _ambig(
        36,
        C.DEPENDENCY_VERSION_BUG,
        C.CPU_SATURATION,
        "billing-api",
        "Le bug de la librairie provoque une boucle de decodage : il explique le "
        "CPU a 97 % ET la pile d'exceptions. La saturation CPU seule n'explique "
        "pas le TypeError repete 214 fois.",
    ),
    _ambig(
        37,
        C.MEMORY_LEAK,
        C.DB_POOL_EXHAUSTION,
        "order-worker",
        "Les pauses de ramasse-miettes de 2 s immobilisent les fils qui "
        "detiennent une connexion : l'attente du pool est une consequence de la "
        "fuite. Un pool sous-dimensionne n'expliquerait pas les erreurs "
        "d'allocation repetees 37 fois.",
    ),
    _ambig(
        38,
        C.DB_POOL_EXHAUSTION,
        C.DISK_FULL,
        "inventory-api",
        "Le disque se remplit des journaux d'erreurs produits par l'attente de "
        "connexions : c'est une consequence, pas une cause. L'inverse "
        "n'expliquerait pas une file de 180 demandes.",
    ),
    _ambig(
        39,
        C.CONFIG_CHANGE,
        C.NETWORK_PARTITION,
        "geo-router",
        "La bascule de flag a reroute le trafic vers une zone distante : elle "
        "explique la latence inter-zones ET les rejets. Une vraie partition "
        "toucherait aussi les services voisins, ce qui n'est pas le cas.",
    ),
    _ambig(
        40,
        C.CACHE_STAMPEDE,
        C.CPU_SATURATION,
        "recommendation-api",
        "Le CPU monte parce que 12 400 entrees sont recalculees en meme temps. "
        "Le CPU seul n'expliquerait pas l'effondrement du taux de succes.",
    ),
    _ambig(
        41,
        C.DEPLOY_REGRESSION,
        C.DOWNSTREAM_TIMEOUT,
        "checkout-api",
        "La release a divise par dix le delai d'attente configure : elle "
        "explique les expirations ET leur apparition a la minute du deploiement. "
        "Le service appele, lui, repond au meme rythme qu'hier.",
    ),
    _ambig(
        42,
        C.CERT_EXPIRY,
        C.NETWORK_PARTITION,
        "partner-gateway",
        "Un certificat expire coupe toutes les negociations vers un seul pair, "
        "ce qui ressemble a une partition. Mais la partition toucherait aussi "
        "les autres flux vers la meme zone.",
    ),
    _ambig(
        43,
        C.TRAFFIC_SPIKE,
        C.DB_POOL_EXHAUSTION,
        "catalog-api",
        "Le triplement du trafic sature un pool dimensionne pour la charge "
        "nominale : le pic explique l'attente ET le rejet des requetes en trop. "
        "Un pool sous-dimensionne a trafic constant ne se serait pas manifeste "
        "aujourd'hui seulement.",
    ),
    _ambig(
        44,
        C.DOWNSTREAM_TIMEOUT,
        C.CPU_SATURATION,
        "shipping-api",
        "Le CPU monte a cause des fils d'execution bloques en attente de l'aval. "
        "Une vraie saturation CPU ne laisserait pas le p99 de l'appele a 4 s.",
    ),
    _ambig(
        45,
        C.DISK_FULL,
        C.DEPLOY_REGRESSION,
        "ingest-worker",
        "Le deploiement a active des journaux de debogage qui ont rempli le "
        "disque : la cause operationnelle est le disque plein, et c'est lui "
        "qu'il faut traiter pour retablir le service.",
    ),
)


def kb_matches() -> dict[str, str]:
    """Incident de la categorie `history_required` -> fiche qui le resout.

    Vit ici et non dans la CLI : c'est une propriete du jeu de donnees, dont le
    garde anti-fuite et la mesure de rappel ont besoin autant que l'interface.
    """
    return {spec.id: spec.kb_match for spec in SPECS if spec.kb_match}
