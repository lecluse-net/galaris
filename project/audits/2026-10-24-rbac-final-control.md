# Dernier contrôle des privilèges fonctionnels

Date : 24 octobre 2026. Contrôle du code après la réorganisation décrite par la
[décision 0233](../decisions/0233-functional-domain-privileges.md).

> Suivi : les correctifs et leur qualification après cet audit sont consignés dans le
> [contrôle d’isolation fonctionnelle](2026-10-24-rbac-functional-isolation.md). Les observations
> ci-dessous restent la photographie antérieure aux correctifs.

## Conclusion

**Le catalogue est cohérent, mais la séparation n'est pas exhaustive.** Les 24 nouveaux
droits sont présents, déclarés et consommés. Cela ne prouve pas qu'ils protègent tous les
chemins d'accès aux données. Le contrôle complémentaire reproduit cinq écarts HTTP sur
quatre familles de parcours et identifie des fonctions encore couvertes par des droits
généraux. La conclusion précédente de réorganisation entièrement qualifiée était trop large.

Ce contrôle est un audit : il ne modifie ni politique applicative, ni catalogue, ni rôle.
Les résultats ci-dessous décrivent les écarts encore présents, pas des correctifs livrés.

## Inventaire recroisé

| Mesure | Résultat |
|---|---:|
| Privilèges déclarés dans les modules actifs | 109 |
| Domaines déclarant au moins un code | 29 |
| Codes déclarés sans référence backend de production | 0 |
| Codes inconnus dans les gardes chargés | 0 |
| Codes inconnus dans la navigation générée | 0 |
| Enregistrements HTTP inspectés | 797 |
| Avec garde RBAC | 737 |
| Publics explicitement déclarés | 13 |
| Avec authentification indépendante | 47 |
| WebSockets avec contrôles propres | 2 |
| Handlers distincts HTTP/WebSocket | 735 |
| Entrées de navigation inspectées | 54 |
| Pages Vue recensées | 51 |

Les alias sont inclus dans les enregistrements. Une référence de production démontre un
consommateur, pas la correction de chaque autorisation. Les six tests existants de
`core/authorize/tests/test_route_security.py` passent ; ils vérifient les politiques
enregistrées et les exceptions, sans détecter tous les réemplois fonctionnels ci-dessous.

## Écarts reproduits sur PostgreSQL éphémère

Les utilisateurs, rôles, agents, processus, tâches, Topics et mails de reproduction sont
entièrement synthétiques. Les cas attendent la séparation fonctionnelle ; leurs cinq échecs
sont les résultats de cet audit, pas une suite présentée comme réussie.

| Priorité | Profil et action | Résultat observé | Garantie à établir |
|---|---|---|---|
| P1 | `MEMORY_ACCESS` seul lit un run Process rattaché à son agent géré | HTTP 200, données du run retournées | Les données Process requièrent un droit Process, en plus de leur ACL |
| P1 | `TOPIC_ACCESS` seul ouvre le contenu d'un dossier lié à une tâche de son agent | L'API Task directe refuse avec 403 ; le dossier retourne l'objectif de la tâche | Le résumé transversal doit respecter les droits de chaque contenu exposé, ou annoncer explicitement un pouvoir transversal distinct |
| P1 | Approbateur Mail désigné, avec `CONNECTION_ACCESS` seul | Le rejet réussit avec 200 sans `PERMISSION_DECIDE` | Les décisions Mail suivent le droit fonctionnel de décision, en conservant l'identité de l'approbateur |
| P2 | `CONVERSATION_ACCESS` seul résout les libellés compacts des Topics | HTTP 403 | L'historique peut résoudre ses libellés sans ouvrir les analyses Topics |
| P2 | `VOICE_HISTORY_ACCESS` seul résout les mêmes libellés | HTTP 403 | Même garantie pour l'historique vocal |

Les trois premiers cas restent limités aux objets accessibles dans le périmètre de
l'utilisateur, ou à l'approbateur explicitement désigné. Ils ne démontrent pas un accès
arbitraire aux données d'un autre utilisateur. Ils montrent que des rôles fonctionnels
annoncés comme séparés conservent des pouvoirs transversaux.

### Process : variantes localisées

Huit handlers de `back/app/process/native_router.py` acceptent `MEMORY_ACCESS` : aperçu et
options de ressources, inspection du run et d'un nœud, fichier du run, occurrences d'une
activité, enfants et métriques. L'inspection d'un run a été reproduite avec ses vraies
données. Les sept autres occurrences sont des variantes confirmées de la même déclaration
de garde ; leur effet n'a pas été reproduit individuellement.

Les ACL Process de `native_access.py` et `native_runs.py` restent actives. Elles ne
remplacent pas le droit fonctionnel Process. Les aperçus partagés doivent conserver une
autorisation explicite de la source, comme le navigateur de fichiers déjà réorganisé.

### Topics : projection transversale et métadonnées

`back/app/topic/router.py` protège le contenu transversal par `TOPIC_ACCESS` ou `TOPIC_EDIT`.
`service.get_content` assemble objectifs Task, messages des rounds texte/vocaux, extraits
Memory et références Document/Dataset, avec portée et ACL mais sans filtre des privilèges
fonctionnels de ces domaines. La lecture d'un objectif Task a été démontrée. Les autres
sections sont identifiées par lecture du code et des DTO ; leurs contenus respectifs
n'ont pas tous fait l'objet d'une reproduction HTTP dans ce contrôle.

Inversement, `/topics/refs` n'accepte que `TASK_ACCESS`, `TOPIC_ACCESS` et `TOPIC_EDIT`, alors
que les deux nouveaux historiques l'appellent via `useTopicRefs`. Leurs listes vides ne
déclenchaient aucun appel dans les précédents scénarios minimaux. Avec un Topic existant,
les deux lecteurs reçoivent un refus. La correction doit porter sur le DTO minimal
`id/title`, en maintenant le refus d'accès aux analyses et contenus Topics.

### Mail : décisions et journal encore couplés aux connexions

Les décisions de `bridge.mail.router` utilisent encore `CONNECTION_ACCESS` avec
`MailApproverAssertion`. Le service vérifie bien l'approbateur et la validité de la demande.
Le nouveau `PERMISSION_DECIDE` n'intervient pas dans cette frontière. Le journal entrant et
sortant utilise également `CONNECTION_ACCESS`, ce qui empêche une délégation de lecture Mail
indépendante de la consultation des connexions.
La reproduction HTTP utilise une livraison en attente sans autorisation commune attachée,
sur le chemin de compatibilité encore maintenu. Le chemin courant avec autorisation commune
est identifié par lecture du code ; il n'est pas couvert par cette reproduction.

## Correspondance des fonctions et des droits existants

| Fonction ou pouvoir | Codes présents |
|---|---|
| Comptes administrés | `READ_USER`, `CREATE_USER`, `UPDATE_USER`, `DELETE_USER` |
| Rôles | `READ_ROLE`, `MANAGE_ROLE` |
| Affectations | `READ_ASSIGNMENT`, `MANAGE_ASSIGNMENT` |
| Catalogue et listes de privilèges | `READ_PRIVILEGE`, `MANAGE_PRIVILEGE` |
| Équipes et membres | `TEAM_ACCESS`, `TEAM_EDIT`, `TEAM_MEMBERS_EDIT` |
| Agents, périmètre global et API Agent | `AGENT_ACCESS`, `AGENT_EDIT`, `AGENT_MANAGE_ALL`, `AGENT_API_ACCESS` |
| Outils et connexions | `TOOL_ACCESS`, `TOOL_EDIT`, `CONNECTION_ACCESS`, `CONNECTION_EDIT` |
| Permissions et accords communs | `PERMISSION_ACCESS`, `PERMISSION_DECIDE`, `PERMISSION_REVOKE` ; exception Mail ci-dessus |
| Documents et attribution globale | `DOCUMENT_ACCESS`, `DOCUMENT_EDIT`, `DOCUMENT_ADMIN`, `DOCUMENT_ASSIGN_ALL_USERS` |
| Datasets | `DATASET_READ`, `DATASET_EDIT`, `DATASET_ADMIN` |
| Souvenirs | `MEMORY_ACCESS`, `MEMORY_EDIT`, `MEMORY_ADMIN` |
| Contacts | `CONTACT_ACCESS`, `CONTACT_EDIT` ; oubli avec souvenirs : aussi `MEMORY_EDIT` |
| Fichiers et indexation | `FILE_ACCESS`, `FILE_EDIT`, `FILE_INDEX_ACCESS`, `FILE_INDEX_RUN` |
| Topics | `TOPIC_ACCESS`, `TOPIC_EDIT` ; pouvoir transversal et libellés à reprendre |
| Tâches | `TASK_ACCESS`, `TASK_EDIT`, `TASK_PURGE` |
| Conversations texte | `CONVERSATION_ACCESS`, `CONVERSATION_CONTROL` |
| Historique vocal | `VOICE_HISTORY_ACCESS`, `VOICE_HISTORY_CONTROL` |
| Chat | `CHAT_ACCESS`, `CHAT_MANAGE`, `CHAT_SEND`, `CHAT_CALL`, `CHAT_IMPERSONATE` |
| Goals | `GOAL_ACCESS`, `GOAL_EDIT` |
| Process | `PROCESS_READ`, `PROCESS_EDIT`, `PROCESS_LAUNCH`, `PROCESS_ADMIN` ; variantes Memory à retirer |
| Skills | `SKILL_ACCESS`, `SKILL_EDIT`, `SKILL_ASSIGN` |
| Fournisseurs | `LLM_PROVIDER_ACCESS`, `LLM_PROVIDER_EDIT` |
| Modèles configurés | `LLM_MODEL_ACCESS`, `LLM_MODEL_EDIT` |
| Profils LLM | `LLM_PROFILE_ACCESS`, `LLM_PROFILE_EDIT` |
| Appels LLM | `LLM_CALL_ACCESS`, `LLM_CALL_CONTROL`, `LLM_CALL_PURGE` |
| API LLM et MCP | `LLM_API_ACCESS`, `MCP_API_ACCESS`, avec leurs authentifications et restrictions propres |
| Harnais communs | `HARNESS_CONFIG_ACCESS`, `HARNESS_CONFIG_EDIT` ; opérations par agent sous droits Agents |
| Tableau de bord | `DASHBOARD_ACCESS` |
| Dream | `DREAM_ACCESS`, `DREAM_EDIT`, avec périmètre global pour la supervision |
| Incidents | `INCIDENT_ACCESS`, `INCIDENT_EDIT`, `INCIDENT_PURGE` |
| Console et éditeur de code | `CONSOLE_ACCESS`, `CONSOLE_ADMIN`, `CODE_ACCESS` |
| Lab | 22 codes, soit 11 paires lecture/édition par mécanisme |
| Réglages globaux | `PARAMS_ACCESS`, `PARAMS_EDIT`, avec exceptions par clé Dream/Harnais/Profil LLM |

## Fonctions encore mutualisées

| Fonction | Protection actuelle | Conséquence pour la délégation |
|---|---|---|
| Journal Mail | `CONNECTION_ACCESS` | Aucun code de lecture Mail séparé |
| Révision d'un envoi Mail | `CONNECTION_ACCESS` et approbateur désigné | Le droit commun de décision ne représente pas encore toutes les décisions |
| Flux calendaires d'une connexion | `CONNECTION_ACCESS` / `CONNECTION_EDIT` | Configuration des flux et configuration générale de la connexion restent groupées |
| Réglages Browser | `PARAMS_ACCESS` / `PARAMS_EDIT` | Aucun administrateur Browser distinct des paramètres globaux |
| Réglages mémoire, voix, audio, Process, Tasks, recherche, Janus, instructions et logs | `PARAMS_*` | Ces réglages techniques restent un domaine d'administration global |

Les calendriers sont actuellement des flux configurés dans une connexion, sans écran de
calendrier humain autonome. Browser est ici son écran de configuration ; son exécution
agentique suit les capacités Tool et sa politique réseau. Ces mutualisations sont des
limites de granularité, pas des accès non authentifiés. Une délégation indépendante demande
un choix de domaine explicite, puis des contrôles dans les API et Params, des métadonnées
minimales et une projection des rôles revue.

Une suite cohérente serait un droit de lecture Mail, le raccordement des décisions Mail à
`PERMISSION_DECIDE`, et, si ces administrations doivent être déléguées séparément, des paires
lecture/édition Calendrier et configuration Browser. Ces codes ne sont pas créés par cet
audit. Le nettoyage Process/Topics nécessite d'abord d'appliquer correctement les codes
déjà existants ; ajouter des constantes ne suffit pas.

Des écarts de composition lecture/édition subsistent aussi dans les anciens domaines :
les menus Documents, Goals et Skills n'acceptent que le code de lecture alors que
leurs API acceptent aussi des opérateurs ; Console Admin ne suffit pas pour son écran de
statut ; l'édition native Process et sa navigation n'ont pas partout la même composition.
Ces constats proviennent du code et de la navigation chargée, sans parcours navigateur
supplémentaire pour chacun dans ce contrôle.

La lecture Teams exige au contraire explicitement `TEAM_ACCESS`, et plusieurs mutations
composent les droits par une conjonction. Ce cas ne démontre pas un écart menu/API et n'est
pas compté comme un défaut.

## Couverture, limites et prévention

L'inventaire couvre les déclarations, les gardes chargés et la navigation active. Les
reproductions traversent l'authentification HTTP et une vraie base éphémère. Aucun service
externe n'est appelé et aucune donnée réelle n'est utilisée. L'absence de code inconnu ou
inutilisé n'est pas une preuve d'isolation de tous les contenus. Aucun nouveau parcours
navigateur ni validation complète réservée à l'utilisateur n'est exécuté ici.

Les contrôles précédents vérifiaient surtout les routes principales et des catalogues vides.
Les tests de portée établissaient l'agent ou l'ACL, sans croiser systématiquement rôle
fonctionnel et ressources existantes dans les vues transversales. Les contrôles structurels
de Topics figeaient même l'ancienne liste de gardes des libellés. Les corrections doivent
être protégées par des scénarios HTTP peuplés, vérifiant un domaine voisin refusé, le domaine
légitime accepté et les métadonnées minimales sans accès au contenu complet.

Les inventaires et diagnostics reproductibles restent sous
`artifacts/rbac-final-control-2026-10-24/`. Le rapport versionné ne contient que mesures
agrégées, contrats, résultats et conclusions techniques.
