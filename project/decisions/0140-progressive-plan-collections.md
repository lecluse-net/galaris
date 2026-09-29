# 0140 — Collections de tâches développées progressivement

Statut : accepté. Date : 2026-09-27.

## Garantie et consommateurs

Une opération substantielle répétée sur des éléments indépendamment vérifiables conserve
une Task par élément. Un petit lot mécanique connu peut rester une seule feuille.
L'ordre demandé entre groupes et éléments est préservé. Les plafonds du plan
ne doivent pas transformer une collection en une feuille qui exécute une boucle entière.

Les consommateurs concernés sont le planner et son catalogue effectif, le scheduler Task,
le Working Set, la projection de progression, la commande Réessayer, les notifications
terminales et le Lab Planner. Les plans statiques existants, les pauses humaines, les ACL,
les reçus d'effets incertains et la livraison unique de la réponse restent compatibles.

## Décision

`PlanStep.collection` décrit l'inventaire et l'opération complète pour un seul élément.
`item_count` exprime le nombre d'éléments indépendants, inconnu avec `null`.
`item_work` vaut `substantial` par défaut : plusieurs éléments exigent alors une
décomposition, même avec un effort standard. L'exception `mechanical` autorise une feuille
pour au plus cinq éléments connus, avec des opérations triviales et déterministes et une
vérification simple du lot, par exemple appliquer trois noms fournis. Ce plafond conservateur
borne l'exception ; il ne suffit pas à classifier le travail comme mécanique. Lire et
transformer chaque document, exercer un jugement ou vérifier substantiellement chaque élément
reste un travail substantiel, même pour deux documents. Les volumes inconnus ou supérieurs
au plafond exigent des sous-étapes ou une collection. Aucun inventaire ni sous-tâche par
élément n'est ajouté aux petits lots mécaniques. Le dispatcher et les critères d'activation
de PLAN restent inchangés ; plusieurs cibles seules ne justifient pas cette route.
Le planner conserve la responsabilité de reconnaître sémantiquement ces collections ;
le serveur valide le contrat déclaré sans prétendre déduire ce nombre d'un texte libre.

Le découpage privilégie la répétition d'un traitement complet sur des éléments autonomes :
X fichiers indépendants donnent X traitements complets. La lecture, la transformation, la
vérification, les corrections et la mise à jour du suivi d'un élément restent dans sa Task.
Une tâche cohérente unique reste une seule feuille, même complexe ou forcée en PLAN.
Les chapitres, composants, phases et fichiers sources d'un même résultat ne constituent pas
des éléments autonomes. Les groupes organisent les collections et les résultats réellement
indépendants ; ils ne fragmentent pas le travail interne d'un exécuteur.

Cette précision aligne le planner sur l'ADR 0036. L'ancien prompt, le schéma des sous-étapes
et leurs tests encourageaient au contraire le découpage d'un artefact complexe ; cette
contrainte est retirée intentionnellement. Le prompt par défaut, le schéma et le contrat
serveur ajouté aux prompts de production et du Lab portent désormais la même règle.
Le contrat serveur prime sur une ancienne consigne personnalisée contradictoire.
Le barème Planner v4 évalue les deux erreurs : fragmenter une tâche unique ou regrouper
les traitements substantiels de plusieurs éléments dans une feuille. Il distingue les choix
du modèle des politiques techniques ajoutées par le serveur ; les campagnes précédentes
conservent leur barème figé et leurs scores.
Les politiques `artifact_policy` et `delivery_policy` sont retirées du schéma d'entrée du
modèle, sans changer leur sérialisation ni la validation des valeurs explicitement fournies.
La qualification indépendante a reproduit leur émission incorrecte malgré la consigne de
les omettre : le schéma, plutôt qu'une nouvelle consigne, porte désormais cette séparation.
Les tests de présence de formulations ne prouvent pas la qualité des choix du modèle.

Chaque collection devient un groupe PLAN. À son activation, une Task de découverte lit
l'inventaire existant ou les sources autorisées, sans réaliser les transformations. Elle
crée un Dataset JSON `galaris.collection/v1` et rend son URI dans un reçu JSON terminal.
Le serveur exige une opération de ressource enregistrée pour cette Task, relit le Dataset
par un lecteur injecté par `app.file_share` avec les ACL de l'agent, vérifie son rattachement au groupe,
sa complétude déclarée, sa taille, sa cardinalité et l'unicité des clés. L'inventaire
contient seulement les identifiants et entrées bornées, jamais tous les corps documentaires.
Son contenu validé, son URI et sa révision sont figés dans le plan durable du groupe.
Ce Dataset technique ne prouve pas la livraison d'un document demandé par l'utilisateur.
Le port de lecture appartient à `app.agent` et son adaptateur à `app.file_share` : le planner
ne dépend pas du service de fichiers concret et aucune dette de couplage n'est ajoutée.

Le moteur développe ensuite déterministement une feuille par élément avec le même modèle
d'instructions. Chaque vague comporte au plus `TASK_PLAN_MAX_LEAVES` éléments.
Le squelette initial est borné par sa profondeur et son nombre de feuilles ; chaque collection est
bornée à 1 000 éléments et 2 000 000 caractères JSON. Le plafond de profondeur comprend
le niveau des éléments et aucun sous-arbre excessif n'est aplati silencieusement.
Les nouveaux enfants ont une clé d'idempotence stable dérivée du groupe et de l'élément.
Les vagues et curseurs sont persistés avant activation. Les tâches réalisées restent
consultables ; les futurs éléments ne sont matérialisés qu'à la fin de la vague précédente.

La progression compte les éléments connus, y compris ceux qui attendent leur vague.
Le total peut augmenter lors de la découverte d'une collection suivante. L'exécution reste
séquentielle, y compris les mises à jour d'un suivi partagé. Une réconciliation de liens
entre documents peut être une étape ultérieure. Le parallélisme avec dépendances explicites
reste hors de cette décision.

Un échec conserve l'arrêt du plan et la clôture des étapes non exécutées. Réessayer un plan
terminal conserve les succès, l'inventaire figé, les curseurs et les journaux d'effets ;
seuls les descendants en erreur sont réouverts. Le groupe reprend le document en échec
avant les suivants. Les coûts des enfants déjà agrégés ne sont pas comptés deux fois.
Les plans historiques ne sont ni réécrits ni relancés automatiquement.

## Validation

`app/agent/tests/test_planner_collections.py` couvre une collection au-delà du plafond
statique, l'exception mécanique bornée (acceptation de deux à cinq éléments, refus au-delà
ou sans cardinalité), l'exécution d'un petit lot en une seule feuille sans découverte ni
replanification, le refus des feuilles substantielles multi-éléments, les vagues bornées,
les inventaires vides ou invalides, l'absence de reçu,
le refus d'accès et un parcours avec PostgreSQL et un vrai Dataset : découverte, erreur,
rechargement, modification du Dataset après gel, reprise ciblée et achèvement ordonné.
Les suites Planner, Task et Lab conservent les contrats de notification, de pause,
d'arrêt, de reprise et de validation. L'ancienne assertion de sérialisation exhaustive
du test des sous-arbres est remplacée par la conservation des objectifs et de leur ordre :
les valeurs par défaut internes ne constituent pas une garantie utilisateur.
Le scénario historique d'aplatissement à la profondeur maximale est remplacé par le
refus du plan excessif sans suppression d'instructions ; la disparition des sous-étapes
n'est plus un comportement autorisé.
