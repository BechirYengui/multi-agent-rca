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

---

## D10 — Quatre bras de comparaison, et l'un d'eux est gratuit (2026-09-11)

Comparer « multi-agents » à « agent unique » ne sépare pas deux choses pourtant
différentes : **découper le problème en trois vues** et **avoir un arbitre
LLM**. Deux bras intermédiaires les isolent :

| Bras | Appels LLM / incident | Ce qu'il isole |
|---|---|---|
| `floor` | 0 | la difficulté réelle du jeu de données |
| `baseline` | 1 | l'apport de la décomposition |
| `vote` | **0** | l'apport de l'arbitre |
| `council` | 3 à 8 | — |

Le bras `vote` rejoue les hypothèses du **premier tour** déjà payées par le
conseil et prend simplement la plus confiante : il ne coûte pas un jeton. Si
l'arbitre ne le bat pas, il ne paie pas son coût, et le rapport l'écrira.

---

## D11 — L'arbitre ne voit jamais les données brutes (2026-09-11)

Il ne reçoit que les trois hypothèses, leurs preuves citées et leurs confiances.
S'il pouvait relire les métriques et les journaux, il redeviendrait un agent
unique avec trois résumés en plus — et la comparaison au bras `baseline`
perdrait tout son sens, puisque les deux verraient la même chose.

---

## D12 — Trois tâches d'arbitre, trois schémas, trois appels (2026-09-11)

Un schéma unique qui autoriserait à la fois « voici la cause » et « je ne sais
pas » laisserait le modèle choisir la sortie confortable. Ici, c'est le routeur
— déterministe et testé — qui décide de la tâche ; l'arbitre ne fait que
l'exécuter.

---

## D13 — Le test apparié ne fusionne pas les passes (2026-09-11)

Deux passes du même incident ne sont pas deux observations indépendantes. Les
empiler gonflerait artificiellement la puissance du McNemar. L'analyse primaire
porte donc sur **la passe 1**, et les autres passes servent à mesurer la
variance, pas à grossir l'échantillon.

---

## D14 — Le seuil de 10 paires discordantes l'emporte sur une p-valeur basse (2026-09-11)

Constaté sur le run simulé : `council` vs `vote` donne 9 paires discordantes,
toutes dans le même sens, soit p = 0,004. La règle posée avant le premier run
exige 10 paires minimum. Le rapport affiche donc **« non concluant »**, tout en
publiant la p-valeur.

Céder ici reviendrait à transformer une règle en filtre appliqué après coup aux
résultats qui dérangent. Une règle qu'on suspend quand elle gêne n'est pas une
règle.

---

## D15 — Mesurer la variance avec le cache actif est refusé par la CLI (2026-09-11)

`council benchmark run --passes 3` sort en erreur si `--no-cache` est absent :
les trois passes renverraient les mêmes réponses mises en cache et la « variance
mesurée » serait exactement zéro, par construction. Un piège qu'on ne peut pas
se contenter de documenter.

---

## D16 — La baseline tourne à deux niveaux d'effort, on retient son meilleur score (2026-09-11)

Elle coûte ~1 appel par incident. Lui donner sa meilleure chance coûte quelques
dollars et c'est la seule façon de rendre un éventuel écart crédible. Le rapport
indique explicitement quel niveau a été retenu.
