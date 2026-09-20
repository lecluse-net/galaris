# ADR 0024 — Création gouvernée et réemploi prioritaire des dossiers thématiques

- Statut : Accepted
- Date : 2026-08-02

## Contexte

Le classement Dream pouvait choisir directement entre réutiliser un dossier thématique et en
créer un. La liste bornée aux dossiers les plus récents, puis l'application aveugle d'une décision
`create`, favorisaient la fragmentation : des variantes de formulation ou des activités ponctuelles
pouvaient devenir de nouveaux dossiers alors qu'un thème durable existait déjà.

La création doit aussi relever d'une politique d'instance explicite. Certaines installations
veulent l'interdire, d'autres demander une décision humaine, et d'autres conserver une création
entièrement automatique.

## Décision

Le paramètre PostgreSQL `DREAM_TOPIC_CREATION_MODE` accepte trois valeurs :

- `forbid` interdit toute création automatique ; une réutilisation reste appliquée ;
- `propose`, valeur par défaut, transforme une proposition de création en interaction Messenger
  persistante adressée à l'utilisateur d'origine ;
- `auto` applique immédiatement la création après tous les contrôles de réemploi.

Le paramètre `ai.topic-classification-system-prompt` permet à l’administrateur d’ajouter des
instructions Markdown propres à l’instance au prompt système du classifieur. Une valeur vide
conserve le comportement standard. Ces instructions complètent le socle commun au lieu de le
remplacer, afin que les contrats structurés, la confidentialité des métadonnées publiques et la
priorité donnée au réemploi restent invariants.

Le classifieur suit désormais deux étapes structurées. La première ne peut que choisir un UUID
existant ou déclarer qu'aucun candidat ne convient. La seconde ne peut proposer une création et
n'est appelée qu'après cet échec. Les candidats sont sélectionnés par pertinence lexicale par
rapport à l'activité, avec des dossiers fréquemment utilisés conservés comme points d'ancrage.
Leur nombre d'activités est fourni au modèle pour favoriser les thèmes déjà établis.

Avant toute proposition humaine ou création automatique, une barrière déterministe reconvertit en
réemploi les titres ou ensembles de mots-clés quasi équivalents. Au moment de l'écriture, un verrou
transactionnel PostgreSQL et une normalisation accent/casse/ponctuation empêchent deux décisions
concurrentes de créer le même titre logique.

En mode `propose`, l'interaction offre trois types de réponse : créer le dossier proposé, rattacher
l'activité à l'un des candidats autorisés, ou laisser l'activité non classée. Le payload préparé,
la politique et les UUID admissibles sont checkpointés avant l'effet. L'interaction possède une
clé d'idempotence dérivée du reçu Dream et sa réponse est limitée à la conversation et, lorsqu'il
est connu, à l'utilisateur d'origine. Une cible sans route humaine exploitable reste non classée.

Les mécanismes `topic.classify_task` et `topic.classify_voice_session` adoptent cette politique.
Ce changement remplace uniquement la politique de classement décrite dans l'ADR 0020 ; le modèle
global des Topics et leurs projections mémoire reste inchangé.

## Conséquences

- Le comportement par défaut ne crée plus silencieusement un nouveau dossier.
- Le mode automatique conserve son autonomie, mais la création n'est atteinte qu'après un passage
  de réemploi dédié et une déduplication déterministe.
- Le mode interdit peut laisser volontairement une activité sans `topic_id`.
- Une proposition en attente survit aux reprises du worker et n'est envoyée qu'une fois.
- Le choix humain ne peut réutiliser qu'un UUID checkpointé par le serveur.
- Les paramètres Dream existants sont complétés sans nouvelle table ni migration manuscrite.

## Preuves dans le code

`back/app/topic/classifier.py`, `back/app/topic/service.py`,
`back/app/dream/mechanisms/topic_classification.py`,
`back/app/messenger/interactions.py`, `back/core/params/`, `front/core/params/` et leurs tests.
