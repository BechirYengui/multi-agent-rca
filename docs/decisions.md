# Journal des arbitrages

Une entrée par décision qui aurait pu être prise autrement. Chacune porte sa
mesure ou sa raison, et sa date. Ce fichier existe pour que, dans six mois, une
décision ne ressemble pas à une évidence.

---

## D1 — `error_rate` n'est pas une métrique discriminante (2026-09-11)

Elle est élevée dans les 45 incidents : c'est le symptôme qui déclenche
l'alerte. La compter comme un signal rendrait aucune vue « métriques » jamais
neutre, et le garde anti-fuite ne vaudrait plus rien — il passerait toujours,
pour de mauvaises raisons.

---

## D2 — Vocabulaire de surface partagé par famille (2026-09-11)

Les 12 causes sont réparties en 4 familles de 3, et les trois causes d'une
famille produisent les mêmes mots. Une expression régulière ne peut donc jamais
dépasser le niveau de la famille.

**Mesure** : le plancher déterministe plafonne à 53,3 %, dans la bande
[35 %, 60 %] fixée d'avance. Sans ce partage, il aurait dépassé 80 % et le
benchmark n'aurait rien prouvé.

---

## D3 — BM25 plutôt qu'embeddings, mais le seuil a sauté (2026-09-11)

Décision initiale : BM25, parce que la base fait 30 fiches et que
`sentence-transformers` pèse ~800 Mo avec torch sur une machine dont la racine
est un disque mécanique. **Seuil annoncé avant mesure : rappel@3 < 0,80 ⇒ on
ajoute les embeddings.**

**Mesure** : rappel@1 = 54,5 %, @3 = **63,6 %**, @5 = 81,8 %.

Le seuil est franchi dans le mauvais sens. Mais @5 remonte à 81,8 % : servir
cinq fiches candidates et laisser l'agent trancher coûte ~330 jetons et évite
les 800 Mo. C'est l'hypothèse que la phase 2 met à l'épreuve — `k` est un
paramètre (`--k`), les deux valeurs seront mesurées, la meilleure retenue et
l'autre publiée. Les embeddings restent le troisième recours si les deux
échouent.

---

## D4 — Aucun guide de discrimination dans les invites (2026-09-11)

Les consignes des agents ne disent nulle part que « le pic de trafic fait monter
`rps` en premier » ni que « l'attente du pool est locale alors que le timeout
aval ne l'est pas ».

Ces règles sont exactement celles qui ont servi à **fabriquer** le jeu de
données. Les injecter reviendrait à transmettre la grille de correction aux
agents évalués : le benchmark ne mesurerait plus qu'une obéissance à la consigne.
Le modèle a sa propre connaissance des incidents de production — c'est elle
qu'on évalue. Les invites ne contiennent que la liste fermée des causes, et la
même pour les quatre bras.

---

## D5 — L'abstention n'est pas une treizième cause (2026-09-11)

Un spécialiste peut répondre `insufficient_evidence`, converti en `cause = None`
avec une confiance forcée à 0.

Un agent qui s'abstient n'est pas un agent qui contredit. Les confondre ferait
passer une absence de données pour un désaccord, et déclencherait des boucles de
clarification là où il n'y a rien à clarifier. La valeur reste hors de
`RootCause` : la taxonomie qui sert de vérité terrain n'est pas polluée.

---

## D6 — Aucun juge LLM (2026-09-11)

Les agents choisissent dans une liste fermée de 12 labels ; le score est une
égalité de chaînes. Conséquences : le benchmark est déterministe, re-scorer un
run coûte 0 $, et personne ne peut soupçonner le juge d'être complaisant envers
le système qu'il note.

---

## D7 — `temperature` n'existe plus : cache pour reproduire, `--no-cache` pour mesurer (2026-09-11)

Le paramètre est retiré sur Opus 5 et Sonnet 5 (400 s'il est envoyé). On ne peut
donc pas rendre les appels déterministes côté modèle.

- **Reproduire un rapport** : cache disque keyé sur
  `sha256(modèle + effort + invite + schéma)`. Régénérer coûte 0 $.
- **Mesurer la variance** : exactement l'inverse. Les passes de variance tournent
  avec `--no-cache`. C'est une mesure assumée, pas un contournement.

Le modèle **et** le niveau d'effort entrent dans la clé : deux réglages
différents sont deux expériences différentes.

---

## D8 — Le plafond de dépense coupe avant l'appel (2026-09-11)

`BudgetGuard.check()` est appelé **avant** `messages.create`, avec une estimation
volontairement pessimiste (3,2 caractères par jeton). Un disjoncteur doit se
déclencher trop tôt, jamais trop tard : un dépassement doit coûter l'appel qu'on
n'a pas fait, pas celui qu'on vient de payer. Testé avec un plafond de 0 $, en
vérifiant que l'API n'est pas appelée.

---

## D9 — Le chiffrage à blanc rejoue le vrai pipeline (2026-09-11)

`council agents dry-run` ne recalcule pas les invites de son côté : il fait
tourner le pipeline réel contre un client simulé qui enregistre ce qui serait
parti, puis compte. Un chiffrage qui reconstruirait les invites finirait par
mesurer autre chose que ce qui part vraiment.

**Mesure** : 135 appels, ~213 000 jetons d'entrée → **1,64 $** en Sonnet 5,
**4,10 $** en Opus 5.
