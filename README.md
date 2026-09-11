# multi-agent-rca

**Trois agents spécialistes analysent un incident de production en parallèle, chacun
sur une source différente et sans se consulter ; un arbitre tranche. La question du
projet n'est pas « est-ce que ça marche », c'est « est-ce que ça bat un agent unique,
et de combien, pour quel coût » — mesuré sur les mêmes incidents, avec un test
statistique apparié.**

> **Résultat chiffré : en attente du run réel.** Tout le code qui le produit est
> écrit et testé (85 tests, hors réseau). Cette place restera vide tant que la
> mesure n'aura pas tourné : un README qui annonce un résultat avant de l'avoir
> mesuré est exactement ce que ce projet cherche à ne pas faire.

---

## Le problème, et pourquoi il est piégeux

Il est facile de construire une démo multi-agents impressionnante. Il est beaucoup
plus difficile de montrer qu'elle apporte quelque chose. Trois pièges, traités
explicitement ici :

**1. Les trois agents tournent sur le même modèle.** Leur accord n'est donc pas
l'accord de trois experts indépendants — leurs erreurs sont corrélées. Le projet ne
suppose pas le contraire, il mesure de combien (coefficient phi entre convergence et
exactitude).

**2. Un jeu de données trop facile prouverait n'importe quoi.** D'où un **plancher
déterministe** : une heuristique sans LLM qui doit rester entre 35 % et 60 %. Elle
est à **53,3 %**. Au-dessus de 60 %, le jeu aurait été rejeté et régénéré.

**3. Comparer « multi-agents » à « agent unique » ne sépare pas deux choses
différentes** : découper le problème, et avoir un arbitre. D'où quatre bras, dont
un gratuit.

| Bras | Appels LLM / incident | Ce qu'il isole |
|---|---|---|
| `floor` | 0 | la difficulté réelle du jeu de données |
| `baseline` | 1 | l'apport de la décomposition |
| `vote` | **0** — rejoue les hypothèses déjà payées | l'apport de l'arbitre |
| `council` | 3 à 8 | — |

Si `council` ne bat pas `vote`, l'arbitre ne paie pas son coût, et le rapport
l'écrira.

---

## Architecture

```
                  ┌─ agent Infrastructure ─┐   métriques + changements récents
   incident ──────┼─ agent Application ────┼─> routeur ─┬─> conclusion
                  └─ agent Historique ─────┘  (pur)     ├─> relance du divergent ─┐
                     journaux / cas passés               └─> rapport multi-pistes  │
                                                                    ▲             │
                                                                    └─────────────┘
                                                                     2 relances max
```

Orchestration **LangGraph** : fan-out vers trois branches parallèles, fan-in par
réducteur, arête conditionnelle, boucle de clarification plafonnée.

Quatre choix de conception qui portent le projet :

- **Le routeur est une fonction pure** — ni LangGraph, ni LLM, ni horloge. La
  question métier (y a-t-il consensus ? faut-il relancer ?) se teste
  exhaustivement en mémoire. LangGraph ne fait plus que du câblage.
- **Une abstention n'est pas un désaccord.** Un agent qui n'a rien vu est retiré du
  décompte, pas compté contre la majorité.
- **Le plafond de relances est appliqué dans le routeur**, pas dans le nœud qu'il
  limite. Une boucle infinie facturée est le mode de panne qu'on refuse d'avoir.
- **L'arbitre ne voit jamais les données brutes** — seulement les trois hypothèses
  et leurs preuves citées. S'il pouvait relire les métriques, il redeviendrait un
  agent unique avec trois résumés en plus.

---

## Ce qui est déjà mesuré

Chiffres reproductibles par `make dataset-report` et `council benchmark dry-run`.

| Mesure | Valeur | Ce qu'elle garantit |
|---|---|---|
| Fuite de signal entre les vues | **0 / 45** | un incident « infra pure » ne nomme jamais sa cause dans les journaux |
| Recouvrement lexical avec la base historique | **Jaccard médian 0,150** | l'agent Historique ne gagne pas par recopie |
| Plancher déterministe | **53,3 %** (bande [35 %, 60 %]) | le jeu n'est pas résoluble sans LLM |
| Rappel BM25 @1 / @3 / @5 | **54,5 % / 63,6 % / 81,8 %** | seuil de 0,80 franchi à k=5, embeddings évités |
| Coût d'un run complet, Sonnet 5 | **3,48 $ à 5,56 $** | encadré en rejouant le vrai pipeline, pas estimé |

Le plancher atteint **100 % sur les incidents d'infrastructure pure**. Ce n'est pas
un défaut du générateur, c'est la réalité de ces incidents — et la conséquence est
écrite avant les résultats : *aucun gain du multi-agents ne peut venir de cette
catégorie.*

---

## Le jeu de données

45 incidents synthétiques, 12 causes racines en **liste fermée** (le score est une
égalité de chaînes : pas de juge LLM), 4 catégories :

| Catégorie | n | Vue métriques | Vue journaux | Base historique |
|---|---|---|---|---|
| `infra_pure` | 12 | signature de la cause | rien | — |
| `app_pure` | 12 | neutre | signature de la cause | — |
| `history_required` | 11 | neutre | neutre + motif distinctif | une fiche conclut |
| `ambiguous` | 10 | signature du **leurre** | signature de la **vérité** | — |

Le mécanisme central : les 12 causes sont réparties en **4 familles de 3**, et le
vocabulaire de surface est partagé *à l'intérieur* d'une famille. Une expression
régulière ne peut jamais dépasser le niveau de la famille. Ce qui sépare les trois
causes est une **forme temporelle** — `cpu_saturation` et `traffic_spike` font tous
deux monter le CPU, seul le second fait monter `rps` en premier.

Sur les dix cas ambigus, le bon comportement n'est **pas** de trouver la cause :
c'est de ne pas être confiant. C'est mesuré comme tel.

Détail complet : [`docs/dataset.md`](docs/dataset.md).

---

## Utilisation

```bash
make install              # uv sync
make test                 # 85 tests, hors réseau, 0 $
make lint                 # ruff + mypy strict

make dataset              # régénère les 45 incidents (déterministe, graine fixe)
make dataset-report       # recalcule les 3 gardes anti-triche + le plancher

make dry-run              # chiffre un run AVANT de dépenser quoi que ce soit
make calibrate            # mesure chaque spécialiste seul + sa calibration
make benchmark            # les 4 bras + rapport + graphiques
make benchmark-variance   # 3 passes sans cache, pour mesurer la variance

uv run council investigate INC-036   # un incident, avec sa trace
uv run council replay <run_id>       # reconstitue le raisonnement, gratuit
```

Aucune clé API n'est nécessaire pour `make test`, `make dataset` ni `make dry-run`.

**Garde-fou de dépense** : le plafond est vérifié *avant* chaque appel, avec une
estimation volontairement pessimiste. Un dépassement doit coûter l'appel qu'on n'a
pas fait, pas celui qu'on vient de payer. Dépassement ⇒ arrêt propre, résultats
partiels conservés, rapport marqué « PARTIEL ».

---

## Reproductibilité

`temperature` n'existe plus sur Opus 5 et Sonnet 5 (paramètre retiré, 400 s'il est
envoyé). On ne peut donc pas rendre les appels déterministes côté modèle. Deux
conséquences assumées :

- **reproduire un rapport** → cache disque `sha256(modèle + effort + invite + schéma)`,
  régénérer coûte 0 $ ;
- **mesurer la variance** → exactement l'inverse, `--no-cache`. La CLI *refuse*
  `--passes 3` sans `--no-cache` : trois passes cachées mesureraient zéro variance
  par construction.

---

## Documentation

| Fichier | Contenu |
|---|---|
| [`docs/plan.md`](docs/plan.md) | les 5 phases, écrites avant la première ligne de code |
| [`docs/dataset.md`](docs/dataset.md) | construction du jeu, les 3 gardes anti-triche, ce qu'il ne représente pas |
| [`docs/decisions.md`](docs/decisions.md) | 17 arbitrages, chacun avec sa mesure et sa date |
| `docs/calibration.md` | *généré par `make calibrate`* |
| `docs/benchmark.md` | *généré par `make benchmark`* |

---

## Stack

Python 3.12 · [uv](https://github.com/astral-sh/uv) · Pydantic v2 · LangGraph ·
structlog · rank-bm25 · matplotlib · pytest · ruff · mypy strict
