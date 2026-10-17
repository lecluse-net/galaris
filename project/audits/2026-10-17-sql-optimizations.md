# Audit des optimisations SQL

Le 17 octobre 2026, l'inspection transversale du backend a identifié douze chantiers,
dont quatre évalués sur PostgreSQL 17 avec des données synthétiques. Les premiers
lots proposés concernent l'attribution des Topics, les listes Process et les
lectures groupées des Tools. Les prototypes restent des expériences locales ;
aucun correctif applicatif n'est livré par cet audit.

## Mesures sur les prototypes

Les comparaisons utilisent une base éphémère préparée par le runner de tests du
dépôt et le schéma DbAdmin. Chaque scénario est exécuté trois fois sur les mêmes
données, en vérifiant l'égalité des résultats entre l'implémentation et le prototype.
Les durées sont des médianes locales, hors préparation de la base et transport HTTP.

| Scénario synthétique | Lectures SQL actuelles | Lectures du prototype | Durée actuelle | Durée du prototype |
|---|---:|---:|---:|---:|
| Liste de 50 exécutions Process | 152 | 4 | 48,12 ms | 3,91 ms |
| Retrait des références de 100 fichiers, dont un encore partagé | 202 | 4 | 84,10 ms | 15,16 ms |
| Recherche d'une Console absente parmi 30 connexions | 31 | 2 | 8,83 ms | 0,71 ms |
| Attribution de 40 000 appels LLM aux Topics via 2 000 ProcessRun | 1 | 1 | 463,29 ms | 12,25 ms |

L'implémentation actuelle précède le prototype dans chaque passage : ce dernier
peut bénéficier d'un cache plus chaud. Ces mesures ne qualifient ni la charge
concurrente, ni les latences en production. Les sept sondes exécutées réussissent :
Process à 10 et 50 éléments, stockage à 10 et 100 éléments, inventaire des index,
routage Console et attribution des Topics.

## Corrections prioritaires

### Attribution des Topics par jointures

Dans [`app.topic.service`](../../back/app/topic/service.py), `_llm_call_topic_id`
construit des sous-requêtes scalaires corrélées pour retrouver la Task ou le round
conversationnel d'un ProcessRun. L'expression intervient dans le filtre et le
regroupement. Sur le scénario mesuré, deux sous-plans effectuent chacun 40 000
boucles. Le plan actuel relève 481 031 blocs partagés déjà en cache, contre 1 172
dans le prototype avec jointures. Les vingt totaux par Topic sont identiques.

Remplacer ces sous-requêtes par une projection jointe commune aux requêtes
d'attribution. Préserver la priorité entre Task directe, Task du Process, round du
Process et round direct, les suppressions logiques et les scopes d'agents.
L'unicité de `ConversationProcessLink.process_run_id` permet de joindre sans
multiplier les appels. La mesure couvre le chemin ProcessRun vers Task ; les
autres branches et les cas historisés restent à qualifier avant intégration.

### Sérialisation groupée des listes Process

Dans [`process_service`](../../back/app/process/process_service.py), `_run_read`
rafraîchit chaque run, puis lit sa définition et son agent. Le scénario de cinquante
runs du même processus et agent produit 152 lectures SQL : l'identity map ne
conserve pas nécessairement ces objets entre les itérations. Deux lectures groupées
des références et la suppression des rafraîchissements par ligne ramènent le total
à quatre, avec égalité complète des réponses sur le scénario.

Introduire une sérialisation groupée pour les listes HTTP, MCP et de supervision.
Conserver le rafraîchissement explicite des réponses unitaires après mutation,
les libellés de définitions historisées et les replis du `launch_snapshot`.
Qualifier les transitions concurrentes et ces replis avant intégration.

### Lectures groupées des Tools

Dans [`console.connection_service`](../../back/app/console/connection_service.py),
la recherche parcourt les connexions actives et appelle `get_tool_by_id` pour
chacune. Chaque appel émet une lecture explicite avec `populate_existing`.
Une recherche ciblée du Tool puis de sa connexion remplace les 31 lectures du
scénario par deux.

La recherche de variantes a repéré 23 occurrences structurelles dans quinze
fichiers, inspectées dans leur contexte :

| Domaine | Surfaces concernées |
|---|---|
| Console et Browser | `console/connection_service.py`, `browser/service.py`, `browser/network.py` |
| Tools | `tools/agent_registry.py`, deux boucles de `tools/mcp_loader.py` |
| File Sharing | cinq boucles de `file_share/file_share_service.py` |
| Messenger | quatre boucles de `messenger/service.py`, `messenger/session.py` |
| Connection | `connection/connection_service.py`, `connection/agent_admin_service.py` |
| Bridges | Calendar, Mail, Hermes, Matrix Voice et Nextcloud Voice |

Ces occurrences ont des fréquences et des priorités différentes ; seul Console a
été mesuré dynamiquement. L'historique Messenger déduplique déjà les identifiants
de Tool : son surcoût dépend des Tools distincts, pas directement des messages.

Pour les fonctions parcourant tous les Tools, réutiliser
[`get_tools_by_ids`](../../back/app/tools/facade.py). Si seuls les codes sont
nécessaires, `get_tool_codes` évite les configurations complètes. Préserver la
fraîcheur des configurations, les connexions actives, les capacités et l'ordre de
sélection. Le prototype Console couvre le cas absent ; les connexions présentes,
inactives et les paramètres globaux, locaux ou chiffrés restent à tester.

### Retrait groupé des références de fichiers

Dans [`core.storage.lifecycle`](../../back/core/storage/lifecycle.py), chaque
fichier provoque une vérification des alias restants, puis une lecture de
`StoredFile`. Le prototype sélectionne les fichiers devenus orphelins par
`NOT EXISTS` dans une lecture groupée, puis conserve `soft_delete` et `flush`.
Il garde le verrou de volume, le contrôle d'identité et le fichier encore partagé.
Chaque mesure est annulée par rollback d'un savepoint.

Conserver les tombstones, les octets jusqu'au commit et la reprise du purgeur.
Compléter la qualification avec le rollback complet et les enregistrements
concurrents avant intégration.

## Autres chantiers identifiés

Les pistes suivantes sont étayées par le code ; leur gain indépendant reste à
mesurer avec une distribution représentative.

| Chantier | Constat | Correction à évaluer |
|---|---|---|
| Index redondants | Le schéma déclaré contient 27 index explicites sur les mêmes colonnes que leur clé primaire, sans prédicat partiel ; notamment `ix_llm_calls_id`, `ix_tasks_id` et `ix_connections_id`. | Retirer uniquement les `index=True` redondants des modèles, puis faire converger le schéma par DbAdmin. Mesurer le stockage et les écritures ; préserver contraintes, index partiels et composites. |
| Colonnes des listes Process | Les modèles complets chargent `raw_snapshot` et `analysis`, absents de `ProcessRunRead`, puis les rafraîchissements les relisent. | Définir une projection de liste conservant les champs publics et les replis utiles, sans réduire les détails ni les données de reprise. Le prototype de regroupement charge encore ces colonnes une fois. |
| Résolution des contacts | [`_canonical_contact_index`](../../back/app/contact/service.py) parcourt tous les contacts par pages de 500, avec total et comptes de souvenirs liés inutilisés, même après une recherche vide. | Résoudre par une façade Memory les seules identités trouvées ; préserver propriété, identités fortes et fusion entre canaux. Garder les totaux des pages publiques de l'annuaire. |
| Métriques de la page Topics | [`list_page`](../../back/app/topic/service.py) agrège le mois pour tous les Topics avant la pagination ; le tri dépend des dates du Topic. | Sélectionner la page d'abord, puis calculer ses métriques. Préserver total, recherche, mois et scopes. |
| Supervision conversationnelle | [`list_messages`](../../back/app/conversation/monitoring_service.py) joint la résolution du round courant par room à chaque message, puis réemploie ces jointures dans les compteurs. | Examiner les plans et l'éventuel `Memoize`, puis résoudre une fois par room et alléger les compteurs selon les filtres. Préserver les priorités de statut et la visibilité. |
| Mois disponibles | [`Dashboard`](../../back/app/dashboard/dashboard_service.py) et Topics recalculent les mois distincts depuis les historiques à chaque réponse. | Évaluer une projection mensuelle ou une lecture incrémentale si les mesures justifient sa maintenance. Conserver les scopes et fuseaux ; min/max inventerait des mois absents. |
| Accès inverse aux membres Messenger | [`RoomUser`](../../back/app/messenger/models.py) a une clé primaire `(room_id, user_id)`, sans index commençant par `user_id`. | Mesurer les parcours réellement filtrés par utilisateur avant d'évaluer `(user_id, room_id)` ; ne pas indexer indistinctement toutes les FK signalées. |
| Pagination du catalogue Tools | [`agent_admin_service.list_tools`](../../back/app/connection/agent_admin_service.py) charge tout le catalogue, filtre et pagine dans Python, puis relit chaque Tool de la page pour vérifier son existence. | Supprimer les relectures ; évaluer ensuite recherche et pagination SQL en préservant la sémantique Unicode de `casefold`. |

## Ordre de réalisation et garanties

Commencer par l'attribution des Topics et la sérialisation Process. Étendre ensuite
les lectures groupées des Tools par familles de consommateurs : Console,
MCP et File Sharing, puis messageries et bridges. Traiter le stockage et les index
redondants avec leurs contrôles de suppression et de convergence du schéma.

Les tests inspectés de Process, Console et stockage vérifient les comportements
fonctionnels mais ne plafonnent pas les lectures sur ces parcours. Réutiliser
[`tests.sql_reads.measured_reads`](../../back/tests/sql_reads.py) pour protéger le
nombre de lectures sur de vraies opérations DB à plusieurs tailles, sans figer le
texte exact des requêtes. Les scénarios doivent aussi préserver les autorisations,
les suppressions logiques, les reprises et les effets des mutations concurrentes.

La revue est transversale et non exhaustive. Les mesures portent sur des appels
de service synthétiques, sans qualification de l'application assemblée. Les
diagnostics bruts et scripts locaux restent exclus du dépôt ; cet audit conserve
uniquement les mesures agrégées et les conclusions techniques.
