# Isolation fonctionnelle des privilèges — contrôle complémentaire

Date : 24 octobre 2026. Suite aux écarts reproduits dans le
[dernier audit](2026-10-24-rbac-final-control.md), mise en œuvre de la
[décision 0235](../decisions/0235-functional-settings-and-source-authorization.md).

## Périmètre et résultat technique

Le catalogue actif comporte **140 codes**, dont **31 ajouts** dans cette passe.
Mail, calendriers et chaque famille de réglages disposent de leurs droits propres.
`PARAMS_*` n'ouvre que les réglages système. Chaque clé déclarée est classée ;
une nouvelle clé sans politique bloque la synchronisation au lieu de recevoir un
accès administratif implicite. Le frontend utilise le même contrat généré.

Les cinq écarts de l'audit antérieur ont une reproduction HTTP permanente avec données
synthétiques persistées. Les huit routes Process n'acceptent plus les droits Mémoire.
Le contenu Topics est filtré par domaine source et portée d'agent ; les libellés compacts
restent accessibles aux historiques concernés. Les décisions Mail gardent l'approbateur
désigné et exigent les droits de décision ; le journal exige aussi le droit d'écriture Mail.
Les boutons, réponses textuelles et reprises de choix revérifient les droits.

Le recoupement final des badges Dataset a également reproduit un refus des libellés Topics
avec chacun des trois droits Dataset. La correction étend uniquement les références
compactes ; la matrice HTTP couvre les 16 droits des domaines sources et refuse toujours
l'ouverture du contenu Topics sans droit Topics.

Les vues Mémoire, Documents et Activité utilisent des métadonnées Agents minimales.
Les Calendriers ont un parcours indépendant des paramètres Connexions. La configuration
des connexions reçoit des schémas publics sans secrets globaux Tools. Les rubriques Lab
n'appellent plus le banc Task à l'ouverture d'un autre mécanisme. Les pages attendent
le chargement des droits avant de choisir leurs lectures ou de refuser l'accès.

La projection ponctuelle des anciens rôles conserve les pouvoirs précédemment délégués,
sans modifier les identités, affectations, listes personnalisées et ACL. Elle ne
réattribue pas les droits ensuite révoqués. Les nouveaux rôles sont explicites.
Les purges, capacités d'exécution et autres exceptions sont expliquées dans la décision.

## Inventaire complet des déclarations actives

Ce tableau est dérivé des fichiers `privileges.py` des modules actifs. Tous les codes
figurent une fois ; il ne s'agit pas d'une preuve comportementale pour chaque route.

| Domaine | Codes |
|---|---|
| `app.agent` | `AGENT_ACCESS`, `AGENT_API_ACCESS`, `AGENT_EDIT`, `AGENT_MANAGE_ALL`, `JANUS_CONFIG_ACCESS`, `JANUS_CONFIG_EDIT` |
| `app.audio` | `AUDIO_CONFIG_ACCESS`, `AUDIO_CONFIG_EDIT` |
| `app.browser` | `BROWSER_CONFIG_ACCESS`, `BROWSER_CONFIG_EDIT` |
| `app.chat` | `CHAT_ACCESS`, `CHAT_CALL`, `CHAT_IMPERSONATE`, `CHAT_MANAGE`, `CHAT_SEND` |
| `app.code` | `CODE_ACCESS` |
| `app.connection` | `CONNECTION_ACCESS`, `CONNECTION_EDIT` |
| `app.console` | `CONSOLE_ACCESS`, `CONSOLE_ADMIN` |
| `app.contact` | `CONTACT_ACCESS`, `CONTACT_EDIT` |
| `app.conversation` | `CONVERSATION_ACCESS`, `CONVERSATION_CONTROL` |
| `app.dashboard` | `DASHBOARD_ACCESS` |
| `app.dataset` | `DATASET_ADMIN`, `DATASET_EDIT`, `DATASET_READ` |
| `app.document` | `DOCUMENT_ACCESS`, `DOCUMENT_ADMIN`, `DOCUMENT_ASSIGN_ALL_USERS`, `DOCUMENT_EDIT` |
| `app.dream` | `DREAM_ACCESS`, `DREAM_CONFIG_ACCESS`, `DREAM_EDIT` |
| `app.file_share` | `FILE_ACCESS`, `FILE_EDIT`, `FILE_INDEX_ACCESS`, `FILE_INDEX_RUN` |
| `app.goal` | `GOAL_ACCESS`, `GOAL_CONFIG_ACCESS`, `GOAL_CONFIG_EDIT`, `GOAL_EDIT` |
| `app.harnesses` | `HARNESS_CONFIG_ACCESS`, `HARNESS_CONFIG_EDIT` |
| `app.incident` | `INCIDENT_ACCESS`, `INCIDENT_EDIT`, `INCIDENT_PURGE` |
| `app.lab` | `CONVERSATION_EXECUTOR_EVALUATION_ACCESS`, `CONVERSATION_EXECUTOR_EVALUATION_EDIT`, `DISPATCHER_EVALUATION_ACCESS`, `DISPATCHER_EVALUATION_EDIT`, `EVALUATION_ACCESS`, `EVALUATION_EDIT`, `GOAL_TRACKING_EVALUATION_ACCESS`, `GOAL_TRACKING_EVALUATION_EDIT`, `MEMORY_EXTRACTION_EVALUATION_ACCESS`, `MEMORY_EXTRACTION_EVALUATION_EDIT`, `OUTCOME_REFLECTION_EVALUATION_ACCESS`, `OUTCOME_REFLECTION_EVALUATION_EDIT`, `PLANNER_EVALUATION_ACCESS`, `PLANNER_EVALUATION_EDIT`, `PROCESS_EVALUATION_ACCESS`, `PROCESS_EVALUATION_EDIT`, `TASK_EXECUTOR_EVALUATION_ACCESS`, `TASK_EXECUTOR_EVALUATION_EDIT`, `TOPIC_CLASSIFICATION_EVALUATION_ACCESS`, `TOPIC_CLASSIFICATION_EVALUATION_EDIT`, `VOICE_EXECUTOR_EVALUATION_ACCESS`, `VOICE_EXECUTOR_EVALUATION_EDIT` |
| `app.llm` | `LLM_API_ACCESS`, `LLM_CALL_ACCESS`, `LLM_CALL_CONTROL`, `LLM_CALL_PURGE`, `LLM_MODEL_ACCESS`, `LLM_MODEL_EDIT`, `LLM_PROFILE_ACCESS`, `LLM_PROFILE_EDIT`, `LLM_PROVIDER_ACCESS`, `LLM_PROVIDER_EDIT` |
| `app.mcp` | `MCP_API_ACCESS` |
| `app.memory` | `MEMORY_ACCESS`, `MEMORY_ADMIN`, `MEMORY_CONFIG_ACCESS`, `MEMORY_CONFIG_EDIT`, `MEMORY_EDIT` |
| `app.messenger` | `MESSAGING_CONFIG_ACCESS`, `MESSAGING_CONFIG_EDIT` |
| `app.process` | `PROCESS_ADMIN`, `PROCESS_CONFIG_ACCESS`, `PROCESS_CONFIG_EDIT`, `PROCESS_EDIT`, `PROCESS_LAUNCH`, `PROCESS_READ` |
| `app.skill` | `SKILL_ACCESS`, `SKILL_ASSIGN`, `SKILL_EDIT` |
| `app.task` | `TASK_ACCESS`, `TASK_CONFIG_ACCESS`, `TASK_CONFIG_EDIT`, `TASK_EDIT`, `TASK_PURGE` |
| `app.tools` | `PERMISSION_ACCESS`, `PERMISSION_DECIDE`, `PERMISSION_REVOKE`, `TOOL_ACCESS`, `TOOL_EDIT` |
| `app.topic` | `TOPIC_ACCESS`, `TOPIC_EDIT` |
| `app.voice` | `VOICE_CONFIG_ACCESS`, `VOICE_CONFIG_EDIT`, `VOICE_HISTORY_ACCESS`, `VOICE_HISTORY_CONTROL` |
| `bridge.calendar` | `CALENDAR_ACCESS`, `CALENDAR_EDIT` |
| `bridge.mail` | `MAIL_ACCESS`, `MAIL_EDIT` |
| `core.authorize` | `MANAGE_ASSIGNMENT`, `MANAGE_PRIVILEGE`, `MANAGE_ROLE`, `READ_ASSIGNMENT`, `READ_PRIVILEGE`, `READ_ROLE` |
| `core.params` | `INSTRUCTION_CONFIG_ACCESS`, `INSTRUCTION_CONFIG_EDIT`, `LANGUAGE_CONFIG_ACCESS`, `LANGUAGE_CONFIG_EDIT`, `LOG_CONFIG_ACCESS`, `LOG_CONFIG_EDIT`, `PARAMS_ACCESS`, `PARAMS_EDIT`, `SEARCH_CONFIG_ACCESS`, `SEARCH_CONFIG_EDIT` |
| `core.team` | `TEAM_ACCESS`, `TEAM_EDIT`, `TEAM_MEMBERS_EDIT` |
| `core.user` | `CREATE_USER`, `DELETE_USER`, `READ_USER`, `UPDATE_USER` |

## Recoupement du code chargé

- routes : 803.
- handlers : 739.
- navigation : 55.
- domains : 34.
- Aucun code inconnu dans les gardes HTTP ou la navigation.
- Aucun code déclaré sans consommateur backend de production identifié.

## Qualification et limites

Résultats exécutés :

- Suite ciblée consolidée : **408 tests backend réussis** (autorisation, paramètres,
  Topics, Goals, choix, calendriers réseau et Mail), complétée par les tests de révocation
  après capture et de transition terminale concurrente.
- Compléments : 76 tests de décisions, 3 tests de reprise/concurrence, 23 tests HTTP de
  frontières sources et 9 interactions de domaines, dont les compétences avec apprentissage
  activé et un rôle limité aux affectations. Ces séries recouvrent la suite consolidée.
- 5 tests de projection confirment aussi les révocations entre les deux générations :
  les anciens droits Harnais/Profils/Dream ne sont pas réintroduits par la seconde reprise.
- **131 parcours E2E Chromium réussis**, avec un rôle distinct par fonction et exception
  de composition explicitement déclarée.
- Interactions : 27 tests paramètres/domaines/Contacts, puis 24 tests domaines/Lab/harnais,
  20 tests de références métier et 7 parcours Goals/Mémoire réussis ; certaines suites se
  recouvrent. Les fixtures de références utilisent désormais leurs vrais droits de source.
- `make typecheck` : Pyright et vue-tsc réussis, **448 tests unitaires frontend réussis**,
  parité FR/EN/ZH vérifiée. `make lint` réussi.
- Architecture : contrôle statique et **33 tests réussis** ; baseline frontend réduite,
  sans nouvel import privé. Le seul ajout public Dream → File Share appartient à la
  décision 0233 et conserve ses gardes d'indexation.
- Convergence de développement : **140 codes**, **3 rôles préservés**, **12 catégories
  existantes et leurs placements préservés**, **2 nouvelles catégories**, **35 grants
  supplémentaires attendus et vérifiés**, aucun rôle en attente ni grant orphelin.
  Cette mesure porte sur la synchronisation locale, pas sur une installation de production.

Les deux enregistrements sans décorateur RBAC dans l'inventaire sont les WebSockets
OneBot et IDE, protégés par leurs mécanismes propres et contrôlés par la liste exacte des
routes autorisées. Aucun handler HTTP non classé n'est présent.
Les tests HTTP utilisent PostgreSQL éphémère. Les parcours E2E utilisent une installation
isolée et des rôles distincts ; les données et identités sont entièrement synthétiques.
Les frontières externes SMTP, IMAP, fournisseurs IA et exécuteurs ne sont pas qualifiées
sur des services réels par cet audit RBAC. Les rôles personnalisés sont à revoir après
mise à jour, notamment les anciens approbateurs Mail en lecture seule.

Ce contrôle n'est ni un déploiement de production, ni une exécution de `make validate`.
