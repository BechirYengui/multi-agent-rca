# Plan d'implémentation — 5 phases

Projet : **multi-agent-rca** — investigation d'incidents de production par
plusieurs agents spécialistes indépendants + un arbitre.

Établi le 2026-09-11, avant toute ligne de code. Chaque phase : arborescence,
ordre d'implémentation, mesure, critère de sortie chiffré.

---

## 0. La thèse à prouver, et comment elle peut être fausse

**Thèse** : trois agents qui voient chacun une part du problème, puis un arbitre,
trouvent la bonne cause racine plus souvent qu'un agent unique qui voit tout.

**Le piège** : les trois spécialistes tournent sur le **même modèle**. Leur accord
n'est donc pas l'accord de trois experts indépendants — c'est le même réseau,
trois fois, sur trois vues. Leurs erreurs sont corrélées. Tout le projet consiste
à mesurer **de combien** elles le sont, pas à supposer qu'elles ne le sont pas.

D'où trois décisions structurantes, prises maintenant :

1. **Quatre bras de comparaison, pas deux.** Le bras « agrégation triviale »
   (prendre l'hypothèse la plus confiante des trois, sans arbitre LLM) est le vrai
   test de l'arbitre : si l'arbitre ne bat pas `argmax(confiance)`, il ne sert à
   rien et le rapport le dira. Ce bras coûte 0 $ — il rejoue les hypothèses déjà
   produites.

   | # | Bras | Appels LLM / incident | Ce qu'il isole |
   |---|---|---|---|
   | 1 | Plancher : heuristique mots-clés | 0 | La difficulté réelle du jeu de données |
   | 2 | Baseline mono-agent, tout le contexte | 1 | L'apport de la décomposition |
   | 3 | 3 spécialistes + `argmax(confiance)` | 3 | L'apport de l'arbitre |
   | 4 | 3 spécialistes + arbitre (le système) | 3 à 6 | — |

2. **Aucun juge LLM.** Les agents sortent un label pris dans une **liste fermée**
   de causes racines. Le scoring est une égalité de chaînes. Le benchmark est donc
   déterministe, gratuit à re-scorer, et personne ne peut soupçonner le juge d'être
   complaisant envers le système qu'il note.

3. **Comparaison appariée.** Avec n = 45, l'intervalle de confiance à 95 % d'un
   taux de 70 % est de ±13 points : comparer deux proportions indépendantes ne
   détecterait qu'un écart supérieur à ~20 points. Les quatre bras tournent sur
   **les mêmes incidents**, et le test est un **McNemar** sur les paires
   discordantes, beaucoup plus puissant. Règle posée d'avance : moins de 10 paires
   discordantes ⇒ le rapport conclut « aucune différence mesurable », pas
   « tendance en faveur de ».

Ce que le projet peut légitimement conclure : « le multi-agents ne gagne rien,
et coûte 3× plus cher ». Ce serait un résultat publiable. Le plan est construit
pour que ce résultat-là soit aussi facile à produire que l'autre.

---

## Contraintes techniques relevées (2026-09-11)

- `uv` 0.12.3 présent, python système 3.10 → le projet épingle **3.12** via uv,
  comme `catalog-reliability-pipeline` (borne haute incluse).
- **Aucune clé Anthropic trouvée** sur le poste. Les phases 1 et les tests des
  phases 2-4 tournent **sans réseau** (client LLM simulé). Seuls le benchmark et
  la calibration consomment des jetons.
- **`temperature` n'existe plus** sur Opus 5 / Sonnet 5 (paramètre retiré, 400 si
  envoyé). On ne peut donc **pas** rendre les appels déterministes par
  `temperature=0`. Deux conséquences assumées :
  - reproductibilité d'un rapport ⇒ **cache disque** `sha256(modèle+effort+requête)`
    → réponse. Re-générer le rapport coûte 0 $.
  - variance réelle du système ⇒ se **mesure**, en rejouant le benchmark 3 fois
    avec `--no-cache`. C'est une mesure, pas un défaut à cacher.
- Tarifs relevés ce jour (figés dans `council/budget.py`, avec la date) :
  Opus 5 = 5 $ / 25 $ par MTok, Sonnet 5 = 2 $ / 10 $, Haiku 4.5 = 1 $ / 5 $.

---

## Phase 1 — Socle + jeu de données + **preuve qu'il est discriminant**

Aucun appel LLM. Objectif : avoir un jeu de données dont on a **démontré** qu'il
n'est ni trivial ni truqué, avant d'y dépenser un dollar.

```
pyproject.toml            uv, ruff, mypy strict sur council/
Makefile                  install / test / lint / dataset / benchmark / report
.env.example              ANTHROPIC_API_KEY, COUNCIL_MODEL, COUNCIL_BUDGET_USD
council/
  models.py               Pydantic v2 : Incident, MetricWindow, LogWindow,
                          PastIncident, Hypothesis(cause:RootCause, confidence:float,
                          evidence:list[str]), Clarification, Verdict, RootCause(enum)
  config.py               pydantic-settings ; modèle, effort, budget, seuils
  logging.py              structlog, sortie JSON lines, run_id lié au contexte
  budget.py               table de prix datée + BudgetGuard (plafond $ dur)
  data/
    taxonomy.py           LISTE FERMÉE de 12 causes racines
    templates.py          gabarits de métriques, de logs, de fiches d'historique
    generator.py          45 incidents, seed fixe, catégorie + vérité terrain
    kb.py                 30 incidents passés résolus (base de connaissances)
  agents/keyword.py       le plancher : heuristique déterministe, 0 LLM
data/
  incidents/incidents.json    généré, VERSIONNÉ (le benchmark doit être rejouable)
  kb/past_incidents.json
docs/dataset.md
tests/
  test_generator.py       déterminisme (même seed ⇒ octet pour octet), équilibre
                          des 4 catégories, tout label ∈ taxonomie
  test_leakage.py         les 3 gardes anti-triche ci-dessous
```

**Les 4 catégories** (45 incidents) : infra pure (12), applicative pure (12),
nécessitant l'historique (11), ambiguë/mixte (10).

**Les trois façons dont un jeu synthétique se triche tout seul**, et le garde-fou
mesuré pour chacune :

| Triche | Garde-fou automatisé (test) |
|---|---|
| **Trop facile** — un `grep` suffit | Le bras 1 (mots-clés) doit scorer **entre 35 % et 60 %**. Le hasard est à 25 % (4 familles). Au-dessus de 60 %, le générateur est rejeté et re-paramétré : le benchmark ne prouverait rien. |
| **Fuite de signal** — un incident « infra pure » dont les logs nomment la cause | Pour chaque incident, on vérifie que les vues qui ne doivent pas porter le signal ne contiennent **aucun** token discriminant de la cause. Assertion stricte : 0 fuite. |
| **Recouvrement lexical avec la base historique** — l'agent Historique retrouve son cas par simple copie de mots | L'incident et sa fiche historique correspondante sont écrits avec un **vocabulaire de surface disjoint** (service, seuils, formulation différents). Mesure : Jaccard médian des tokens < 0,30. Sinon la performance de l'agent Historique serait un artefact du générateur. |

Les cas **ambigus** sont construits explicitement : deux vues portent chacune un
signal fort vers **deux causes différentes et plausibles**. La vérité terrain y est
la cause dominante, et le comportement attendu du système n'est pas forcément de
la trouver — c'est de **ne pas être confiant**. Mesuré en phase 4.

`docs/dataset.md` documente les gabarits, la répartition, les trois mesures
ci-dessus avec leurs chiffres réels, et ce que le jeu **ne** représente pas
(pas de bruit de production réel, pas d'incidents multi-causes en cascade).

**Ordre** : `taxonomy` → `models` → `templates` → `generator` (+tests de
déterminisme) → `kb` → `keyword.py` → les 3 gardes → `docs/dataset.md`.

**Critère de sortie** : `make dataset` régénère les 45 incidents à l'octet près ;
les 3 gardes passent ; le plancher mots-clés est dans [35 %, 60 %] ; `make lint`
vert (mypy strict). **Je te montre `docs/dataset.md` et les chiffres avant de
passer à la phase 2.**

---

## Phase 2 — Les trois spécialistes, isolés et mesurés séparément

C'est ici que se joue le projet : si chaque spécialiste seul est mauvais sur *sa*
catégorie, aucun arbitre ne rattrapera ça, et il vaut mieux le savoir avant
d'écrire le graphe.

```
council/
  llm/
    client.py             anthropic, sorties structurées (schéma Pydantic),
                          retry borné, comptage jetons → BudgetGuard
    cache.py              sha256(modèle+effort+requête) → réponse, sur disque
    fake.py               client simulé pour les tests : réponses figées, 0 réseau
  agents/
    base.py               Protocol Specialist : analyse(vue) -> Hypothesis
    infra.py              ne reçoit QUE MetricWindow + historique de déploiements
    app.py                ne reçoit QUE LogWindow + stack traces
    history.py            interroge la base de connaissances
    retrieval.py          BM25 (rank-bm25), top-k, sans dépendance lourde
    prompts/              français, taxonomie fermée injectée dans le prompt
benchmark/calibration.py  courbe de fiabilité + score de Brier par agent
tests/
  test_infra_agent.py     client simulé : hypothèse bien parsée, confiance bornée
  test_app_agent.py       idem
  test_history_agent.py   idem + l'agent ne voit jamais métriques ni logs
  test_retrieval.py       rappel@3 sur les couples (incident, fiche) connus
  test_isolation.py       NON NÉGOCIABLE : aucun spécialiste ne reçoit une vue
                          qui ne lui est pas destinée (assertion sur le prompt émis)
```

**Décision documentée — BM25 plutôt qu'embeddings, par défaut.** La base fait 30
fiches. Charger `sentence-transformers` (~800 Mo, torch) sur une machine dont le
`/` est un disque mécanique, pour trier 30 documents, ne se justifie que si BM25
échoue. Mesure qui tranche : **rappel@3** du bon cas passé. Seuil : si BM25 < 0,80,
on ajoute les embeddings et on publie les deux chiffres dans `docs/dataset.md`.
Sinon on garde BM25 et on écrit pourquoi. (Même raisonnement que l'extra `entity`
resté désinstallé sur catalog-reliability-pipeline.)

**Mesure qui conditionne toute la phase 3 — la calibration.** L'arbitre route sur
la confiance annoncée. Si les trois agents annoncent > 0,8 sur plus de 80 % des
cas, la confiance ne porte aucune information et la règle de routage est bâtie sur
du sable. On mesure donc, par agent : taux de réussite **solo** par catégorie,
courbe de fiabilité (confiance annoncée vs. exactitude réelle) et score de Brier.
Repli prévu si la calibration est plate : forcer la confiance à dériver du
**nombre de preuves citées** et non d'une auto-évaluation, puis re-mesurer.

Coût de cette phase : 3 agents × 45 incidents = 135 appels, ~2,5 $ en Opus 5.

**Ordre** : `fake.py` et les tests **d'abord** (les agents naissent testables) →
`client.py` + `cache.py` → `infra` → `app` → `retrieval` + `history` → calibration.

**Critère de sortie** : chaque agent est vert hors réseau ; le tableau
« taux solo par agent × catégorie » et les courbes de calibration existent ;
`test_isolation.py` prouve l'étanchéité des vues. **Je te montre ce tableau : il
dit déjà si la thèse tient.**

---

## Phase 3 — Arbitre + graphe LangGraph + trace auditable

```
council/
  agents/arbiter.py       les 3 règles : convergence / divergence partielle /
                          désaccord total (rapport multi-pistes, pas de choix forcé)
  orchestration/
    state.py              InvestigationState (TypedDict) ; hypotheses et
                          clarifications en Annotated[list, operator.add] —
                          c'est le réducteur qui rend le fan-in possible
    graph.py              dispatch (fan-out 3 branches parallèles) → collect
                          (fan-in) → route (arête conditionnelle) → [clarify]* →
                          synthesize
    routing.py            fonction pure state -> "consensus" | "clarify" |
                          "no_consensus" — testable SANS LangGraph et sans LLM
    trace.py              1 ligne JSON par transition : run_id, incident_id, nœud,
                          décision, POURQUOI, jetons, latence
  cli.py                  typer : investigate / dataset / benchmark / replay
tests/
  test_routing.py         table de vérité complète des 3 règles, 0 appel LLM
  test_max_rounds.py      2 relances maximum, même si le divergent s'entête
  test_graph_integration.py  graphe complet sur 1 incident simple, client simulé
  test_trace.py           la trace rejouée reconstitue la décision finale
```

Le point de conception : **`routing.py` est une fonction pure**, séparée du graphe.
La logique métier (quand y a-t-il consensus ? à quel seuil de confiance ?) se teste
exhaustivement en mémoire, en millisecondes ; LangGraph ne fait plus que du câblage.
Le compteur de relances vit dans l'état et le plafond est appliqué **dans le
routeur**, pas dans le nœud — une boucle infinie facturée est le mode de panne
qu'on refuse d'avoir.

`council replay <run_id>` rejoue la trace JSONL et réaffiche le raisonnement
complet : c'est le livrable « auditable » demandé, et il ne coûte rien.

La version de `langgraph` sera relevée et épinglée au démarrage de cette phase
(API des réducteurs et du fan-out à vérifier sur la version installée, pas de
mémoire).

**Ordre** : `routing.py` + sa table de vérité → `state.py` → `arbiter.py` (client
simulé) → `graph.py` → `trace.py` → test d'intégration → CLI.

**Critère de sortie** : `council investigate <id>` produit le rapport complet
(cause retenue ou absence de consensus, pistes écartées et pourquoi, confiance,
nombre d'allers-retours, coût en jetons) ; `make test` vert et **hors réseau**.

---

## Phase 4 — Baseline, benchmark, et rapport honnête

La partie qui donne sa valeur au projet. Elle n'est pas un sous-produit des autres.

```
council/
  agents/baseline.py      mono-agent : métriques + logs + cas similaires mélangés
                          dans un seul prompt, même modèle, MÊME schéma de sortie
  benchmark/
    runner.py             les 4 bras sur les 45 incidents, reprise après arrêt
                          budget, écriture incrémentale (un plantage ne perd rien)
    metrics.py            réussite globale et par catégorie ; taux d'accord ;
                          corrélation accord↔exactitude ; coût ; latence
    stats.py              Wilson (IC 95 %), McNemar apparié, phi
    report.py             docs/benchmark.md — tableau des 4 bras
    plots.py              results/*.png
results/
  raw/<run_id>/*.jsonl    traces brutes, versionnées
  accuracy_by_category.png
  consensus_vs_accuracy.png
docs/benchmark.md
```

**Équité envers la baseline, écrite avant de connaître les résultats** :

- même modèle, même effort, même schéma de sortie, même taxonomie fermée ;
- elle reçoit **toute** l'information, y compris les cas historiques similaires
  (sinon on lui cache une source et la comparaison est truquée) ;
- elle tourne à **deux niveaux d'effort** et on retient **son meilleur score**.
  Elle est bon marché ; lui donner sa meilleure chance ne coûte que ~2 $.

**Le tableau de tête du rapport** — colonnes figées maintenant, remplies plus tard :

| Bras | Réussite (IC 95 %) | Infra | Appli | Historique | Ambigu | Appels/inc. | Coût total | Latence méd. |
|---|---|---|---|---|---|---|---|---|

**Trois mesures qu'on publiera même si elles fâchent** :

1. **La convergence prédit-elle l'exactitude ?** Table 2×2 (3/3 d'accord vs non) ×
   (correct vs non), coefficient phi, test exact. Si les cas de convergence ne sont
   **pas** plus souvent justes, la thèse centrale du projet tombe et le rapport
   l'écrit en tête.
2. **Par catégorie.** Il est attendu que la baseline gagne sur l'infra pure (signal
   évident, la décomposition n'apporte rien et ajoute du bruit). Ce résultat sera
   dans le tableau, pas dans une note de bas de page.
3. **Comportement sur les cas ambigus.** Le bon comportement n'y est pas de trouver
   la cause, c'est de **s'abstenir**. Mesure dédiée : taux de « pas de consensus »
   sur les ambigus vs sur les autres. Un système qui tranche avec assurance sur les
   cas ambigus est *moins* bon, et le rapport le présentera ainsi.

**Garde-fou budgétaire** : `BudgetGuard` vérifie le coût cumulé **avant** chaque
appel. Dépassement ⇒ `BudgetExceeded` ⇒ arrêt propre, résultats partiels écrits,
rapport marqué « PARTIEL — budget épuisé à N/45 ». Testé avec un plafond de 0 $.
`council benchmark --dry-run` chiffre le run **avant** le premier appel facturé.

**Ordre** : `stats.py` (+ tests sur des cas connus à la main) → `runner.py` avec
le client simulé sur les 45 incidents (0 $, valide toute la tuyauterie) →
`--dry-run` → baseline → run réel → `metrics` → `plots` → `docs/benchmark.md`.

**Critère de sortie** : `make benchmark` produit `docs/benchmark.md` + les PNG,
sous plafond ; chaque chiffre du rapport est régénérable à partir des JSONL bruts.

---

## Phase 5 — Durcissement + README

- `README.md` : **première phrase = le résultat chiffré**, dans la forme
  « Sur 45 incidents synthétiques, le conseil d'agents identifie la bonne cause
  dans X % des cas contre Y % pour un agent unique, pour Z fois le coût » — et si
  X ≤ Y, c'est cette phrase-là qui est écrite. Ensuite l'architecture, ensuite la
  technique.
- `tests/test_readme_claims.py` : les chiffres du README sont recalculés depuis
  `results/raw/` en CI. Un README qui ment devient un test rouge.
- GitHub Actions : `make lint` + `make test` (hors réseau, donc gratuit en CI).
- `docs/decisions.md` : le journal des arbitrages (BM25 vs embeddings, calibration,
  seuils de routage), chacun avec sa mesure et sa date.

---

## Coût prévisionnel (à remplacer par `--dry-run`)

Hypothèses : spécialiste ≈ 1 400 jetons in / 900 out (effort `low`) ; arbitre
≈ 2 200 / 1 600 (effort `high`) ; clarification sur ~30 % des cas.

| | Opus 5 | Sonnet 5 |
|---|---|---|
| Phase 2 (calibration, 135 appels) | ~2,5 $ | ~1,0 $ |
| Une passe de benchmark, 4 bras, 45 incidents | ~11,5 $ | ~4,5 $ |
| Trois passes (mesure de la variance) | ~35 $ | ~14 $ |

Estimation à ±40 % : les jetons de réflexion sont facturés en sortie et leur
volume n'est pas connu d'avance. Le `--dry-run` de la phase 4 donnera le chiffre
réel avant toute dépense.

---

## Points ouverts (à trancher avant la phase 2 ; la phase 1 n'en dépend pas)

| # | Sujet | Options | Ma recommandation |
|---|---|---|---|
| 1 | Emplacement / nom du dépôt | `/home/bechir/incident-council` (créé) ; `git init` + GitHub comme ForeScale ? | garder le nom, `git init` tout de suite, pousser à la fin de la phase 1 |
| 2 | Clé API Anthropic | aucune trouvée sur le poste | la mettre dans `.env` avant la phase 2 ; phases 1 et tests n'en ont pas besoin |
| 3 | Modèle et budget | **A** : Sonnet 5, 3 passes (~14 $) — **B** : Sonnet 5 ×3 + 1 passe Opus 5 en sensibilité (~25 $) — **C** : Opus 5, 3 passes (~35 $) | **B** : on mesure la variance *et* on sait si le gain multi-agents dépend du modèle — c'est un résultat en soi |
| 4 | Plafond dur du `BudgetGuard` | valeur en dollars | 1,5× l'option retenue, pour qu'un dépassement signale un bug, pas une estimation optimiste |

Langue : docs et prompts en français, code et commits en anglais — comme
catalog-reliability-pipeline. Dis-moi si tu veux autre chose.
