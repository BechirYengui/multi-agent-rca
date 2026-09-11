"""Base de connaissances : 30 incidents passes, deja resolus.

Onze d'entre eux sont la reponse d'un incident de la categorie
`history_required` ; les dix-neuf autres sont des distracteurs. Cinq de ces
distracteurs sont des **faux jumeaux** deliberes : meme motif distinctif que la
bonne fiche (periodicite, instance unique, region unique) mais une cause
racine differente. Sans eux, retrouver le bon cas serait trivial et le rappel
mesure en phase 2 ne voudrait rien dire.

Regle d'ecriture, verifiee par `tests/test_leakage.py` : la fiche et l'incident
qu'elle resout sont rediges avec un vocabulaire de surface different (service,
chiffres, tournures). Le rapprochement doit se faire sur la FORME du symptome,
pas sur une repetition de mots.
"""

from __future__ import annotations

from datetime import date

from council.data.taxonomy import RootCause as C
from council.models import PastIncident

_RAW: tuple[tuple[str, str, str, str, str, C, str], ...] = (
    (
        "KB-01",
        "Temps de calcul sature sur le service de recherche",
        "Les temps de reponse ont triple sans que le volume d'appels ne change.",
        "Une requete mal indexee consommait tout le temps de calcul disponible sur "
        "les machines du groupe.",
        "Index ajoute, garde-fou sur la duree maximale d'une requete.",
        C.CPU_SATURATION,
        "2025-11-04",
    ),
    (
        "KB-02",
        "Croissance continue de l'occupation memoire d'un worker",
        "L'occupation grimpait regulierement jusqu'a l'arret brutal du processus, "
        "plusieurs fois par jour.",
        "Un tampon interne conservait chaque message traite sans jamais le liberer.",
        "Liberation explicite apres traitement.",
        C.MEMORY_LEAK,
        "2025-09-17",
    ),
    (
        "KB-03",
        "Rafales d'erreurs periodiques sur le service de facturation",
        "Quatre fois par jour, une rafale d'echecs d'une dizaine de minutes, calee "
        "sur les heures rondes ; le reste du temps, aucun probleme.",
        "Un traitement par lots planifie toutes les six heures ouvrait soixante "
        "connexions simultanees sans les rendre ; le reservoir applicatif restait "
        "vide pendant toute la duree du lot.",
        "Pool dedie au traitement par lots, plafonne a dix connexions.",
        C.DB_POOL_EXHAUSTION,
        "2026-02-11",
    ),
    (
        "KB-04",
        "Expirations en cascade vers un service tiers",
        "Le p99 du service appele est passe de 150 ms a plusieurs secondes.",
        "Le fournisseur avait reduit sa capacite sans prevenir.",
        "Delai d'attente abaisse, disjoncteur et reponse degradee mis en place.",
        C.DOWNSTREAM_TIMEOUT,
        "2025-12-02",
    ),
    (
        "KB-05",
        "Regression introduite par une mise en production",
        "Les erreurs ont commence a la minute exacte de la bascule, sur toutes les "
        "instances a la fois.",
        "Un changement de format de reponse non retro-compatible.",
        "Retour arriere immediat puis correctif.",
        C.DEPLOY_REGRESSION,
        "2026-01-20",
    ),
    (
        "KB-06",
        "Affluence exceptionnelle du lundi matin",
        "Chaque lundi entre huit et dix heures, la charge double et une partie des "
        "appels est rejetee.",
        "Aucune anomalie technique : la frequentation reelle depassait la capacite provisionnee.",
        "Provisionnement calendaire avant la plage concernee.",
        C.TRAFFIC_SPIKE,
        "2025-10-13",
    ),
    (
        "KB-07",
        "Interruption brutale des flux sortants vers un prestataire",
        "A partir de zero heure, la totalite des echanges vers un unique prestataire "
        "externe tombe en echec ; les autres destinations restent saines.",
        "Le certificat presente par le prestataire avait atteint sa date de fin de "
        "validite ; la negociation echouait des la premiere poignee de main.",
        "Chaine mise a jour cote prestataire, supervision de la date de validite.",
        C.CERT_EXPIRY,
        "2026-03-01",
    ),
    (
        "KB-08",
        "Volume de stockage sature sur les machines d'ingestion",
        "Les ecritures echouaient, le service refusait toute nouvelle tache.",
        "Les fichiers intermediaires n'etaient plus purges depuis un changement de chemin.",
        "Purge retablie, alerte a 85 %.",
        C.DISK_FULL,
        "2025-08-29",
    ),
    (
        "KB-09",
        "Perte de communication entre deux zones",
        "Les appels entre deux zones echouaient, plusieurs services sans rapport "
        "etaient touches en meme temps.",
        "Une regle de filtrage deployee par l'equipe reseau bloquait le trafic inter-zones.",
        "Regle annulee.",
        C.NETWORK_PARTITION,
        "2025-07-22",
    ),
    (
        "KB-10",
        "Effondrement du taux de succes du cache produit",
        "Le taux de succes est tombe sous 10 %, le temps de calcul a explose.",
        "Une purge complete avait ete declenchee en pleine journee.",
        "Purge progressive, prechauffage avant ouverture.",
        C.CACHE_STAMPEDE,
        "2026-04-08",
    ),
    (
        "KB-11",
        "Panne limitee a une seule zone commerciale",
        "Les utilisateurs d'un pays voyaient systematiquement une erreur, tandis que "
        "le reste du monde n'observait rien d'anormal.",
        "Un parametre de routage avait ete modifie pour cette zone seulement, lors "
        "d'une operation manuelle non tracee.",
        "Retour au parametre precedent, operation desormais tracee.",
        C.CONFIG_CHANGE,
        "2026-05-19",
    ),
    (
        "KB-12",
        "Reservoir de connexions epuise aux heures de pointe",
        "Les demandes s'accumulaient en file alors que la base repondait en quelques "
        "millisecondes.",
        "Le dimensionnement du reservoir n'avait pas suivi la montee du trafic.",
        "Reservoir redimensionne, file bornee.",
        C.DB_POOL_EXHAUSTION,
        "2025-06-30",
    ),
    (
        "KB-13",
        "Bascule de parametre a l'origine d'un rejet massif",
        "Toutes les requetes ont ete refusees des l'activation d'une option de validation stricte.",
        "L'option rejetait des donnees historiques pourtant valides.",
        "Option desactivee, donnees migrees avant reactivation.",
        C.CONFIG_CHANGE,
        "2026-02-27",
    ),
    (
        "KB-14",
        "Pointe d'erreurs au changement d'heure",
        "Chaque debut d'heure, une pointe d'echecs de quelques minutes, puis tout "
        "rentre dans l'ordre sans aucune intervention.",
        "Toutes les entrees memorisees expiraient a la meme seconde ; des milliers "
        "de calculs identiques repartaient en parallele.",
        "Duree de validite desynchronisee, verrou de recalcul unique.",
        C.CACHE_STAMPEDE,
        "2026-06-05",
    ),
    (
        "KB-15",
        "Poignee de main refusee sur la passerelle interne",
        "Toutes les connexions securisees entrantes ont ete refusees d'un coup.",
        "Le certificat interne n'avait pas ete renouvele avant son terme.",
        "Renouvellement automatise.",
        C.CERT_EXPIRY,
        "2025-05-12",
    ),
    (
        "KB-16",
        "Montee de version d'une bibliotheque d'analyse",
        "Des exceptions inedites apparaissaient dans du code non modifie.",
        "La nouvelle version avait change le type retourne par une fonction publique.",
        "Version figee, adaptation du code appelant.",
        C.DEPENDENCY_VERSION_BUG,
        "2026-01-09",
    ),
    (
        "KB-17",
        "Campagne publicitaire non annoncee",
        "Le nombre d'appels a ete multiplie par cinq en une dizaine de minutes.",
        "Rien d'anormal techniquement : la demande depassait la capacite.",
        "Procedure d'annonce prealable des campagnes.",
        C.TRAFFIC_SPIKE,
        "2025-11-28",
    ),
    (
        "KB-18",
        "Echecs reserves aux envois volumineux",
        "Seuls les envois depassant quelques megaoctets echouaient ; les petits "
        "passaient sans erreur.",
        "Une montee de version de la bibliotheque d'encodage avait change la gestion "
        "des tampons au-dela d'un certain seuil.",
        "Retour a la version precedente, puis correctif amont.",
        C.DEPENDENCY_VERSION_BUG,
        "2026-03-24",
    ),
    (
        "KB-19",
        "Accalmie systematique apres chaque redemarrage",
        "Apres un redemarrage, une demi-heure sans incident, puis les erreurs revenaient.",
        "Le reservoir de connexions repartait vide et se saturait de nouveau au "
        "meme rythme : le redemarrage ne faisait que reculer l'echeance.",
        "Connexions liberees en fin de transaction.",
        C.DB_POOL_EXHAUSTION,
        "2025-10-02",
    ),
    (
        "KB-20",
        "Creneau quotidien d'erreurs en fin de matinee",
        "Tous les jours a la meme heure, une vingtaine de minutes difficiles, puis "
        "un retour a la normale.",
        "Un rapport quotidien declenchait un afflux d'appels concentres sur cette plage.",
        "Rapport etale sur deux heures.",
        C.TRAFFIC_SPIKE,
        "2026-04-30",
    ),
    (
        "KB-21",
        "Echecs cantonnes a la plage de traitement de nuit",
        "Entre deux et quatre heures du matin uniquement, une part importante des "
        "appels n'aboutissait pas.",
        "Le service appele consacrait ses ressources a son traitement nocturne et "
        "repondait au-dela du delai accorde.",
        "Traitement nocturne decale, delai revu.",
        C.DOWNSTREAM_TIMEOUT,
        "2026-05-06",
    ),
    (
        "KB-22",
        "Une machine du groupe systematiquement en cause",
        "Les echecs ne concernaient que les appels servis par une machine precise.",
        "Cette machine se trouvait dans une zone dont la route de retour avait "
        "disparu : elle ne joignait plus ses pairs.",
        "Route retablie.",
        C.NETWORK_PARTITION,
        "2025-09-08",
    ),
    (
        "KB-23",
        "Zone geographique unique touchee",
        "Seuls les utilisateurs d'un continent rencontraient des echecs.",
        "Le point de presence local avait perdu le lien avec la zone principale.",
        "Bascule sur le point de presence de secours.",
        C.NETWORK_PARTITION,
        "2026-06-21",
    ),
    (
        "KB-24",
        "Une instance sur trois isolee du reste du groupe",
        "Un seul membre du groupe presentait des echecs ; apres redemarrage, le "
        "probleme se deplacait sur un autre membre.",
        "La table de routage d'une machine hote ne propageait pas les adresses de "
        "l'autre zone ; l'instance qui y atterrissait perdait le contact.",
        "Table de routage corrigee sur l'hote.",
        C.NETWORK_PARTITION,
        "2026-07-14",
    ),
    (
        "KB-25",
        "Ralentissement d'un fournisseur de calcul de taxes",
        "Les appels sortants mettaient plusieurs secondes, sans erreur locale.",
        "Le fournisseur avait migre son infrastructure la nuit precedente.",
        "Delai releve temporairement, reponse mise en cache.",
        C.DOWNSTREAM_TIMEOUT,
        "2025-12-15",
    ),
    (
        "KB-26",
        "Retour cyclique des erreurs apres chaque redemarrage",
        "Apres un redemarrage, une accalmie d'environ trois quarts d'heure, puis les "
        "memes echecs revenaient a l'identique.",
        "Une structure interne grossissait sans jamais etre videe ; le processus "
        "finissait par ne plus pouvoir allouer quoi que ce soit.",
        "Correction de la retention, redemarrage preventif en attendant.",
        C.MEMORY_LEAK,
        "2026-07-29",
    ),
    (
        "KB-27",
        "Pointe reguliere au debut de chaque heure",
        "Une pointe d'echecs de deux a trois minutes, a chaque changement d'heure.",
        "Une tache planifiee rechargeait les parametres et remplacait une valeur "
        "valide par une valeur vide pendant le rechargement.",
        "Rechargement atomique.",
        C.CONFIG_CHANGE,
        "2026-08-03",
    ),
    (
        "KB-28",
        "Erreurs quotidiennes de courte duree, toujours a la meme heure",
        "Chaque jour a la meme heure, une vingtaine de minutes d'echecs, puis un "
        "retour a la normale sans intervention humaine.",
        "Un export quotidien saturait le volume de stockage jusqu'a ce que la purge "
        "automatique libere la place.",
        "Volume agrandi, purge declenchee avant l'export.",
        C.DISK_FULL,
        "2026-08-17",
    ),
    (
        "KB-29",
        "Un unique serveur en cause dans un groupe sain",
        "Les echecs ne concernaient que les requetes servies par une machine du "
        "groupe ; sortie du groupe, tout redevenait normal immediatement.",
        "Un processus resident consommait la quasi-totalite du temps de calcul de cette machine.",
        "Processus resident supprime, alerte par machine ajoutee.",
        C.CPU_SATURATION,
        "2026-08-25",
    ),
    (
        "KB-30",
        "Incident recurrent cale sur la fenetre de mise en production",
        "Chaque semaine, le meme soir, les erreurs reapparaissaient ; les autres "
        "jours de la semaine, rien.",
        "La mise en production hebdomadaire embarquait une modification fautive "
        "restee non detectee par les tests.",
        "Mise en production bloquee jusqu'a correction, test de non-regression ajoute.",
        C.DEPLOY_REGRESSION,
        "2026-09-02",
    ),
)


def build_entries() -> list[PastIncident]:
    return [
        PastIncident(
            id=kb_id,
            title=title,
            symptoms=symptoms,
            diagnosis=diagnosis,
            resolution=resolution,
            root_cause=cause,
            resolved_on=date.fromisoformat(resolved_on),
        )
        for kb_id, title, symptoms, diagnosis, resolution, cause, resolved_on in _RAW
    ]
