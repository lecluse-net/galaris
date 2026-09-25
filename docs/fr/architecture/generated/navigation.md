<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/generated/navigation.md">English</a></p>

# Carte des menus Galaris

> Généré depuis les modules actifs, leurs menus et traductions par `make project-context`. Ne pas modifier à la main.

Cette carte décrit le produit livré, pas les menus visibles pour un compte donné. Chaque groupe de privilèges est un OU ; les groupes des ancêtres et de l’entrée doivent tous être satisfaits. Les conditions dynamiques sont évaluées dans l’application, jamais pendant cette génération.

Le [guide de navigation](../../user/navigation.md) détaille les onglets, le menu du compte, les parcours et les entrées absentes. Les sous-entrées de harnais chargées depuis le catalogue serveur ne sont pas figées ici.

## Configurer → Fournisseurs & modèles

- Route : `/llm`
- Usage : Gestion des fournisseurs, modèles et services IA
- Visibilité du menu (privilèges) : (LLM_PROVIDER_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/llm/navigation.ts`

## Configurer → Agents

- Route : `/agent`
- Usage : Gestion des agents
- Visibilité du menu (privilèges) : (AGENT_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/agent/navigation.ts`

## Configurer → Outils & connexions

- Route : `/tools`
- Usage : Gestion des outils
- Visibilité du menu (privilèges) : (TOOL_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/tools/navigation.ts`

## Configurer → Compétences

- Route : `/skill`
- Usage : Bibliothèque de compétences pour les agents
- Visibilité du menu (privilèges) : (SKILL_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/skill/navigation.ts`

## Agir → Discussion

- Route : `/chat`
- Usage : Toutes vos conversations, quelle que soit leur source
- Visibilité du menu (privilèges) : (CHAT_ACCESS)
- Conditions supplémentaires : act.chat: dynamic
- Sources : `front/app/chat/navigation.ts`

## Agir → Objectifs

- Route : `/goal`
- Usage : Piloter les objectifs long terme confiés aux agents
- Visibilité du menu (privilèges) : (GOAL_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/goal/navigation.ts`

## Agir → Processus

- Route : `/process`
- Usage : Processus métier et exécutions externes
- Visibilité du menu (privilèges) : (PROCESS_READ)
- Conditions supplémentaires : —
- Sources : `front/app/process/navigation.ts`

## Connaissances → Documents

- Route : `/memory/documents`
- Usage : Retrouver et classer vos documents accessibles
- Visibilité du menu (privilèges) : (MEMORY_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/memory/navigation.ts`

## Connaissances → Mémoire

- Route : `/memory`
- Usage : Conserver, retrouver et gouverner la mémoire durable des agents
- Visibilité du menu (privilèges) : (MEMORY_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/memory/navigation.ts`

## Connaissances → Contacts

- Route : `/memory/contacts`
- Usage : Réunir les identités multicanales et leurs souvenirs
- Visibilité du menu (privilèges) : (MEMORY_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/memory/navigation.ts`

## Connaissances → Sujets

- Route : `/topic`
- Usage : Parcourir les sujets durables organisés par Dream
- Visibilité du menu (privilèges) : (TOPIC_ACCESS OR TOPIC_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/topic/navigation.ts`

## Superviser → Tableau de bord

- Route : `/dashboard`
- Usage : Vue d’ensemble de l’activité et des performances de Galaris
- Visibilité du menu (privilèges) : (TASK_ACCESS OR TASK_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/index/navigation.ts`

## Superviser → Activité

- Route : `/task`
- Usage : Suivi des conversation, tâches, appels LLM & processus
- Visibilité du menu (privilèges) : (TASK_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/app/task/navigation.ts`

## Superviser → Dream

- Route : `/dream`
- Usage : Suivi des travaux en arrière-plan
- Visibilité du menu (privilèges) : (TASK_ACCESS OR AGENT_MANAGE_ALL)
- Conditions supplémentaires : —
- Sources : `front/app/dream/navigation.ts`

## Superviser → Journal des mails

- Route : `/connection/mail`
- Usage : Validation et journal des courriels envoyés par les agents
- Visibilité du menu (privilèges) : (CONNECTION_ACCESS)
- Conditions supplémentaires : monitor.mailJournal: dynamic
- Sources : `front/app/connection/navigation.ts`

## Superviser → Journal des échecs

- Route : `/incident`
- Usage : Examinez chaque appel LLM ou outil en échec, sa trace complète et les motifs récurrents à corriger.
- Visibilité du menu (privilèges) : (INCIDENT_ACCESS OR INCIDENT_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/incident/navigation.ts`

## Administrer → Préférences

- Route : `/params`
- Usage : Configuration guidée de l’application
- Visibilité du menu (privilèges) : (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`, `front/app/browser/navigation.ts`

## Administrer → Préférences → Système

- Route : `/params/system`
- Usage : Inscriptions, limites d’accès à l’API et diagnostics de l’instance.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Langue

- Route : `/params/language`
- Usage : Définissez la langue de repli du système et le lieu utilisé pour contextualiser les réponses des agents.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Messagerie

- Route : `/params/messaging`
- Usage : Configurez tous les canaux que les agents peuvent écouter et utiliser simultanément.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Mémoire

- Route : `/params/memory`
- Usage : Réglez la mémoire de session, le rappel durable et l’acquisition autonome pour tous les drivers.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Dream

- Route : `/params/dream`
- Usage : Exécute séquentiellement des travaux d’entretien lorsque Galaris est inactif.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Voix

- Route : `/params/voice`
- Usage : Réglages généraux des appels en temps réel, indépendants du fournisseur.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Audio

- Route : `/params/audio`
- Usage : Personnalisez les prompts utilisés pour résumer les transcriptions longues et les sous-titres YouTube.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Processus

- Route : `/params/processes`
- Usage : Connectez Galaris à son moteur de processus. Un seul moteur peut être actif.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Tâches et exécution

- Route : `/params/tasks`
- Usage : Ajustez l’ordonnanceur, la reprise, la planification et les garde-fous des exécutions agentiques.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Harnais

- Route : `/params/harnesses`
- Usage : Configurez le harnais interne, les harnais managés, les services externes et leurs limites d’exécution.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Recherche

- Route : `/params/search`
- Usage : Réglages du moteur SearXNG utilisé par les agents.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Navigateur

- Route : `/browser/settings`
- Usage : Réglez les délais, l’extraction et les captures du Tool Navigateur. Les changements s’appliquent aux prochaines opérations ; les dimensions par défaut concernent les nouvelles fenêtres.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS OR PARAMS_EDIT)
- Conditions supplémentaires : admin.params.browser: dynamic
- Sources : `front/app/browser/navigation.ts`

## Administrer → Préférences → Janus

- Route : `/params/janus`
- Usage : Janus expose une API compatible OpenAI. Il propose les agents disponibles puis transmet directement la conversation à l’agent choisi avec son {'@'}code.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Instructions

- Route : `/params/instructions`
- Usage : Les trois premiers textes Markdown sont ajoutés comme dernier nœud du prompt de leur exécuteur. La politique conversationnelle remplace la règle par défaut commune au texte et à la voix.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Préférences → Journaux

- Route : `/params/logs`
- Usage : Réglez la conservation des traces et le nettoyage des historiques techniques.
- Visibilité du menu (privilèges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/params/navigation.ts`

## Administrer → Laboratoire

- Route : `/lab`
- Usage : Tester et comparer les mécanismes IA
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Analyse de tâches

- Route : `/lab/ai-evaluations`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (EVALUATION_ACCESS OR EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Dispatcher

- Route : `/lab/dispatcher`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Briefing

- Route : `/lab/briefing`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Planner

- Route : `/lab/planner`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Détection des sujets

- Route : `/lab/topic-detection`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Extraction mémoire

- Route : `/lab/memory-extraction`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Apprentissage

- Route : `/lab/learning`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Suivi d’objectif

- Route : `/lab/goal-tracking`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Exécuteur de tâches

- Route : `/lab/task-executor`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Exécuteur conversationnel

- Route : `/lab/conversation-executor`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Laboratoire → Exécuteur vocal

- Route : `/lab/voice-executor`
- Usage : —
- Visibilité du menu (privilèges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT)
- Conditions supplémentaires : —
- Sources : `front/app/lab/navigation.ts`

## Administrer → Console

- Route : `/console/executor`
- Usage : Exécuteur SSH persistant des agents
- Visibilité du menu (privilèges) : (CONSOLE_ACCESS)
- Conditions supplémentaires : admin.executor: dynamic
- Sources : `front/app/console/navigation.ts`

## Administrer → Utilisateurs

- Route : `/user/users`
- Usage : Gestion des utilisateurs
- Visibilité du menu (privilèges) : (READ_USER)
- Conditions supplémentaires : —
- Sources : `front/core/user/navigation.ts`

## Administrer → Équipes

- Route : `/team`
- Usage : Les humains et les agents de vos équipes.
- Visibilité du menu (privilèges) : (TEAM_ACCESS)
- Conditions supplémentaires : —
- Sources : `front/core/team/navigation.ts`

## Administrer → Rôles & autorisations

- Route : `/authorize`
- Usage : Gestion des rôles et privilèges
- Visibilité du menu (privilèges) : (READ_ROLE)
- Conditions supplémentaires : —
- Sources : `front/core/authorize/navigation.ts`

## À propos

- Route : `/about`
- Usage : —
- Visibilité du menu (privilèges) : —
- Conditions supplémentaires : —
- Sources : `front/app/index/navigation.ts`

## Licence

- Route : `/license`
- Usage : —
- Visibilité du menu (privilèges) : —
- Conditions supplémentaires : —
- Sources : `front/app/index/navigation.ts`
