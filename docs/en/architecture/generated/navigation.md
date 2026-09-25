<p align="right"><a href="../../../fr/architecture/generated/navigation.md">Français</a> · <strong>English</strong></p>

# Galaris menu map

> Generated from active modules, menus and translations by `make project-context`. Do not edit manually.

This map describes the shipped product, not the menus visible to a particular account. Privileges within each group use OR; every ancestor and entry group must be satisfied. Dynamic conditions are evaluated in the application, never during generation.

The [navigation guide](../../user/navigation.md) explains tabs, the account menu, workflows and missing entries. Harness subentries loaded from the server catalog are not frozen here.

## Configure → Providers & models

- Route : `/llm`
- Purpose : AI provider, model and service management
- Menu visibility (privileges) : (LLM_PROVIDER_ACCESS)
- Additional conditions : —
- Sources : `front/app/llm/navigation.ts`

## Configure → Agents

- Route : `/agent`
- Purpose : Agent management
- Menu visibility (privileges) : (AGENT_ACCESS)
- Additional conditions : —
- Sources : `front/app/agent/navigation.ts`

## Configure → Tools & connections

- Route : `/tools`
- Purpose : Tool management
- Menu visibility (privileges) : (TOOL_ACCESS)
- Additional conditions : —
- Sources : `front/app/tools/navigation.ts`

## Configure → Skills

- Route : `/skill`
- Purpose : Knowledge library for agents
- Menu visibility (privileges) : (SKILL_ACCESS)
- Additional conditions : —
- Sources : `front/app/skill/navigation.ts`

## Act → Chat

- Route : `/chat`
- Purpose : All your conversations, whatever their source
- Menu visibility (privileges) : (CHAT_ACCESS)
- Additional conditions : act.chat: dynamic
- Sources : `front/app/chat/navigation.ts`

## Act → Goals

- Route : `/goal`
- Purpose : Supervise long-running objectives assigned to agents
- Menu visibility (privileges) : (GOAL_ACCESS)
- Additional conditions : —
- Sources : `front/app/goal/navigation.ts`

## Act → Processes

- Route : `/process`
- Purpose : Business processes and external runs
- Menu visibility (privileges) : (PROCESS_READ)
- Additional conditions : —
- Sources : `front/app/process/navigation.ts`

## Knowledge → Documents

- Route : `/memory/documents`
- Purpose : Find and organize your accessible documents
- Menu visibility (privileges) : (MEMORY_ACCESS)
- Additional conditions : —
- Sources : `front/app/memory/navigation.ts`

## Knowledge → Memory

- Route : `/memory`
- Purpose : Store, retrieve, and govern durable agent memory
- Menu visibility (privileges) : (MEMORY_ACCESS)
- Additional conditions : —
- Sources : `front/app/memory/navigation.ts`

## Knowledge → Contacts

- Route : `/memory/contacts`
- Purpose : Unify multichannel identities and their memories
- Menu visibility (privileges) : (MEMORY_ACCESS)
- Additional conditions : —
- Sources : `front/app/memory/navigation.ts`

## Knowledge → Thematic dossiers

- Route : `/topic`
- Purpose : Browse durable themes organized by Dream
- Menu visibility (privileges) : (TOPIC_ACCESS OR TOPIC_EDIT)
- Additional conditions : —
- Sources : `front/app/topic/navigation.ts`

## Monitor → Dashboard

- Route : `/dashboard`
- Purpose : Overview of Galaris activity and performance
- Menu visibility (privileges) : (TASK_ACCESS OR TASK_EDIT)
- Additional conditions : —
- Sources : `front/app/index/navigation.ts`

## Monitor → Activity

- Route : `/task`
- Purpose : Task, text-conversation, phone-call, LLM activity and process tracking
- Menu visibility (privileges) : (TASK_ACCESS)
- Additional conditions : —
- Sources : `front/app/task/navigation.ts`

## Monitor → Dream

- Route : `/dream`
- Purpose : Track background work
- Menu visibility (privileges) : (TASK_ACCESS OR AGENT_MANAGE_ALL)
- Additional conditions : —
- Sources : `front/app/dream/navigation.ts`

## Monitor → Mail journal

- Route : `/connection/mail`
- Purpose : Approval and journal of emails sent by agents
- Menu visibility (privileges) : (CONNECTION_ACCESS)
- Additional conditions : monitor.mailJournal: dynamic
- Sources : `front/app/connection/navigation.ts`

## Monitor → Failure journal

- Route : `/incident`
- Purpose : Inspect every failed LLM or tool call, its complete trace, and recurring patterns to fix.
- Menu visibility (privileges) : (INCIDENT_ACCESS OR INCIDENT_EDIT)
- Additional conditions : —
- Sources : `front/app/incident/navigation.ts`

## Administer → Preferences

- Route : `/params`
- Purpose : Guided application configuration
- Menu visibility (privileges) : (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`, `front/app/browser/navigation.ts`

## Administer → Preferences → System

- Route : `/params/system`
- Purpose : Registration, instance API access limits and diagnostics.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Language

- Route : `/params/language`
- Purpose : Set the system fallback language and the place used to contextualize agent responses.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Messaging

- Route : `/params/messaging`
- Purpose : Configure every channel that agents can listen to and use simultaneously.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Memory

- Route : `/params/memory`
- Purpose : Configure session memory, durable recall, and autonomous acquisition for every driver.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Dream

- Route : `/params/dream`
- Purpose : Runs maintenance mechanisms sequentially while Galaris is idle.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Voice

- Route : `/params/voice`
- Purpose : General real-time call settings independent from a provider.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Audio

- Route : `/params/audio`
- Purpose : Customize the prompts used to summarize long transcripts and YouTube captions.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Processes

- Route : `/params/processes`
- Purpose : Connect Galaris to its process engine. Only one engine can be active.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Tasks and execution

- Route : `/params/tasks`
- Purpose : Tune scheduling, recovery, planning, and safety limits for agent executions.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Harnesses

- Route : `/params/harnesses`
- Purpose : Configure the internal engine, managed harnesses, external services and their execution limits.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Search

- Route : `/params/search`
- Purpose : Settings for the SearXNG engine used by agents.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Browser

- Route : `/browser/settings`
- Purpose : Configure Browser Tool timeouts, extraction and screenshots. Changes apply to subsequent operations; default dimensions apply to new windows.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS OR PARAMS_EDIT)
- Additional conditions : admin.params.browser: dynamic
- Sources : `front/app/browser/navigation.ts`

## Administer → Preferences → Janus

- Route : `/params/janus`
- Purpose : Janus exposes an OpenAI-compatible API. It lists the available agents, then directly forwards the conversation to the agent selected with its {'@'}code.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Instructions

- Route : `/params/instructions`
- Purpose : The first three Markdown texts are appended as the final node of their executor prompt. The conversation policy replaces the default rule shared by text and voice.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Preferences → Logs

- Route : `/params/logs`
- Purpose : Configure trace retention and technical history cleanup.
- Menu visibility (privileges) : (PARAMS_ACCESS) AND (PARAMS_ACCESS)
- Additional conditions : —
- Sources : `front/core/params/navigation.ts`

## Administer → Laboratory

- Route : `/lab`
- Purpose : Test and compare AI mechanisms
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Task analysis

- Route : `/lab/ai-evaluations`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (EVALUATION_ACCESS OR EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Dispatcher

- Route : `/lab/dispatcher`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Briefing

- Route : `/lab/briefing`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Planner

- Route : `/lab/planner`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Thematic dossier detection

- Route : `/lab/topic-detection`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Memory extraction

- Route : `/lab/memory-extraction`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Learning

- Route : `/lab/learning`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Goal tracking

- Route : `/lab/goal-tracking`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Task executor

- Route : `/lab/task-executor`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Conversation executor

- Route : `/lab/conversation-executor`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Laboratory → Voice executor

- Route : `/lab/voice-executor`
- Purpose : —
- Menu visibility (privileges) : (EVALUATION_ACCESS OR EVALUATION_EDIT OR DISPATCHER_EVALUATION_ACCESS OR DISPATCHER_EVALUATION_EDIT OR BRIEFING_EVALUATION_ACCESS OR BRIEFING_EVALUATION_EDIT OR PLANNER_EVALUATION_ACCESS OR PLANNER_EVALUATION_EDIT OR TOPIC_CLASSIFICATION_EVALUATION_ACCESS OR TOPIC_CLASSIFICATION_EVALUATION_EDIT OR MEMORY_EXTRACTION_EVALUATION_ACCESS OR MEMORY_EXTRACTION_EVALUATION_EDIT OR OUTCOME_REFLECTION_EVALUATION_ACCESS OR OUTCOME_REFLECTION_EVALUATION_EDIT OR GOAL_TRACKING_EVALUATION_ACCESS OR GOAL_TRACKING_EVALUATION_EDIT OR TASK_EXECUTOR_EVALUATION_ACCESS OR TASK_EXECUTOR_EVALUATION_EDIT OR CONVERSATION_EXECUTOR_EVALUATION_ACCESS OR CONVERSATION_EXECUTOR_EVALUATION_EDIT OR VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT) AND (VOICE_EXECUTOR_EVALUATION_ACCESS OR VOICE_EXECUTOR_EVALUATION_EDIT)
- Additional conditions : —
- Sources : `front/app/lab/navigation.ts`

## Administer → Console

- Route : `/console/executor`
- Purpose : Persistent SSH executor for agents
- Menu visibility (privileges) : (CONSOLE_ACCESS)
- Additional conditions : admin.executor: dynamic
- Sources : `front/app/console/navigation.ts`

## Administer → Users

- Route : `/user/users`
- Purpose : User management
- Menu visibility (privileges) : (READ_USER)
- Additional conditions : —
- Sources : `front/core/user/navigation.ts`

## Administer → Teams

- Route : `/team`
- Purpose : The humans and agents in your teams.
- Menu visibility (privileges) : (TEAM_ACCESS)
- Additional conditions : —
- Sources : `front/core/team/navigation.ts`

## Administer → Roles & permissions

- Route : `/authorize`
- Purpose : Role and privilege management
- Menu visibility (privileges) : (READ_ROLE)
- Additional conditions : —
- Sources : `front/core/authorize/navigation.ts`

## About

- Route : `/about`
- Purpose : —
- Menu visibility (privileges) : —
- Additional conditions : —
- Sources : `front/app/index/navigation.ts`

## License

- Route : `/license`
- Purpose : —
- Menu visibility (privileges) : —
- Additional conditions : —
- Sources : `front/app/index/navigation.ts`
