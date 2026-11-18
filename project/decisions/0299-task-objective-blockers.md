# 0299 — Résultat métier des tâches bloquées

Date: 2026-11-18

Status: accepted

Un jalon obligatoire déclaré `blocked` à la fin d'une exécution normale signifie que
l'objectif reste à atteindre. La tâche conserve la phase terminale `SUCCESS` et publie
`outcome=BLOCKED`. Le motif déclaré, le bilan, la trace et les effets confirmés restent
consultables. Une attente durable existante conserve la priorité. La règle de clôture
continue de traiter les échecs du moteur comme `ERROR`.

Les étapes qui dépendent du résultat sont écartées, et le plan parent expose le blocage.
Le retour d'un pair transmet aussi le motif à la tâche qui attendait sa réponse. Une
activité de processus dont la tâche est bloquée produit un diagnostic de blocage et
empêche l'utilisation des sorties attendues. Les tâches historiques conservent leur état.
La commande explicite de relance rouvre les tâches exécutables bloquées et préserve les
étapes déjà réussies. Les attentes résolues par un pair restent des traces de coordination.

La lecture du plan et la clôture sont déterministes. Une expérimentation sur le modèle
Décision pourrait comparer la déclaration du blocage avec celle de l'exécuteur actuel,
à partir des mêmes objectifs et reçus d'outils synthétiques. Les cas doivent couvrir
objectif atteint, résultat invérifiable, complément facultatif indisponible, attente
déjà ouverte et panne technique. Mesurer les faux succès, faux blocages, coût total par
tâche et latence p50/p95. Une variante ne réduit le coût total que si elle remplace du
travail de l'exécuteur. Conserver la rédaction du bilan dans le parcours d'exécution.
