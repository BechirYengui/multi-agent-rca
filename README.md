# incident-council

> Le resultat chiffre viendra ici, en premiere phrase, a la fin de la phase 4.
> Tant que le benchmark n'a pas tourne, cette place reste vide : un README qui
> annonce un resultat avant de l'avoir mesure est exactement ce que ce projet
> cherche a ne pas faire.

Investigation d'incidents de production par trois agents specialistes
independants (infrastructure, application, historique) et un arbitre, comparee
mesure en main a un agent unique recevant tout le contexte.

Etat : **phases 1 a 4 ecrites et testees hors reseau** (85 tests, 0 $).
Le jeu de donnees est valide (`docs/dataset.md`) ; les trois specialistes,
l'arbitre, le graphe LangGraph, la baseline et le harnais de benchmark
tournent de bout en bout contre un client simule. **Il manque les mesures
reelles** : elles attendent une cle API.

Voir `docs/plan.md` (les 5 phases), `docs/dataset.md` (les 3 gardes
anti-triche) et `docs/decisions.md` (16 arbitrages, chacun avec sa mesure).
