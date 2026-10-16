# 0194 — Préanalyse décisionnelle des messages conversationnels

Statut : accepté — 16 octobre 2026.

## Contrat

Le contrôleur de conversation texte appelle une préanalyse du dispatcher uniquement lorsque
le profil effectif de l'agent configure un modèle Décision. Le dispatcher des Tasks, leurs
routes, efforts et drivers restent inchangés. Les commandes déterministes et les réponses
forcées conservent leurs courts-circuits. La porte `EXEC`/`END` des pairs IA reste prioritaire.
Cette décision complète l'[ADR 0101](0101-dispatch-without-action-judgment.md) : aucun jugement
après réponse ni contrôle d'absence d'outil n'est réintroduit.

Deux choix fermés indépendants examinent le rattachement à une interaction ou un travail actif,
et le lancement d'un nouveau processus métier affecté. Ils peuvent reconnaître une réponse et
un nouveau lancement dans le même message. Plusieurs cibles indissociables ou une ambiguïté
restent `uncertain`. Une demande de suivi est `related`, pas une réponse qui débloque un travail.
Les identifiants viennent exclusivement des candidats serveur. Une Task utilise son URI
canonique ; un lancement fournit l'identifiant de définition et le `workflow_id` accepté par l'outil.
Une interaction conserve sa référence exacte et, lorsqu'ils existent, sa Task et son run.
Une attente issue d'une projection conserve un localisateur à résoudre avant toute réponse.

## Responsabilités et absence de conclusion

Chaque axe expose `not_evaluated`, `uncertain`, `none` ou `selected`. Sans modèle Décision,
aucun appel de préanalyse ni chargement supplémentaire du catalogue Process n'a lieu. Un
catalogue absent ou tronqué ne prouve jamais `none`. Les candidats sont bornés à 200 par axe
et le contexte à 60 000 caractères ; un dépassement du contexte rend la préanalyse indisponible.
Le catalogue de décision n'est pas limité à la publicité de dix processus du prompt.

Le résultat est injecté vers la fin du prompt conversationnel. En l'absence de conclusion,
l'exécuteur doit lui-même rechercher une attente et sélectionner puis lancer un Process si
nécessaire. Cette instruction s'applique aussi aux exécuteurs vocaux, dont les chemins directs
ne passent pas par cette préanalyse textuelle. Une sélection n'exécute rien : l'exécuteur prépare
les valeurs et appelle les outils canoniques, qui revérifient état, fraîcheur et droits.

Les inférences utilisent le service durable Décision et sa politique de repli configurée.
Une erreur de préanalyse rend la responsabilité à l'exécuteur ; elle ne provoque aucun retry
supplémentaire de fournisseur. L'annulation se propage. Les appels portent le round et le run
conversationnels avec `task_id=NULL`. Les coûts et la provenance restent dans la trace du round.

## Vérification

Les tests unitaires couvrent l'activation conditionnelle, les deux axes indépendants, les
références exactes, les catalogues incomplets, les cibles inconnues et l'annulation. Le test
du contrôleur vérifie l'injection effective et les pièces jointes. Les scénarios PostgreSQL
de `test_decision_workflows.py` utilisent la résolution réelle du profil et le cycle durable,
avec remplacement du seul transport HTTP fournisseur. Ils vérifient absence d'inférence sans
modèle, provenance conversationnelle, coût, échec et absence de lancement par la préanalyse.
La qualité sémantique et la latence avec un fournisseur réel restent à mesurer.
