# Le jeu de données synthétique — construction et contrôles

Mesures du 2026-09-11, régénérables par `make dataset && make dataset-report`.
Tous les chiffres de ce document sortent de `council dataset audit`, pas d'une
estimation.

---

## 0. Le fait structurant

**Un incident ne se distingue pas d'un autre par un mot, mais par une forme.**

C'est la contrainte qui a commandé toute la construction. Si `memory_leak`
écrivait « fuite mémoire » dans les journaux et `disk_full` « disque plein »,
quarante lignes de `grep` résoudraient les 45 incidents et comparer un agent
unique à trois agents ne prouverait rien du tout.

Les douze causes sont donc réparties en **quatre familles de trois**, et le
**vocabulaire de surface est partagé à l'intérieur d'une famille**. Une
expression régulière ne peut jamais dépasser le niveau de la famille : il lui
reste un choix à trois, qu'elle ne peut pas trancher. Ce qui sépare les trois
causes d'une famille est une forme temporelle.

| Famille | Causes | Vocabulaire commun | Ce qui les sépare |
|---|---|---|---|
| `resource` | `memory_leak`, `cache_stampede`, `traffic_spike` | mémoire, heap, cache, éviction, trafic | croissance monotone / effondrement du taux de succès / `rps` qui monte **en premier** |
| `change` | `deploy_regression`, `config_change`, `dependency_version_bug` | déploiement, release, version, flag | événement de déploiement / bascule de paramètre / pile d'exception **à l'intérieur** d'une librairie tierce |
| `dependency` | `db_connection_pool_exhaustion`, `downstream_timeout`, `network_partition` | timeout, pool, connexion, amont, circuit | attente **locale** / temps passé **chez l'appelé** / plusieurs services sans rapport touchés |
| `platform` | `cpu_saturation`, `disk_full`, `cert_expiry` | cpu, disque, inode, certificat, tls | CPU à 97 % à trafic **constant** / montée monotone du disque / bascule **totale et instantanée** |

Trois exemples concrets de couples que le vocabulaire ne sépare pas :

- `cpu_saturation` et `traffic_spike` font tous deux monter le CPU. Seul le
  second fait monter `rps` d'abord, et le CPU proportionnellement ensuite.
- `db_connection_pool_exhaustion` et `downstream_timeout` produisent tous deux
  des délais dépassés. Dans le premier, l'attente est locale et le service appelé
  répond en 12 ms ; dans le second, l'attente locale est nulle et le p99 de
  l'appelé est à 4 s.
- `disk_full` et `memory_leak` montent tous deux de façon monotone, sur deux
  métriques différentes.

---

## 1. Ce que contient le jeu

- **45 incidents** (`data/incidents/incidents.json`, 289 ko, versionné).
- **30 fiches d'incidents passés** (`data/kb/past_incidents.json`).
- 12 causes racines, **liste fermée** : la comparaison à la vérité terrain est
  une égalité de chaînes. Pas de juge LLM, donc pas de juge à soupçonner de
  complaisance, et re-scorer un run coûte 0 $.
- Chaque incident : une fenêtre de 60 minutes, 12 relevés de 9 métriques, de 6 à
  12 lignes de journal, 0 à 1 pile d'exception, 0 à 1 événement de changement.
- Répartition des causes : 4 occurrences pour neuf d'entre elles, 3 pour les
  trois autres. Aucune cause n'est absente (test).

**Déterminisme.** Chaque incident tire ses valeurs d'un générateur semé sur
`f"{graine}:{identifiant}"`, et non sur un flux unique parcouru dans l'ordre :
insérer un incident au milieu de la table ne décale pas les valeurs des
suivants, donc ne périme pas les chiffres déjà publiés. Un test compare le
fichier versionné à ce que produit le générateur — modifier le code sans
régénérer le fichier fait échouer `make test`.

---

## 2. Les quatre catégories

| Catégorie | n | Vue métriques | Vue journaux | Base historique |
|---|---|---|---|---|
| `infra_pure` | 12 | signature de la cause | **rien** | sans objet |
| `app_pure` | 12 | **neutre** | signature de la cause | sans objet |
| `history_required` | 11 | **neutre** | **neutre** + un motif distinctif | une fiche, et une seule, conclut |
| `ambiguous` | 10 | signature du **leurre** | signature de la **vérité** | sans objet |

**`history_required`** : les deux vues sont muettes, mais les journaux portent un
**motif distinctif** — temporel ou conditionnel — qui ne nomme aucune cause :
« les échecs arrivent par salves de huit minutes, toutes les six heures », « seules
les requêtes dont la charge utile dépasse deux mégaoctets échouent », « après
chaque redémarrage, quarante minutes sans aucun échec ». Aucun de ces motifs ne
contient un token de famille : c'est vérifié incident par incident.

**`ambiguous`** : les métriques pointent vers une cause, les journaux vers une
autre, et les deux sont plausibles. La règle de dominance est la même pour les
dix, écrite avant toute exécution :

> La vérité terrain est la cause qui explique **les deux** observations ; le
> leurre n'explique que la sienne.

Exemple (INC-036) : le CPU est à 97 % et une pile d'exceptions se répète 214 fois
à l'intérieur d'une librairie tierce. Le bug de la librairie — une boucle de
décodage — explique le CPU **et** les exceptions. La saturation CPU seule
n'explique pas le `TypeError`. Chaque cas ambigu porte sa justification dans
`dominance_note`, et un test refuse un cas ambigu sans justification, comme il
refuse un leurre pris dans la même famille que la vérité.

Sur ces dix incidents, **le bon comportement du système n'est pas de trouver la
cause : c'est de ne pas être confiant.** La phase 4 mesure le taux d'absence de
consensus sur les ambigus par rapport aux autres catégories. Un système qui
tranche avec assurance sur un cas ambigu y sera compté comme moins bon.

---

## 3. Garde n°1 — fuite de signal entre les vues

Le mode de panne : un incident « infra pure » dont les journaux nomment déjà la
cause. L'agent Application trouverait la bonne réponse sans avoir les données
pour, le taux de réussite serait excellent, et rien dans les résultats ne
signalerait que la mesure est fausse.

Deux détecteurs, appliqués aux 45 incidents :

- `metric_signals` : les métriques hors de leur bande neutre, plus l'événement de
  changement s'il y en a un.
- `log_families` : les familles dont le vocabulaire apparaît dans les lignes, les
  exceptions et les piles.

**`error_rate` est délibérément exclue des métriques discriminantes.** Elle est
élevée dans les 45 incidents — c'est ce qui fait qu'il y a un incident. La
compter comme un signal rendrait aucune vue métrique jamais neutre, et le garde
ne vaudrait plus rien.

| Catégorie | signaux métriques (moyenne) | familles dans les journaux |
|---|---|---|
| `infra_pure` | 1,17 | **0** |
| `app_pure` | **0,00** | 1 — celle de la cause |
| `history_required` | **0,00** | **0** |
| `ambiguous` | 1,00 | 1 — celle de la cause |

**Résultat : 0 fuite sur 45 incidents.** Un test vérifie en plus qu'aucun des neuf
gabarits de lignes neutres ne contient de token de famille — sans quoi la
neutralité d'une vue dépendrait du tirage aléatoire.

Ce garde a servi dès la première exécution : il a rejeté INC-037 et INC-043, où
la vérité et le leurre appartenaient à la même famille. Les deux couples ont été
réécrits.

---

## 4. Garde n°2 — recouvrement lexical avec la base historique

Le mode de panne : la fiche passée reprend les mots de l'incident. L'agent
Historique gagne par recopie, et sa performance mesure la paresse du générateur,
pas une capacité de rapprochement.

Mesure : indice de Jaccard entre `incident.history_query()` (ce que l'agent envoie
au moteur de recherche) et `fiche.searchable_text()` (ce que le moteur indexe) —
exactement le couple que la recherche doit rapprocher.

```
0.091  0.097  0.100  0.129  0.149  0.150  0.156  0.159  0.172  0.206  0.265
                                   médiane 0,150                  max 0,265
```

**Seuil : médiane < 0,30. Mesuré : 0,150.** Le maximum, 0,265, reste sous le seuil.

Concrètement, la fiche qui résout INC-025 (« salves de huit minutes, toutes les
six heures, aux heures rondes ») parle de « quatre fois par jour, une rafale
d'échecs d'une dizaine de minutes, calée sur les heures rondes » sur un autre
service, avec d'autres chiffres. Le rapprochement passe par la **forme** du
symptôme, pas par une répétition de mots.

Et surtout : l'incident ne contient aucun token de surface de sa propre cause
(garde n°1). La cause vient donc bien de la fiche, jamais de l'incident.

---

## 5. Garde n°3 — le jeu est-il trivial ?

Si une heuristique déterministe suffit, comparer un agent unique à trois agents
ne prouve rien. Le **plancher** (`council/agents/keyword.py`) est ce qu'un
ingénieur écrit en une après-midi : dix seuils sur les métriques, une détection
de famille sur le vocabulaire des journaux, et un repli sur le cas passé le plus
proche. Il reçoit **exactement la même information que la baseline mono-agent**,
fiches historiques comprises — le handicaper sur onze incidents aurait
artificiellement abaissé le plancher.

Bande admissible fixée d'avance : **[35 %, 60 %]**. Le hasard est à 25 %.

| | Réussite |
|---|---|
| Plancher, sans la base historique | 42,2 % |
| **Plancher, avec la base historique** | **53,3 %** |
| `infra_pure` | **100,0 %** |
| `app_pure` | 50,0 % |
| `history_required` | 54,5 % |
| `ambiguous` | 0,0 % |

**Ce chiffre de 100 % sur `infra_pure` est le résultat le plus important de la
phase 1, et il n'est pas flatteur pour le projet.**

Douze incidents sur quarante-cinq se résolvent avec `disque > 90 %`,
`cpu > 90 %`, `un déploiement dans la fenêtre`. Ce n'est pas un défaut du
générateur : c'est la réalité de ces incidents-là. La conséquence est à assumer
dès maintenant et sera rappelée dans le rapport de la phase 4 :

> **Un éventuel gain du système multi-agents ne peut pas venir de la catégorie
> `infra_pure`.** Le plafond y est déjà atteint sans LLM. Il ne peut venir que
> des 33 autres incidents — et c'est là que la baseline mono-agent sera, elle
> aussi, à son meilleur.

À l'autre bout, le plancher est à **0 %** sur les cas ambigus. Il suit les
métriques, qui portent le leurre : il se trompe systématiquement. Un test fige ce
comportement — si le plancher se met à réussir sur les ambigus, c'est qu'ils ne
le sont plus.

---

## 6. Recherche de cas passés : la décision BM25 / embeddings

Décision prise dans `docs/plan.md` **avant** de mesurer : BM25 par défaut, parce
que la base fait 30 fiches et que charger `sentence-transformers` (~800 Mo avec
torch) sur une machine dont la racine est un disque mécanique ne se justifie que
si BM25 échoue. **Seuil annoncé d'avance : rappel@3 < 0,80 ⇒ on ajoute les
embeddings et on publie les deux chiffres.**

| | Rappel |
|---|---|
| @1 | 54,5 % |
| @3 | **63,6 %** |
| @5 | 81,8 % |

**Le seuil est franchi dans le mauvais sens : 63,6 % < 80 %.** La règle
pré-enregistrée s'applique, la phase 2 devra donc comparer trois variantes et
publier les trois :

1. BM25 top-3 (référence, 63,6 %) ;
2. BM25 **top-5** (81,8 %) en laissant l'agent trancher parmi cinq candidats —
   l'option la moins chère, et la plus proche de ce que fait un humain ;
3. embeddings, si les deux premières ne suffisent pas.

Ce résultat vient des cinq **faux jumeaux** placés délibérément dans la base :
des fiches au motif identique (périodicité, instance unique, région unique) mais
de cause différente. KB-19 (« accalmie systématique après chaque redémarrage »,
cause : pool de connexions) est le jumeau de KB-26 (même motif, cause : fuite
mémoire) ; KB-20 (« créneau quotidien à heure fixe », cause : pic de trafic) est
celui de KB-28 (même motif, cause : disque plein). Sans eux, le rappel@1
frôlerait 100 % et la mesure ne voudrait rien dire.

---

## 7. Volumétrie, pour le chiffrage de la phase 2

Estimation grossière (caractères ÷ 3,6), à remplacer par `count_tokens` :

| Vue | Jetons d'entrée, par incident |
|---|---|
| Infrastructure (métriques + événements) | ~770 |
| Application (journaux + piles) | ~370 |
| Historique (5 fiches candidates) | ~330 |
| Baseline mono-agent (les trois réunies) | ~1 500 |

La vue infrastructure est **deux fois plus lourde** que la vue applicative : 12
relevés × 9 métriques en JSON. Un point à surveiller en phase 2 — si le coût le
justifie, les séries pourront être résumées (min/max/pente/point de bascule)
plutôt que transmises point par point. Ce sera un arbitrage mesuré, pas un choix
a priori.

---

## 8. Ce que ce jeu de données **ne** représente pas

À dire avant les résultats, pas après :

- **Une seule cause par incident.** Les vraies pannes en cascade (un déploiement
  qui sature le disque qui bloque la base) ne sont représentées que dans les cas
  ambigus, et encore, sous une forme simplifiée.
- **Pas de bruit de production réel** : ni pannes de collecteur, ni horloges
  désynchronisées, ni journaux tronqués, ni métriques manquantes.
- **Une fenêtre de 60 minutes, déjà cadrée.** Le travail de trouver la bonne
  fenêtre — souvent le plus difficile — est écarté.
- **Un vocabulaire homogène**, celui du générateur. Une vraie base d'incidents
  mélange dix rédacteurs, deux langues et quinze ans d'habitudes.
- **Douze causes**, là où un vrai référentiel en compte des centaines.
- La base historique est **propre** : une fiche par incident, une cause par
  fiche, aucune fiche fausse.

Conséquence honnête : ce jeu de données permet de comparer **des architectures
d'agents entre elles**, à information constante. Il ne permet **pas** d'annoncer
un taux de réussite transposable à une production réelle.

---

## 9. Régénérer et re-vérifier

```bash
make dataset          # réécrit data/incidents/ et data/kb/ (déterministe)
make dataset-report   # recalcule les 3 gardes + le plancher + le rappel
make test             # 27 tests, hors réseau, 0 $
```

`make dataset-report` sort en code 1 si un garde tombe ou si le plancher sort de
la bande [35 %, 60 %].

La graine du projet est `20260911` (`council/config.py`). **La changer change le
jeu de données et périme tous les chiffres publiés** — y compris ceux de ce
document et du README.
