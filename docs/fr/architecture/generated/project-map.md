<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/generated/project-map.md">English</a></p>

# Cartographie générée de Galaris

> Généré par `back/scripts/project_context.py`. Ne pas modifier à la main.

Cette vue est un index statique du code, pas une spécification métier. Les contrats et
tests restent l’autorité sur le comportement.

## Résumé

- 70 modules backend déclarés ;
- 36 modules frontend déclarés ;
- 522 arêtes de dépendance backend ;
- 192 arêtes de dépendance frontend ;
- 263 arêtes entre domaines `app`/`bridge` ;
- 25 paires de domaines directement bidirectionnelles ;
- 1 composantes fortement connexes ;
- 7 paires frontend directement bidirectionnelles ;
- 569 handlers HTTP/WebSocket détectés ;
- 123 tables SQLAlchemy détectées ;
- 131 outils MCP natifs détectés ;
- 39 pages Vue détectées.

## Modules backend

| Module | Couche | Conditionnel | Existe | Capacités |
|---|---|---:|---:|---|
| `core.user` | core | non | oui | `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `core.team` | core | non | oui | `contracts.py`, `models.py`, `privileges.py`, `router.py`, `tests/` |
| `core.authorize` | core | non | oui | `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `core.params` | core | non | oui | `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `core.dbadmin` | core | non | oui | `contracts.py`, `models.py`, `tests/` |
| `app.incident` | app | non | oui | `contracts.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.tools` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.agent` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.harness` | app | non | oui | `contracts.py`, `facade.py`, `router.py`, `schemas.py`, `tests/` |
| `app.harnesses` | app | non | oui | `contracts.py`, `facade.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `app.connection` | app | non | oui | `facade.py`, `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.skill` | app | non | oui | `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.webhook` | app | non | oui | `i18n/`, `router.py`, `schemas.py`, `tests/` |
| `app.llm` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.topic` | app | non | oui | `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.memory` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.contact` | app | non | oui | `contracts.py`, `facade.py`, `router.py`, `schemas.py`, `tests/` |
| `app.dream` | app | non | oui | `contracts.py`, `i18n/`, `interface.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `app.task` | app | non | oui | `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.goal` | app | non | oui | `facade.py`, `i18n/`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.dashboard` | app | non | oui | `router.py`, `schemas.py`, `tests/` |
| `app.lab` | app | non | oui | `contracts.py`, `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.messenger` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `interface.py`, `mcp.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `app.chat` | app | non | oui | `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.conversation` | app | non | oui | `contracts.py`, `facade.py`, `i18n/`, `mcp.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `app.browser` | app | non | oui | `i18n/`, `mcp.py`, `router.py`, `schemas.py`, `tests/` |
| `app.image` | app | non | oui | `i18n/`, `mcp.py`, `router.py`, `schemas.py`, `tests/` |
| `app.audio` | app | non | oui | `i18n/`, `mcp.py`, `tests/` |
| `app.onboarding` | app | non | oui | `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.voice` | app | non | oui | `facade.py`, `i18n/`, `interface.py`, `mcp.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `app.file_share` | app | non | oui | `i18n/`, `interface.py`, `mcp.py`, `router.py`, `tests/` |
| `app.console` | app | non | oui | `contracts.py`, `i18n/`, `mcp.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.process` | app | non | oui | `i18n/`, `interface.py`, `mcp.py`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `app.multimedia` | app | non | oui | `mcp.py`, `models.py`, `router.py`, `tests/` |
| `app.mcp` | app | non | oui | `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py` |
| `bridge.harness` | bridge | non | oui | `i18n/`, `router.py`, `tests/` |
| `bridge.claude_agent` | bridge | non | oui | `tests/` |
| `bridge.codex` | bridge | non | oui | `router.py`, `tests/` |
| `bridge.deepseek_harness` | bridge | non | oui | `tests/` |
| `bridge.n8n` | bridge | non | oui | `router.py`, `schemas.py`, `tests/` |
| `bridge.mail` | bridge | non | oui | `contracts.py`, `mcp.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `bridge.calendar` | bridge | non | oui | `mcp.py`, `models.py`, `router.py`, `schemas.py`, `tests/` |
| `bridge.hermes` | bridge | non | oui | `i18n/`, `models.py`, `privileges.py`, `router.py`, `schemas.py`, `tests/` |
| `bridge.one_bot` | bridge | non | oui | `router.py`, `tests/` |
| `bridge.matrix` | bridge | non | oui | `router.py`, `schemas.py`, `tests/` |
| `bridge.nextcloud` | bridge | non | oui | `router.py`, `tests/` |
| `bridge.telegram` | bridge | non | oui | `router.py`, `schemas.py`, `tests/` |
| `bridge.whatsapp` | bridge | non | oui | `router.py`, `schemas.py`, `tests/` |
| `bridge.openrouter` | bridge | oui | oui | — |
| `bridge.mammouth` | bridge | oui | oui | — |
| `bridge.openai` | bridge | oui | oui | `i18n/`, `tests/` |
| `bridge.anthropic` | bridge | oui | oui | — |
| `bridge.deepseek` | bridge | oui | oui | — |
| `bridge.fireworks` | bridge | oui | oui | — |
| `bridge.groq` | bridge | oui | oui | — |
| `bridge.mistral` | bridge | oui | oui | — |
| `bridge.models_dev` | bridge | oui | oui | — |
| `bridge.together` | bridge | oui | oui | — |
| `bridge.cerebras` | bridge | oui | oui | — |
| `bridge.google` | bridge | oui | oui | — |
| `bridge.xai` | bridge | oui | oui | — |
| `bridge.nvidia` | bridge | oui | oui | — |
| `bridge.huggingface` | bridge | oui | oui | — |
| `bridge.cohere` | bridge | oui | oui | — |
| `bridge.perplexity` | bridge | oui | oui | — |
| `bridge.elevenlabs` | bridge | oui | oui | — |
| `bridge.sunoapi` | bridge | oui | oui | — |
| `bridge.byteplus` | bridge | oui | oui | — |
| `bridge.azure_speech` | bridge | oui | oui | — |
| `bridge.ollama` | bridge | oui | oui | — |

## Modules frontend

| Module | Existe | Capacités | Pages |
|---|---:|---|---:|
| `core/user` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 4 |
| `core/team` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services` | 1 |
| `core/authorize` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 2 |
| `core/params` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 3 |
| `app/index` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 6 |
| `app/agent` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/harnesses` | oui | `components`, `i18n.ts`, `pages`, `services` | 1 |
| `app/tools` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 1 |
| `app/browser` | oui | `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/connection` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/skill` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/llm` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 2 |
| `app/task` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/conversation` | oui | `components`, `i18n.ts`, `services` | 0 |
| `app/chat` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/voice` | oui | `components`, `i18n.ts`, `services` | 0 |
| `app/dream` | oui | `i18n.ts`, `navigation.ts`, `pages`, `services` | 1 |
| `app/topic` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services` | 2 |
| `app/goal` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/memory` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 3 |
| `app/lab` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `presentation.ts`, `services`, `stores` | 3 |
| `app/incident` | oui | `i18n.ts`, `navigation.ts`, `pages`, `services` | 1 |
| `app/process` | oui | `components`, `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `app/console` | oui | `i18n.ts`, `navigation.ts`, `pages`, `services`, `stores` | 1 |
| `bridge/nextcloud` | oui | `i18n.ts` | 0 |
| `bridge/matrix` | oui | `i18n.ts` | 0 |
| `bridge/telegram` | oui | `i18n.ts` | 0 |
| `bridge/whatsapp` | oui | `i18n.ts` | 0 |
| `bridge/one_bot` | oui | `i18n.ts` | 0 |
| `bridge/n8n` | oui | `components`, `i18n.ts`, `services` | 0 |
| `bridge/calendar` | oui | `i18n.ts` | 0 |
| `bridge/claude_agent` | oui | — | 0 |
| `bridge/codex` | oui | — | 0 |
| `bridge/deepseek_harness` | oui | — | 0 |
| `bridge/hermes` | oui | `components`, `i18n.ts`, `services` | 0 |
| `bridge/ollama` | oui | `i18n.ts` | 0 |

## Dépendances backend inter-modules

| Source | Cible | Fichiers |
|---|---|---|
| `app.agent` | `app.llm` | `back/app/agent/agent_service.py`, `back/app/agent/briefing_service.py`, `back/app/agent/dispatcher.py`, `back/app/agent/facade.py`, `back/app/agent/janus.py`, `back/app/agent/model_resolver.py`, `back/app/agent/models.py`, `back/app/agent/openai_router.py`, `back/app/agent/planner_service.py`, `back/app/agent/realtime.py`, `back/app/agent/tools.py` |
| `app.agent` | `app.messenger` | `back/app/agent/planner_service.py` |
| `app.agent` | `app.process` | `back/app/agent/briefing_service.py`, `back/app/agent/janus.py`, `back/app/agent/openai_router.py`, `back/app/agent/realtime.py` |
| `app.agent` | `app.skill` | `back/app/agent/__init__.py`, `back/app/agent/agent_service.py`, `back/app/agent/facade.py`, `back/app/agent/models.py` |
| `app.agent` | `app.tools` | `back/app/agent/agent_service.py`, `back/app/agent/briefing_service.py`, `back/app/agent/executor_service.py`, `back/app/agent/facade.py`, `back/app/agent/mcp.py`, `back/app/agent/planner_service.py` |
| `app.agent` | `core.authorize` | `back/app/agent/agent_service.py`, `back/app/agent/assertions.py`, `back/app/agent/dialogue_service.py`, `back/app/agent/management_scope.py`, `back/app/agent/openai_router.py`, `back/app/agent/openai_service.py`, `back/app/agent/router.py`, `back/app/agent/team_router.py` |
| `app.agent` | `core.database` | `back/app/agent/agent_group_service.py`, `back/app/agent/agent_service.py`, `back/app/agent/dialogue_service.py`, `back/app/agent/janus.py`, `back/app/agent/management_scope.py`, `back/app/agent/models.py`, `back/app/agent/openai_service.py`, `back/app/agent/resource_facade.py`, `back/app/agent/router.py`, `back/app/agent/team_router.py`, `back/app/agent/title_service.py` |
| `app.agent` | `core.dbadmin` | `back/app/agent/dbadmin.py`, `back/app/agent/html_migration.py` |
| `app.agent` | `core.failure_journal` | `back/app/agent/facade.py` |
| `app.agent` | `core.i18n` | `back/app/agent/agent_service.py`, `back/app/agent/briefing_service.py`, `back/app/agent/contracts.py`, `back/app/agent/dispatcher.py`, `back/app/agent/dispatcher_service.py`, `back/app/agent/executor_service.py`, `back/app/agent/janus.py`, `back/app/agent/model_resolver.py`, `back/app/agent/openai_router.py`, `back/app/agent/openai_schemas.py`, `back/app/agent/openai_service.py`, `back/app/agent/planner_service.py`, `back/app/agent/router.py`, `back/app/agent/tools.py` |
| `app.agent` | `core.params` | `back/app/agent/briefing_service.py`, `back/app/agent/dispatcher.py`, `back/app/agent/executor_service.py`, `back/app/agent/facade.py`, `back/app/agent/janus.py`, `back/app/agent/planner_contracts.py`, `back/app/agent/planner_service.py`, `back/app/agent/realtime.py`, `back/app/agent/registry.py` |
| `app.agent` | `core.team` | `back/app/agent/agent_group_service.py`, `back/app/agent/dialogue_service.py`, `back/app/agent/models.py`, `back/app/agent/team_router.py` |
| `app.agent` | `core.user` | `back/app/agent/agent_service.py`, `back/app/agent/dbadmin.py`, `back/app/agent/dialogue_service.py`, `back/app/agent/janus.py`, `back/app/agent/management_scope.py`, `back/app/agent/models.py`, `back/app/agent/openai_service.py`, `back/app/agent/router.py` |
| `app.agent` | `core.util` | `back/app/agent/html_migration.py`, `back/app/agent/models.py`, `back/app/agent/planner_service.py`, `back/app/agent/router.py`, `back/app/agent/schemas.py` |
| `app.audio` | `app.file_share` | `back/app/audio/mcp.py` |
| `app.audio` | `app.llm` | `back/app/audio/mcp.py`, `back/app/audio/summary_service.py` |
| `app.audio` | `app.messenger` | `back/app/audio/mcp.py` |
| `app.audio` | `app.task` | `back/app/audio/summary_service.py` |
| `app.audio` | `app.tools` | `back/app/audio/mcp.py` |
| `app.audio` | `bridge.youtube` | `back/app/audio/mcp.py` |
| `app.audio` | `core.i18n` | `back/app/audio/mcp.py` |
| `app.audio` | `core.params` | `back/app/audio/summary_service.py` |
| `app.browser` | `app.connection` | `back/app/browser/router.py`, `back/app/browser/service.py` |
| `app.browser` | `app.file_share` | `back/app/browser/__init__.py`, `back/app/browser/mcp.py` |
| `app.browser` | `app.tools` | `back/app/browser/mcp.py`, `back/app/browser/service.py` |
| `app.browser` | `core.authorize` | `back/app/browser/router.py` |
| `app.browser` | `core.i18n` | `back/app/browser/mcp.py` |
| `app.browser` | `core.params` | `back/app/browser/mcp.py`, `back/app/browser/service.py` |
| `app.browser` | `core.preview` | `back/app/browser/__init__.py`, `back/app/browser/service.py` |
| `app.browser` | `core.secrets` | `back/app/browser/service.py` |
| `app.browser` | `core.settings` | `back/app/browser/service.py` |
| `app.browser` | `core.user` | `back/app/browser/__init__.py`, `back/app/browser/service.py` |
| `app.chat` | `app.agent` | `back/app/chat/assertions.py`, `back/app/chat/events.py`, `back/app/chat/router.py`, `back/app/chat/schemas.py` |
| `app.chat` | `app.browser` | `back/app/chat/router.py`, `back/app/chat/thumbnail_service.py` |
| `app.chat` | `app.conversation` | `back/app/chat/document_previews.py`, `back/app/chat/events.py`, `back/app/chat/router.py` |
| `app.chat` | `app.messenger` | `back/app/chat/assertions.py`, `back/app/chat/document_previews.py`, `back/app/chat/events.py`, `back/app/chat/provider.py`, `back/app/chat/push_service.py`, `back/app/chat/router.py`, `back/app/chat/schemas.py`, `back/app/chat/storage.py`, `back/app/chat/thumbnail_service.py` |
| `app.chat` | `app.topic` | `back/app/chat/router.py` |
| `app.chat` | `app.voice` | `back/app/chat/events.py`, `back/app/chat/router.py`, `back/app/chat/webrtc.py` |
| `app.chat` | `core.authorize` | `back/app/chat/assertions.py`, `back/app/chat/dbadmin.py`, `back/app/chat/events.py`, `back/app/chat/router.py`, `back/app/chat/webrtc.py` |
| `app.chat` | `core.database` | `back/app/chat/emoji_service.py`, `back/app/chat/events.py`, `back/app/chat/models.py`, `back/app/chat/push_service.py`, `back/app/chat/router.py`, `back/app/chat/storage.py`, `back/app/chat/thumbnail_service.py`, `back/app/chat/webrtc.py` |
| `app.chat` | `core.dbadmin` | `back/app/chat/dbadmin.py` |
| `app.chat` | `core.i18n` | `back/app/chat/router.py` |
| `app.chat` | `core.params` | `back/app/chat/dbadmin.py`, `back/app/chat/html_preview.py`, `back/app/chat/push_service.py`, `back/app/chat/router.py`, `back/app/chat/storage.py`, `back/app/chat/thumbnail_service.py` |
| `app.chat` | `core.settings` | `back/app/chat/html_preview.py`, `back/app/chat/storage.py`, `back/app/chat/webrtc.py` |
| `app.chat` | `core.user` | `back/app/chat/events.py`, `back/app/chat/router.py`, `back/app/chat/webrtc.py` |
| `app.chat` | `core.util` | `back/app/chat/push_service.py`, `back/app/chat/storage.py` |
| `app.connection` | `app.agent` | `back/app/connection/router.py` |
| `app.connection` | `app.tools` | `back/app/connection/connection_service.py`, `back/app/connection/router.py` |
| `app.connection` | `core.authorize` | `back/app/connection/assertions.py`, `back/app/connection/router.py` |
| `app.connection` | `core.database` | `back/app/connection/connection_service.py`, `back/app/connection/models.py`, `back/app/connection/router.py` |
| `app.connection` | `core.i18n` | `back/app/connection/connection_service.py`, `back/app/connection/router.py` |
| `app.connection` | `core.util` | `back/app/connection/connection_service.py` |
| `app.console` | `app.agent` | `back/app/console/__init__.py`, `back/app/console/connection_service.py`, `back/app/console/provisioning.py`, `back/app/console/router.py` |
| `app.console` | `app.connection` | `back/app/console/connection_service.py`, `back/app/console/provisioning.py`, `back/app/console/router.py` |
| `app.console` | `app.file_share` | `back/app/console/file_transport.py` |
| `app.console` | `app.tools` | `back/app/console/connection_service.py`, `back/app/console/file_transport.py`, `back/app/console/mcp.py`, `back/app/console/provisioning.py`, `back/app/console/router.py`, `back/app/console/ssh_client.py` |
| `app.console` | `core.authorize` | `back/app/console/router.py` |
| `app.console` | `core.i18n` | `back/app/console/connection_service.py` |
| `app.console` | `core.util` | `back/app/console/file_transport.py` |
| `app.contact` | `app.agent` | `back/app/contact/router.py` |
| `app.contact` | `app.conversation` | `back/app/contact/service.py` |
| `app.contact` | `app.memory` | `back/app/contact/router.py`, `back/app/contact/service.py` |
| `app.contact` | `app.messenger` | `back/app/contact/service.py` |
| `app.contact` | `app.task` | `back/app/contact/service.py` |
| `app.contact` | `core.authorize` | `back/app/contact/router.py` |
| `app.contact` | `core.database` | `back/app/contact/service.py` |
| `app.conversation` | `app.agent` | `back/app/conversation/artifact_delivery.py`, `back/app/conversation/context.py`, `back/app/conversation/contracts.py`, `back/app/conversation/directives.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/mcp.py`, `back/app/conversation/monitoring_service.py`, `back/app/conversation/router.py`, `back/app/conversation/runtime.py`, `back/app/conversation/scheduler.py`, `back/app/conversation/service.py`, `back/app/conversation/task_objective.py` |
| `app.conversation` | `app.connection` | `back/app/conversation/context.py`, `back/app/conversation/facade.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/monitoring_service.py`, `back/app/conversation/resource_facade.py`, `back/app/conversation/service.py` |
| `app.conversation` | `app.file_share` | `back/app/conversation/artifact_delivery.py`, `back/app/conversation/context.py`, `back/app/conversation/service.py` |
| `app.conversation` | `app.llm` | `back/app/conversation/facade.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/management_service.py`, `back/app/conversation/service.py`, `back/app/conversation/task_objective.py` |
| `app.conversation` | `app.messenger` | `back/app/conversation/context.py`, `back/app/conversation/document_display.py`, `back/app/conversation/facade.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/mcp.py`, `back/app/conversation/monitoring_service.py`, `back/app/conversation/resource_facade.py`, `back/app/conversation/service.py`, `back/app/conversation/task_projection.py`, `back/app/conversation/work_projection.py` |
| `app.conversation` | `app.process` | `back/app/conversation/contracts.py`, `back/app/conversation/facade.py`, `back/app/conversation/mcp.py`, `back/app/conversation/progress.py`, `back/app/conversation/service.py`, `back/app/conversation/work_projection.py` |
| `app.conversation` | `app.task` | `back/app/conversation/contracts.py`, `back/app/conversation/facade.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/mcp.py`, `back/app/conversation/monitoring_service.py`, `back/app/conversation/progress.py`, `back/app/conversation/schemas.py`, `back/app/conversation/service.py`, `back/app/conversation/task_projection.py`, `back/app/conversation/work_projection.py` |
| `app.conversation` | `app.tools` | `back/app/conversation/mcp.py` |
| `app.conversation` | `core.authorize` | `back/app/conversation/router.py` |
| `app.conversation` | `core.database` | `back/app/conversation/activity_facade.py`, `back/app/conversation/context.py`, `back/app/conversation/facade.py`, `back/app/conversation/inspection_service.py`, `back/app/conversation/management_service.py`, `back/app/conversation/mcp.py`, `back/app/conversation/models.py`, `back/app/conversation/monitoring_service.py`, `back/app/conversation/progress.py`, `back/app/conversation/resource_facade.py`, `back/app/conversation/scheduler.py`, `back/app/conversation/service.py`, `back/app/conversation/task_projection.py`, `back/app/conversation/work_projection.py` |
| `app.conversation` | `core.i18n` | `back/app/conversation/router.py`, `back/app/conversation/service.py`, `back/app/conversation/task_objective.py` |
| `app.conversation` | `core.params` | `back/app/conversation/task_objective.py` |
| `app.conversation` | `core.settings` | `back/app/conversation/mcp.py` |
| `app.conversation` | `core.util` | `back/app/conversation/task_objective.py` |
| `app.dashboard` | `app.agent` | `back/app/dashboard/dashboard_service.py`, `back/app/dashboard/router.py` |
| `app.dashboard` | `app.llm` | `back/app/dashboard/dashboard_service.py` |
| `app.dashboard` | `app.task` | `back/app/dashboard/dashboard_service.py` |
| `app.dashboard` | `core.authorize` | `back/app/dashboard/router.py` |
| `app.dashboard` | `core.database` | `back/app/dashboard/dashboard_service.py` |
| `app.dashboard` | `core.util` | `back/app/dashboard/dashboard_service.py` |
| `app.dream` | `app.agent` | `back/app/dream/events.py`, `back/app/dream/router.py` |
| `app.dream` | `app.connection` | `back/app/dream/dbadmin.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/monitoring_service.py` |
| `app.dream` | `app.conversation` | `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/monitoring_service.py` |
| `app.dream` | `app.goal` | `back/app/dream/outcome_evidence.py` |
| `app.dream` | `app.llm` | `back/app/dream/attachment_processing.py`, `back/app/dream/evaluation.py`, `back/app/dream/live_topics.py`, `back/app/dream/mechanisms/attachment_memory.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/memory_decisions.py`, `back/app/dream/mechanisms/memory_extraction.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/skill_learning.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/monitoring_service.py`, `back/app/dream/scheduler.py`, `back/app/dream/schemas.py` |
| `app.dream` | `app.memory` | `back/app/dream/attachment_processing.py`, `back/app/dream/mechanisms/attachment_memory.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/document_structure.py`, `back/app/dream/mechanisms/memory_extraction.py`, `back/app/dream/mechanisms/memory_maintenance.py`, `back/app/dream/mechanisms/process_memory.py`, `back/app/dream/mechanisms/stale_memory.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/outcome_evidence.py`, `back/app/dream/scheduler.py` |
| `app.dream` | `app.messenger` | `back/app/dream/dbadmin.py`, `back/app/dream/live_topics.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/monitoring_service.py` |
| `app.dream` | `app.process` | `back/app/dream/mechanisms/process_memory.py` |
| `app.dream` | `app.skill` | `back/app/dream/mechanisms/skill_learning.py` |
| `app.dream` | `app.task` | `back/app/dream/dbadmin.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/skill_learning.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/monitoring_service.py`, `back/app/dream/outcome_evidence.py`, `back/app/dream/scheduler.py` |
| `app.dream` | `app.topic` | `back/app/dream/dbadmin.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py` |
| `app.dream` | `app.voice` | `back/app/dream/monitoring_service.py`, `back/app/dream/scheduler.py` |
| `app.dream` | `core.authorize` | `back/app/dream/events.py`, `back/app/dream/router.py` |
| `app.dream` | `core.database` | `back/app/dream/attachment_processing.py`, `back/app/dream/events.py`, `back/app/dream/mechanisms/attachment_memory.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/document_structure.py`, `back/app/dream/mechanisms/memory_maintenance.py`, `back/app/dream/mechanisms/process_memory.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/skill_learning.py`, `back/app/dream/mechanisms/stale_memory.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/models.py`, `back/app/dream/monitoring_service.py`, `back/app/dream/service.py` |
| `app.dream` | `core.dbadmin` | `back/app/dream/dbadmin.py` |
| `app.dream` | `core.i18n` | `back/app/dream/attachment_processing.py`, `back/app/dream/language.py`, `back/app/dream/mechanisms/sequential_topic_classification.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py` |
| `app.dream` | `core.params` | `back/app/dream/mechanisms/attachment_memory.py`, `back/app/dream/mechanisms/conversation_memory.py`, `back/app/dream/mechanisms/memory_extraction.py`, `back/app/dream/mechanisms/memory_maintenance.py`, `back/app/dream/mechanisms/skill_learning.py`, `back/app/dream/mechanisms/stale_memory.py`, `back/app/dream/mechanisms/task_memory.py`, `back/app/dream/mechanisms/task_outcome_reflection.py`, `back/app/dream/mechanisms/topic_classification.py`, `back/app/dream/scheduler.py`, `back/app/dream/service.py` |
| `app.dream` | `core.user` | `back/app/dream/events.py` |
| `app.file_share` | `app.agent` | `back/app/file_share/galaris_provider.py`, `back/app/file_share/messenger_transport.py`, `back/app/file_share/resource_contracts.py` |
| `app.file_share` | `app.connection` | `back/app/file_share/file_share_service.py` |
| `app.file_share` | `app.console` | `back/app/file_share/file_share_service.py`, `back/app/file_share/resource_service.py` |
| `app.file_share` | `app.conversation` | `back/app/file_share/galaris_provider.py` |
| `app.file_share` | `app.goal` | `back/app/file_share/galaris_provider.py` |
| `app.file_share` | `app.image` | `back/app/file_share/file_share_service.py` |
| `app.file_share` | `app.memory` | `back/app/file_share/resource_description.py`, `back/app/file_share/resource_service.py` |
| `app.file_share` | `app.messenger` | `back/app/file_share/file_share_service.py` |
| `app.file_share` | `app.process` | `back/app/file_share/galaris_provider.py` |
| `app.file_share` | `app.skill` | `back/app/file_share/galaris_provider.py`, `back/app/file_share/mcp.py` |
| `app.file_share` | `app.task` | `back/app/file_share/galaris_provider.py`, `back/app/file_share/messenger_transport.py` |
| `app.file_share` | `app.tools` | `back/app/file_share/file_share_service.py`, `back/app/file_share/mcp.py`, `back/app/file_share/transport.py` |
| `app.file_share` | `bridge.affine` | `back/app/file_share/bridges.py` |
| `app.file_share` | `bridge.grav` | `back/app/file_share/bridges.py` |
| `app.file_share` | `core.authorize` | `back/app/file_share/router.py` |
| `app.file_share` | `core.i18n` | `back/app/file_share/bridges.py`, `back/app/file_share/file_share_service.py`, `back/app/file_share/messenger_transport.py` |
| `app.file_share` | `core.params` | `back/app/file_share/resource_delivery.py` |
| `app.file_share` | `core.preview` | `back/app/file_share/web_preview.py` |
| `app.file_share` | `core.util` | `back/app/file_share/messenger_transport.py`, `back/app/file_share/resource_service.py`, `back/app/file_share/transport.py`, `back/app/file_share/web_transport.py` |
| `app.goal` | `app.agent` | `back/app/goal/events.py`, `back/app/goal/goal_service.py`, `back/app/goal/models.py`, `back/app/goal/router.py`, `back/app/goal/runner.py` |
| `app.goal` | `app.connection` | `back/app/goal/mcp.py`, `back/app/goal/models.py`, `back/app/goal/resource_facade.py` |
| `app.goal` | `app.llm` | `back/app/goal/goal_service.py`, `back/app/goal/models.py`, `back/app/goal/runner.py` |
| `app.goal` | `app.messenger` | `back/app/goal/goal_service.py`, `back/app/goal/referrer_wait.py` |
| `app.goal` | `app.task` | `back/app/goal/__init__.py`, `back/app/goal/goal_service.py`, `back/app/goal/models.py`, `back/app/goal/referrer_wait.py`, `back/app/goal/resource_facade.py`, `back/app/goal/runner.py` |
| `app.goal` | `app.tools` | `back/app/goal/mcp.py` |
| `app.goal` | `core.authorize` | `back/app/goal/router.py` |
| `app.goal` | `core.database` | `back/app/goal/events.py`, `back/app/goal/facade.py`, `back/app/goal/goal_service.py`, `back/app/goal/models.py`, `back/app/goal/referrer_wait.py`, `back/app/goal/resource_facade.py`, `back/app/goal/runner.py` |
| `app.goal` | `core.i18n` | `back/app/goal/referrer_wait.py` |
| `app.goal` | `core.params` | `back/app/goal/settings_service.py` |
| `app.goal` | `core.user` | `back/app/goal/events.py`, `back/app/goal/goal_service.py` |
| `app.goal` | `core.util` | `back/app/goal/router.py`, `back/app/goal/schemas.py` |
| `app.harness` | `app.agent` | `back/app/harness/__init__.py`, `back/app/harness/checkpoint.py`, `back/app/harness/checkpoint_policy.py`, `back/app/harness/contracts.py`, `back/app/harness/conversation.py`, `back/app/harness/driver.py`, `back/app/harness/executor.py`, `back/app/harness/facade.py`, `back/app/harness/mcp_toolset.py`, `back/app/harness/media.py`, `back/app/harness/prompt.py`, `back/app/harness/router.py`, `back/app/harness/runtime.py` |
| `app.harness` | `app.console` | `back/app/harness/executor.py` |
| `app.harness` | `app.conversation` | `back/app/harness/conversation.py` |
| `app.harness` | `app.file_share` | `back/app/harness/conversation.py`, `back/app/harness/media.py`, `back/app/harness/runtime.py` |
| `app.harness` | `app.llm` | `back/app/harness/conversation.py`, `back/app/harness/executor.py`, `back/app/harness/media.py`, `back/app/harness/runtime.py` |
| `app.harness` | `app.messenger` | `back/app/harness/conversation.py`, `back/app/harness/executor.py` |
| `app.harness` | `app.process` | `back/app/harness/conversation.py`, `back/app/harness/executor.py` |
| `app.harness` | `app.skill` | `back/app/harness/__init__.py`, `back/app/harness/skills.py` |
| `app.harness` | `app.tools` | `back/app/harness/checkpoint.py`, `back/app/harness/conversation.py`, `back/app/harness/executor.py`, `back/app/harness/mcp_toolset.py`, `back/app/harness/runtime.py` |
| `app.harness` | `core.authorize` | `back/app/harness/router.py` |
| `app.harness` | `core.database` | `back/app/harness/conversation.py`, `back/app/harness/executor.py`, `back/app/harness/runtime.py` |
| `app.harness` | `core.failure_journal` | `back/app/harness/runtime.py` |
| `app.harness` | `core.i18n` | `back/app/harness/conversation.py`, `back/app/harness/executor.py`, `back/app/harness/runtime.py` |
| `app.harness` | `core.params` | `back/app/harness/conversation.py`, `back/app/harness/executor.py`, `back/app/harness/media.py`, `back/app/harness/runtime.py` |
| `app.harnesses` | `app.agent` | `back/app/harnesses/agent_adapter.py`, `back/app/harnesses/agent_driver.py`, `back/app/harnesses/configuration.py`, `back/app/harnesses/contracts.py`, `back/app/harnesses/dbadmin.py`, `back/app/harnesses/driver.py`, `back/app/harnesses/facade.py`, `back/app/harnesses/models.py`, `back/app/harnesses/openai_client.py`, `back/app/harnesses/openai_provider.py`, `back/app/harnesses/router.py`, `back/app/harnesses/service.py`, `back/app/harnesses/skill_sync.py` |
| `app.harnesses` | `core.authorize` | `back/app/harnesses/router.py` |
| `app.harnesses` | `core.database` | `back/app/harnesses/configuration.py`, `back/app/harnesses/models.py`, `back/app/harnesses/service.py`, `back/app/harnesses/skill_sync.py` |
| `app.harnesses` | `core.dbadmin` | `back/app/harnesses/dbadmin.py` |
| `app.harnesses` | `core.params` | `back/app/harnesses/service.py` |
| `app.harnesses` | `core.util` | `back/app/harnesses/service.py` |
| `app.image` | `app.file_share` | `back/app/image/mcp.py` |
| `app.image` | `app.llm` | `back/app/image/image_service.py`, `back/app/image/mcp.py` |
| `app.image` | `app.tools` | `back/app/image/mcp.py` |
| `app.image` | `core.i18n` | `back/app/image/image_service.py`, `back/app/image/mcp.py`, `back/app/image/transport.py` |
| `app.image` | `core.util` | `back/app/image/image_service.py` |
| `app.incident` | `core.authorize` | `back/app/incident/router.py` |
| `app.incident` | `core.database` | `back/app/incident/models.py`, `back/app/incident/retention.py`, `back/app/incident/service.py` |
| `app.incident` | `core.failure_journal` | `back/app/incident/__init__.py`, `back/app/incident/contracts.py` |
| `app.incident` | `core.params` | `back/app/incident/retention.py` |
| `app.lab` | `app.agent` | `back/app/lab/contracts.py`, `back/app/lab/dispatcher_evaluation_service.py`, `back/app/lab/evidence_service.py`, `back/app/lab/executor_prompt_service.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/mechanism_registry.py`, `back/app/lab/objective_checks.py`, `back/app/lab/router.py`, `back/app/lab/schemas.py` |
| `app.lab` | `app.connection` | `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.conversation` | `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.dream` | `back/app/lab/contracts.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/mechanism_registry.py`, `back/app/lab/run_inference.py`, `back/app/lab/schemas.py`, `back/app/lab/synthetic_service.py` |
| `app.lab` | `app.goal` | `back/app/lab/mechanism_registry.py` |
| `app.lab` | `app.llm` | `back/app/lab/analysis_service.py`, `back/app/lab/dispatcher_evaluation_service.py`, `back/app/lab/evaluation_service.py`, `back/app/lab/evidence_service.py`, `back/app/lab/inference_profile.py`, `back/app/lab/judgment_service.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/mechanism_registry.py`, `back/app/lab/run_inference.py`, `back/app/lab/synthetic_service.py` |
| `app.lab` | `app.memory` | `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.messenger` | `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.process` | `back/app/lab/evidence_service.py`, `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.skill` | `back/app/lab/evidence_service.py` |
| `app.lab` | `app.task` | `back/app/lab/__init__.py`, `back/app/lab/dispatcher_evaluation_service.py`, `back/app/lab/evaluation_service.py`, `back/app/lab/evidence_service.py`, `back/app/lab/judgment_service.py`, `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `app.tools` | `back/app/lab/evidence_service.py` |
| `app.lab` | `app.topic` | `back/app/lab/contracts.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/mechanism_registry.py`, `back/app/lab/schemas.py`, `back/app/lab/synthetic_service.py` |
| `app.lab` | `app.voice` | `back/app/lab/mechanism_evaluation_service.py` |
| `app.lab` | `core.authorize` | `back/app/lab/access.py`, `back/app/lab/assertions.py`, `back/app/lab/router.py` |
| `app.lab` | `core.database` | `back/app/lab/capture_service.py`, `back/app/lab/diagnosis_service.py`, `back/app/lab/dispatcher_evaluation_service.py`, `back/app/lab/evaluation_service.py`, `back/app/lab/evidence_service.py`, `back/app/lab/human_review_service.py`, `back/app/lab/judgment_service.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/models.py`, `back/app/lab/run_claims.py`, `back/app/lab/run_lease.py`, `back/app/lab/run_publication.py`, `back/app/lab/synthetic_service.py` |
| `app.lab` | `core.i18n` | `back/app/lab/analysis_service.py`, `back/app/lab/diagnosis_service.py`, `back/app/lab/dispatcher_evaluation_service.py`, `back/app/lab/evaluation_service.py`, `back/app/lab/human_review_service.py`, `back/app/lab/judgment_service.py`, `back/app/lab/mechanism_evaluation_service.py`, `back/app/lab/router.py`, `back/app/lab/synthetic_service.py` |
| `app.lab` | `core.params` | `back/app/lab/evidence_service.py`, `back/app/lab/executor_prompt_service.py` |
| `app.lab` | `core.user` | `back/app/lab/human_review_service.py` |
| `app.llm` | `app.agent` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py`, `back/app/llm/contracts.py`, `back/app/llm/decision_service.py`, `back/app/llm/events.py`, `back/app/llm/facade.py`, `back/app/llm/inference_execution.py`, `back/app/llm/inference_facade.py`, `back/app/llm/inference_journal.py`, `back/app/llm/inference_store.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/llm_service.py`, `back/app/llm/mcp.py`, `back/app/llm/protocol_inference.py`, `back/app/llm/runtime_correlation.py`, `back/app/llm/text_inference.py`, `back/app/llm/tts_service.py` |
| `app.llm` | `app.connection` | `back/app/llm/events.py`, `back/app/llm/llm_call_service.py` |
| `app.llm` | `app.conversation` | `back/app/llm/events.py`, `back/app/llm/facade.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `app.mcp` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py` |
| `app.llm` | `app.messenger` | `back/app/llm/events.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `app.process` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py`, `back/app/llm/events.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/mcp.py`, `back/app/llm/runtime_correlation.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `app.task` | `back/app/llm/__init__.py`, `back/app/llm/events.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/mcp.py`, `back/app/llm/proxy_service.py`, `back/app/llm/retention.py`, `back/app/llm/runtime_correlation.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `app.tools` | `back/app/llm/mcp.py` |
| `app.llm` | `core.authorize` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py`, `back/app/llm/personal_router.py`, `back/app/llm/profile_router.py`, `back/app/llm/provider_router.py` |
| `app.llm` | `core.database` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py`, `back/app/llm/events.py`, `back/app/llm/facade.py`, `back/app/llm/inference_execution.py`, `back/app/llm/inference_journal.py`, `back/app/llm/inference_store.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/llm_provider_service.py`, `back/app/llm/llm_service.py`, `back/app/llm/mcp.py`, `back/app/llm/models.py`, `back/app/llm/personal_service.py`, `back/app/llm/profile_models.py`, `back/app/llm/profile_service.py`, `back/app/llm/protocol_inference.py`, `back/app/llm/provider_models.py`, `back/app/llm/proxy_service.py`, `back/app/llm/retention.py`, `back/app/llm/structured_service.py`, `back/app/llm/subscription_policy.py`, `back/app/llm/text_inference.py` |
| `app.llm` | `core.dbadmin` | `back/app/llm/dbadmin.py` |
| `app.llm` | `core.failure_journal` | `back/app/llm/llm_call_service.py` |
| `app.llm` | `core.i18n` | `back/app/llm/anthropic_router.py`, `back/app/llm/anthropic_service.py`, `back/app/llm/call_router.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/llm_provider_service.py`, `back/app/llm/llm_service.py`, `back/app/llm/personal_router.py`, `back/app/llm/profile_router.py`, `back/app/llm/profile_service.py`, `back/app/llm/protocol_inference.py`, `back/app/llm/provider_router.py`, `back/app/llm/proxy_service.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `core.params` | `back/app/llm/dbadmin.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/profile_service.py`, `back/app/llm/retention.py` |
| `app.llm` | `core.user` | `back/app/llm/anthropic_router.py`, `back/app/llm/call_router.py`, `back/app/llm/events.py`, `back/app/llm/inference_execution.py`, `back/app/llm/llm_provider_service.py`, `back/app/llm/personal_router.py`, `back/app/llm/subscription_policy.py` |
| `app.llm` | `core.util` | `back/app/llm/embedding_service.py`, `back/app/llm/handlers/openai_compatible.py`, `back/app/llm/image_trace.py`, `back/app/llm/llm_call_service.py`, `back/app/llm/llm_provider_service.py`, `back/app/llm/media_transport.py`, `back/app/llm/message_cleanup.py`, `back/app/llm/personal_service.py`, `back/app/llm/proxy_service.py`, `back/app/llm/responses_trace.py`, `back/app/llm/trace.py`, `back/app/llm/transcription_service.py`, `back/app/llm/tts_service.py` |
| `app.mcp` | `app.agent` | `back/app/mcp/router.py` |
| `app.mcp` | `app.tools` | `back/app/mcp/router.py` |
| `app.mcp` | `core.authorize` | `back/app/mcp/router.py` |
| `app.mcp` | `core.database` | `back/app/mcp/models.py`, `back/app/mcp/router.py`, `back/app/mcp/service.py` |
| `app.mcp` | `core.i18n` | `back/app/mcp/router.py` |
| `app.mcp` | `core.util` | `back/app/mcp/models.py`, `back/app/mcp/service.py` |
| `app.memory` | `app.agent` | `back/app/memory/access.py`, `back/app/memory/assertions.py`, `back/app/memory/automation.py`, `back/app/memory/bootstrap.py`, `back/app/memory/conversation_summary.py`, `back/app/memory/document_app_service.py`, `back/app/memory/document_icons.py`, `back/app/memory/document_order.py`, `back/app/memory/document_service.py`, `back/app/memory/document_sharing.py`, `back/app/memory/document_tags.py`, `back/app/memory/events.py`, `back/app/memory/goal_document_adapter.py`, `back/app/memory/goal_folders.py`, `back/app/memory/item_sharing.py`, `back/app/memory/library_queries.py`, `back/app/memory/router.py`, `back/app/memory/service.py`, `back/app/memory/source_projection.py` |
| `app.memory` | `app.conversation` | `back/app/memory/bootstrap.py`, `back/app/memory/conversation_document_adapter.py`, `back/app/memory/link_reconciliation.py`, `back/app/memory/mcp.py`, `back/app/memory/service.py` |
| `app.memory` | `app.goal` | `back/app/memory/bootstrap.py`, `back/app/memory/dbadmin.py`, `back/app/memory/goal_document_adapter.py`, `back/app/memory/goal_folders.py`, `back/app/memory/link_reconciliation.py`, `back/app/memory/source_projection.py` |
| `app.memory` | `app.llm` | `back/app/memory/__init__.py`, `back/app/memory/acquisition_service.py`, `back/app/memory/conversation_summary.py`, `back/app/memory/embedding.py` |
| `app.memory` | `app.process` | `back/app/memory/link_reconciliation.py`, `back/app/memory/process_projection.py` |
| `app.memory` | `app.task` | `back/app/memory/automation.py`, `back/app/memory/goal_folders.py`, `back/app/memory/link_reconciliation.py`, `back/app/memory/mcp.py`, `back/app/memory/service.py` |
| `app.memory` | `app.tools` | `back/app/memory/item_sharing.py`, `back/app/memory/mcp.py` |
| `app.memory` | `app.topic` | `back/app/memory/link_reconciliation.py` |
| `app.memory` | `app.voice` | `back/app/memory/automation.py` |
| `app.memory` | `core.authorize` | `back/app/memory/assertions.py`, `back/app/memory/goal_folders.py`, `back/app/memory/item_sharing.py`, `back/app/memory/router.py` |
| `app.memory` | `core.database` | `back/app/memory/access.py`, `back/app/memory/acquisition_service.py`, `back/app/memory/admission.py`, `back/app/memory/attachment_analysis.py`, `back/app/memory/attachment_description.py`, `back/app/memory/automation.py`, `back/app/memory/contact_directory.py`, `back/app/memory/conversation_document_adapter.py`, `back/app/memory/deduplication.py`, `back/app/memory/document_app_security.py`, `back/app/memory/document_app_service.py`, `back/app/memory/document_attachment_service.py`, `back/app/memory/document_icons.py`, `back/app/memory/document_order.py`, `back/app/memory/document_service.py`, `back/app/memory/document_structure.py`, `back/app/memory/document_tags.py`, `back/app/memory/events.py`, `back/app/memory/facade.py`, `back/app/memory/goal_document_adapter.py`, `back/app/memory/goal_folders.py`, `back/app/memory/html_migration.py`, `back/app/memory/item_sharing.py`, `back/app/memory/library_queries.py`, `back/app/memory/link_reconciliation.py`, `back/app/memory/maintenance.py`, `back/app/memory/mcp.py`, `back/app/memory/messenger_contact.py`, `back/app/memory/models.py`, `back/app/memory/process_projection.py`, `back/app/memory/retrieval.py`, `back/app/memory/revision_queries.py`, `back/app/memory/router.py`, `back/app/memory/semantic_index.py`, `back/app/memory/service.py`, `back/app/memory/source_projection.py`, `back/app/memory/storage_reconciliation.py`, `back/app/memory/topic_maintenance.py`, `back/app/memory/topic_ranking.py`, `back/app/memory/usage.py`, `back/app/memory/vector.py` |
| `app.memory` | `core.dbadmin` | `back/app/memory/dbadmin.py`, `back/app/memory/html_migration.py` |
| `app.memory` | `core.i18n` | `back/app/memory/automation.py`, `back/app/memory/goal_document_adapter.py`, `back/app/memory/goal_folders.py`, `back/app/memory/mcp.py` |
| `app.memory` | `core.params` | `back/app/memory/acquisition_service.py`, `back/app/memory/automation.py`, `back/app/memory/bootstrap.py`, `back/app/memory/context.py`, `back/app/memory/deduplication.py`, `back/app/memory/document_attachment_service.py`, `back/app/memory/document_thumbnail_service.py`, `back/app/memory/maintenance.py`, `back/app/memory/retrieval.py`, `back/app/memory/router.py`, `back/app/memory/storage.py` |
| `app.memory` | `core.preview` | `back/app/memory/document_export.py`, `back/app/memory/document_links.py`, `back/app/memory/document_thumbnail_cache.py`, `back/app/memory/document_thumbnail_service.py`, `back/app/memory/router.py` |
| `app.memory` | `core.settings` | `back/app/memory/document_thumbnail_cache.py` |
| `app.memory` | `core.team` | `back/app/memory/access.py`, `back/app/memory/bootstrap.py`, `back/app/memory/item_sharing.py` |
| `app.memory` | `core.user` | `back/app/memory/access.py`, `back/app/memory/bootstrap.py`, `back/app/memory/document_attachment_service.py`, `back/app/memory/document_export.py`, `back/app/memory/document_links.py`, `back/app/memory/document_sharing.py`, `back/app/memory/document_thumbnail_service.py`, `back/app/memory/events.py`, `back/app/memory/goal_document_adapter.py`, `back/app/memory/goal_folders.py`, `back/app/memory/item_sharing.py`, `back/app/memory/library_queries.py`, `back/app/memory/maintenance.py`, `back/app/memory/router.py`, `back/app/memory/service.py` |
| `app.memory` | `core.util` | `back/app/memory/acquisition_service.py`, `back/app/memory/attachment_analysis.py`, `back/app/memory/attachment_description.py`, `back/app/memory/document_links.py`, `back/app/memory/document_service.py`, `back/app/memory/file_facade.py`, `back/app/memory/html_migration.py`, `back/app/memory/models.py`, `back/app/memory/passages.py`, `back/app/memory/router.py`, `back/app/memory/service.py`, `back/app/memory/source_projection.py`, `back/app/memory/storage.py`, `back/app/memory/storage_reconciliation.py` |
| `app.messenger` | `app.agent` | `back/app/messenger/contact_access.py`, `back/app/messenger/native_facade.py`, `back/app/messenger/router.py`, `back/app/messenger/schemas.py`, `back/app/messenger/service.py`, `back/app/messenger/session.py` |
| `app.messenger` | `app.connection` | `back/app/messenger/configuration.py`, `back/app/messenger/contact_access.py`, `back/app/messenger/contact_memory.py`, `back/app/messenger/directory.py`, `back/app/messenger/ingest.py`, `back/app/messenger/native_facade.py`, `back/app/messenger/native_interactions.py`, `back/app/messenger/service.py`, `back/app/messenger/session.py` |
| `app.messenger` | `app.conversation` | `back/app/messenger/contact_memory.py`, `back/app/messenger/service.py` |
| `app.messenger` | `app.file_share` | `back/app/messenger/link_preview.py`, `back/app/messenger/mcp.py` |
| `app.messenger` | `app.llm` | `back/app/messenger/ingest.py`, `back/app/messenger/mcp.py` |
| `app.messenger` | `app.memory` | `back/app/messenger/contact_memory.py`, `back/app/messenger/service.py` |
| `app.messenger` | `app.task` | `back/app/messenger/contact_memory.py`, `back/app/messenger/mcp.py`, `back/app/messenger/service.py` |
| `app.messenger` | `app.tools` | `back/app/messenger/configuration.py`, `back/app/messenger/contact_memory.py`, `back/app/messenger/directory.py`, `back/app/messenger/journal.py`, `back/app/messenger/mcp.py`, `back/app/messenger/native_facade.py`, `back/app/messenger/service.py`, `back/app/messenger/session.py`, `back/app/messenger/user_service.py` |
| `app.messenger` | `core.authorize` | `back/app/messenger/router.py` |
| `app.messenger` | `core.database` | `back/app/messenger/contact_access.py`, `back/app/messenger/contact_memory.py`, `back/app/messenger/facade.py`, `back/app/messenger/ingest.py`, `back/app/messenger/interactions.py`, `back/app/messenger/journal.py`, `back/app/messenger/mcp.py`, `back/app/messenger/models.py`, `back/app/messenger/native_facade.py`, `back/app/messenger/native_interactions.py`, `back/app/messenger/room_service.py`, `back/app/messenger/service.py`, `back/app/messenger/session.py`, `back/app/messenger/user_service.py`, `back/app/messenger/voice_journal.py` |
| `app.messenger` | `core.dbadmin` | `back/app/messenger/dbadmin.py` |
| `app.messenger` | `core.i18n` | `back/app/messenger/ingest.py`, `back/app/messenger/interactions.py`, `back/app/messenger/mcp.py`, `back/app/messenger/native_facade.py`, `back/app/messenger/native_interactions.py`, `back/app/messenger/service.py` |
| `app.messenger` | `core.params` | `back/app/messenger/configuration.py`, `back/app/messenger/facade.py`, `back/app/messenger/ingest.py`, `back/app/messenger/link_preview.py`, `back/app/messenger/mcp.py`, `back/app/messenger/service.py`, `back/app/messenger/session.py` |
| `app.messenger` | `core.user` | `back/app/messenger/native_facade.py` |
| `app.messenger` | `core.util` | `back/app/messenger/link_preview.py` |
| `app.multimedia` | `app.agent` | `back/app/multimedia/engine.py`, `back/app/multimedia/router.py` |
| `app.multimedia` | `app.file_share` | `back/app/multimedia/delivery.py`, `back/app/multimedia/engine.py`, `back/app/multimedia/provider_results.py`, `back/app/multimedia/service.py` |
| `app.multimedia` | `app.llm` | `back/app/multimedia/engine.py`, `back/app/multimedia/mcp.py`, `back/app/multimedia/provider_results.py`, `back/app/multimedia/service.py` |
| `app.multimedia` | `app.process` | `back/app/multimedia/__init__.py`, `back/app/multimedia/delivery.py`, `back/app/multimedia/engine.py`, `back/app/multimedia/mcp.py`, `back/app/multimedia/provider_results.py`, `back/app/multimedia/router.py` |
| `app.multimedia` | `app.tools` | `back/app/multimedia/mcp.py`, `back/app/multimedia/service.py` |
| `app.multimedia` | `core.authorize` | `back/app/multimedia/router.py` |
| `app.multimedia` | `core.database` | `back/app/multimedia/delivery.py`, `back/app/multimedia/engine.py`, `back/app/multimedia/models.py`, `back/app/multimedia/provider_results.py`, `back/app/multimedia/router.py` |
| `app.multimedia` | `core.params` | `back/app/multimedia/engine.py` |
| `app.multimedia` | `core.util` | `back/app/multimedia/engine.py`, `back/app/multimedia/provider_results.py`, `back/app/multimedia/service.py` |
| `app.onboarding` | `app.agent` | `back/app/onboarding/router.py`, `back/app/onboarding/services.py` |
| `app.onboarding` | `app.connection` | `back/app/onboarding/services.py` |
| `app.onboarding` | `app.llm` | `back/app/onboarding/services.py` |
| `app.onboarding` | `app.messenger` | `back/app/onboarding/services.py` |
| `app.onboarding` | `app.process` | `back/app/onboarding/services.py` |
| `app.onboarding` | `app.skill` | `back/app/onboarding/services.py` |
| `app.onboarding` | `app.tools` | `back/app/onboarding/services.py` |
| `app.onboarding` | `core.authorize` | `back/app/onboarding/router.py` |
| `app.onboarding` | `core.database` | `back/app/onboarding/router.py`, `back/app/onboarding/services.py` |
| `app.onboarding` | `core.user` | `back/app/onboarding/router.py` |
| `app.process` | `app.agent` | `back/app/process/events.py`, `back/app/process/process_service.py`, `back/app/process/router.py` |
| `app.process` | `app.console` | `back/app/process/process_service.py`, `back/app/process/router.py` |
| `app.process` | `app.file_share` | `back/app/process/process_service.py`, `back/app/process/router.py` |
| `app.process` | `app.llm` | `back/app/process/__init__.py`, `back/app/process/agent_capabilities.py`, `back/app/process/process_service.py` |
| `app.process` | `app.task` | `back/app/process/__init__.py`, `back/app/process/process_service.py`, `back/app/process/retention.py` |
| `app.process` | `app.tools` | `back/app/process/mcp.py`, `back/app/process/process_service.py` |
| `app.process` | `core.authorize` | `back/app/process/router.py` |
| `app.process` | `core.database` | `back/app/process/events.py`, `back/app/process/export.py`, `back/app/process/interface.py`, `back/app/process/models.py`, `back/app/process/process_service.py`, `back/app/process/progress.py`, `back/app/process/retention.py`, `back/app/process/workers.py` |
| `app.process` | `core.i18n` | `back/app/process/fake_engine.py`, `back/app/process/mcp.py`, `back/app/process/process_service.py`, `back/app/process/registry.py`, `back/app/process/router.py` |
| `app.process` | `core.params` | `back/app/process/__init__.py`, `back/app/process/process_service.py`, `back/app/process/retention.py`, `back/app/process/router.py`, `back/app/process/workers.py` |
| `app.process` | `core.user` | `back/app/process/events.py` |
| `app.process` | `core.util` | `back/app/process/process_service.py` |
| `app.skill` | `app.agent` | `back/app/skill/dbadmin.py`, `back/app/skill/learning_service.py`, `back/app/skill/models.py`, `back/app/skill/router.py`, `back/app/skill/skill_service.py` |
| `app.skill` | `app.connection` | `back/app/skill/resource_facade.py` |
| `app.skill` | `app.tools` | `back/app/skill/mcp.py` |
| `app.skill` | `core.authorize` | `back/app/skill/router.py` |
| `app.skill` | `core.database` | `back/app/skill/learning_service.py`, `back/app/skill/models.py`, `back/app/skill/resource_facade.py`, `back/app/skill/skill_service.py` |
| `app.skill` | `core.dbadmin` | `back/app/skill/dbadmin.py`, `back/app/skill/skill_service.py` |
| `app.skill` | `core.params` | `back/app/skill/learning_service.py` |
| `app.task` | `app.agent` | `back/app/task/__init__.py`, `back/app/task/activity_snapshot.py`, `back/app/task/agent_adapter.py`, `back/app/task/budget.py`, `back/app/task/live_checkpoint.py`, `back/app/task/mcp.py`, `back/app/task/models.py`, `back/app/task/operational_state.py`, `back/app/task/replacement.py`, `back/app/task/router.py`, `back/app/task/run_events.py`, `back/app/task/runner.py`, `back/app/task/scheduler.py`, `back/app/task/schemas.py`, `back/app/task/task_service.py`, `back/app/task/working_set.py` |
| `app.task` | `app.goal` | `back/app/task/models.py`, `back/app/task/router.py`, `back/app/task/task_service.py` |
| `app.task` | `app.llm` | `back/app/task/budget.py`, `back/app/task/mcp.py`, `back/app/task/startup_timing.py`, `back/app/task/task_service.py` |
| `app.task` | `app.messenger` | `back/app/task/collab.py`, `back/app/task/scheduler.py`, `back/app/task/task_service.py` |
| `app.task` | `app.tools` | `back/app/task/access.py`, `back/app/task/mcp.py` |
| `app.task` | `core.authorize` | `back/app/task/router.py`, `back/app/task/run_events.py` |
| `app.task` | `core.database` | `back/app/task/active_lease.py`, `back/app/task/activity.py`, `back/app/task/activity_snapshot.py`, `back/app/task/agent_adapter.py`, `back/app/task/amendment_service.py`, `back/app/task/collab.py`, `back/app/task/conversation.py`, `back/app/task/live_checkpoint.py`, `back/app/task/mcp.py`, `back/app/task/models.py`, `back/app/task/outcome.py`, `back/app/task/progress.py`, `back/app/task/replacement.py`, `back/app/task/resource_facade.py`, `back/app/task/router.py`, `back/app/task/run_events.py`, `back/app/task/scheduler.py`, `back/app/task/startup_timing.py`, `back/app/task/task_service.py`, `back/app/task/working_set.py` |
| `app.task` | `core.dbadmin` | `back/app/task/dbadmin.py`, `back/app/task/html_migration.py` |
| `app.task` | `core.i18n` | `back/app/task/budget.py`, `back/app/task/collab.py`, `back/app/task/mcp.py`, `back/app/task/router.py`, `back/app/task/scheduler.py`, `back/app/task/task_service.py` |
| `app.task` | `core.params` | `back/app/task/budget.py`, `back/app/task/collab.py`, `back/app/task/mcp.py`, `back/app/task/scheduler.py`, `back/app/task/settings_service.py` |
| `app.task` | `core.user` | `back/app/task/mcp.py`, `back/app/task/run_events.py`, `back/app/task/task_service.py` |
| `app.task` | `core.util` | `back/app/task/activity_snapshot.py`, `back/app/task/html_migration.py`, `back/app/task/mcp.py`, `back/app/task/models.py`, `back/app/task/operational_state.py`, `back/app/task/router.py`, `back/app/task/schemas.py` |
| `app.tools` | `app.agent` | `back/app/tools/agent_registry.py`, `back/app/tools/catalog.py`, `back/app/tools/catalog_refresh_service.py`, `back/app/tools/connection_functions.py`, `back/app/tools/dbadmin.py`, `back/app/tools/mcp_loader.py`, `back/app/tools/resource_effects.py`, `back/app/tools/router.py` |
| `app.tools` | `app.connection` | `back/app/tools/admin_access.py`, `back/app/tools/agent_registry.py`, `back/app/tools/connection_functions.py`, `back/app/tools/dbadmin.py`, `back/app/tools/mcp_loader.py` |
| `app.tools` | `app.console` | `back/app/tools/mcp_loader.py` |
| `app.tools` | `app.file_share` | `back/app/tools/resource_effects.py`, `back/app/tools/tool_service.py` |
| `app.tools` | `app.llm` | `back/app/tools/mcp_loader.py`, `back/app/tools/tool_search_service.py` |
| `app.tools` | `app.messenger` | `back/app/tools/mcp_loader.py`, `back/app/tools/tool_service.py` |
| `app.tools` | `app.task` | `back/app/tools/mcp_loader.py` |
| `app.tools` | `app.util` | `back/app/tools/search_tool.py` |
| `app.tools` | `core.authorize` | `back/app/tools/assertions.py`, `back/app/tools/router.py` |
| `app.tools` | `core.database` | `back/app/tools/catalog_refresh_service.py`, `back/app/tools/mandatory_tools.py`, `back/app/tools/mcp_loader.py`, `back/app/tools/models.py`, `back/app/tools/tool_search_service.py`, `back/app/tools/tool_service.py` |
| `app.tools` | `core.dbadmin` | `back/app/tools/dbadmin.py`, `back/app/tools/mandatory_tools.py` |
| `app.tools` | `core.failure_journal` | `back/app/tools/mcp_loader.py` |
| `app.tools` | `core.i18n` | `back/app/tools/agent_registry.py`, `back/app/tools/connection_functions.py`, `back/app/tools/mcp.py`, `back/app/tools/mcp_diagnostics.py`, `back/app/tools/mcp_loader.py`, `back/app/tools/router.py`, `back/app/tools/search_tool.py`, `back/app/tools/tool_errors.py`, `back/app/tools/tool_service.py` |
| `app.tools` | `core.params` | `back/app/tools/mandatory_tools.py`, `back/app/tools/mcp_loader.py` |
| `app.tools` | `core.util` | `back/app/tools/agent_registry.py`, `back/app/tools/assertions.py`, `back/app/tools/catalog.py`, `back/app/tools/secrets.py`, `back/app/tools/tool_service.py` |
| `app.topic` | `app.agent` | `back/app/topic/evaluation.py`, `back/app/topic/router.py`, `back/app/topic/sequential_detection.py`, `back/app/topic/service.py` |
| `app.topic` | `app.connection` | `back/app/topic/mcp.py`, `back/app/topic/router.py`, `back/app/topic/service.py` |
| `app.topic` | `app.conversation` | `back/app/topic/service.py` |
| `app.topic` | `app.llm` | `back/app/topic/classifier.py`, `back/app/topic/evaluation.py`, `back/app/topic/runtime_detection.py`, `back/app/topic/sequential_detection.py`, `back/app/topic/service.py` |
| `app.topic` | `app.memory` | `back/app/topic/service.py` |
| `app.topic` | `app.messenger` | `back/app/topic/service.py` |
| `app.topic` | `app.process` | `back/app/topic/service.py` |
| `app.topic` | `app.task` | `back/app/topic/service.py` |
| `app.topic` | `app.tools` | `back/app/topic/mcp.py` |
| `app.topic` | `core.authorize` | `back/app/topic/router.py` |
| `app.topic` | `core.database` | `back/app/topic/models.py`, `back/app/topic/runtime_detection.py`, `back/app/topic/service.py` |
| `app.topic` | `core.i18n` | `back/app/topic/classifier.py`, `back/app/topic/service.py` |
| `app.topic` | `core.params` | `back/app/topic/classifier.py`, `back/app/topic/sequential_detection.py` |
| `app.topic` | `core.util` | `back/app/topic/service.py` |
| `app.util` | `core.params` | `back/app/util/search.py` |
| `app.voice` | `app.agent` | `back/app/voice/conversation_service.py`, `back/app/voice/engine.py`, `back/app/voice/events.py`, `back/app/voice/facade.py`, `back/app/voice/inspection_service.py`, `back/app/voice/mcp.py`, `back/app/voice/monitoring_service.py`, `back/app/voice/realtime_engine.py`, `back/app/voice/realtime_tools.py`, `back/app/voice/router.py` |
| `app.voice` | `app.connection` | `back/app/voice/conversation_service.py`, `back/app/voice/events.py`, `back/app/voice/mcp.py`, `back/app/voice/monitoring_service.py` |
| `app.voice` | `app.conversation` | `back/app/voice/conversation_service.py`, `back/app/voice/engine.py`, `back/app/voice/inspection_service.py`, `back/app/voice/management_service.py`, `back/app/voice/mcp.py`, `back/app/voice/monitoring_service.py`, `back/app/voice/realtime_engine.py`, `back/app/voice/realtime_tools.py` |
| `app.voice` | `app.llm` | `back/app/voice/engine.py`, `back/app/voice/facade.py`, `back/app/voice/inspection_service.py`, `back/app/voice/monitoring_service.py`, `back/app/voice/realtime_engine.py`, `back/app/voice/realtime_tools.py` |
| `app.voice` | `app.memory` | `back/app/voice/realtime_tools.py`, `back/app/voice/session.py` |
| `app.voice` | `app.messenger` | `back/app/voice/conversation_service.py`, `back/app/voice/events.py`, `back/app/voice/facade.py`, `back/app/voice/mcp.py`, `back/app/voice/monitoring_service.py`, `back/app/voice/session.py` |
| `app.voice` | `app.process` | `back/app/voice/realtime_tools.py` |
| `app.voice` | `app.task` | `back/app/voice/mcp.py` |
| `app.voice` | `app.tools` | `back/app/voice/mcp.py`, `back/app/voice/monitoring_service.py` |
| `app.voice` | `core.authorize` | `back/app/voice/router.py` |
| `app.voice` | `core.database` | `back/app/voice/conversation_service.py`, `back/app/voice/engine.py`, `back/app/voice/events.py`, `back/app/voice/inspection_service.py`, `back/app/voice/management_service.py`, `back/app/voice/models.py`, `back/app/voice/monitoring_service.py`, `back/app/voice/realtime_engine.py`, `back/app/voice/realtime_tools.py`, `back/app/voice/session.py` |
| `app.voice` | `core.i18n` | `back/app/voice/call_manager.py`, `back/app/voice/engine.py`, `back/app/voice/mcp.py`, `back/app/voice/realtime_engine.py`, `back/app/voice/relay.py`, `back/app/voice/router.py` |
| `app.voice` | `core.params` | `back/app/voice/__init__.py`, `back/app/voice/audio_devices.py`, `back/app/voice/mcp.py` |
| `app.voice` | `core.user` | `back/app/voice/events.py` |
| `app.voice` | `core.util` | `back/app/voice/audio.py` |
| `app.webhook` | `app.agent` | `back/app/webhook/functions.py` |
| `app.webhook` | `app.connection` | `back/app/webhook/functions.py` |
| `app.webhook` | `app.task` | `back/app/webhook/functions.py` |
| `app.webhook` | `app.tools` | `back/app/webhook/functions.py` |
| `app.webhook` | `core.database` | `back/app/webhook/functions.py` |
| `app.webhook` | `core.i18n` | `back/app/webhook/functions.py` |
| `bridge.affine` | `core.i18n` | `back/bridge/affine/client.py` |
| `bridge.affine` | `core.util` | `back/bridge/affine/client.py` |
| `bridge.anthropic` | `app.llm` | `back/bridge/anthropic/__init__.py`, `back/bridge/anthropic/parameters.py`, `back/bridge/anthropic/resources.py` |
| `bridge.azure_speech` | `app.llm` | `back/bridge/azure_speech/__init__.py`, `back/bridge/azure_speech/resources.py`, `back/bridge/azure_speech/speech.py` |
| `bridge.azure_speech` | `core.util` | `back/bridge/azure_speech/resources.py`, `back/bridge/azure_speech/speech.py` |
| `bridge.byteplus` | `app.llm` | `back/bridge/byteplus/__init__.py`, `back/bridge/byteplus/media.py` |
| `bridge.byteplus` | `core.util` | `back/bridge/byteplus/media.py` |
| `bridge.calendar` | `app.agent` | `back/bridge/calendar/router.py`, `back/bridge/calendar/service.py` |
| `bridge.calendar` | `app.connection` | `back/bridge/calendar/router.py`, `back/bridge/calendar/service.py` |
| `bridge.calendar` | `app.file_share` | `back/bridge/calendar/transport.py` |
| `bridge.calendar` | `app.process` | `back/bridge/calendar/service.py` |
| `bridge.calendar` | `app.tools` | `back/bridge/calendar/mcp.py`, `back/bridge/calendar/service.py` |
| `bridge.calendar` | `core.authorize` | `back/bridge/calendar/router.py` |
| `bridge.calendar` | `core.database` | `back/bridge/calendar/models.py`, `back/bridge/calendar/service.py` |
| `bridge.calendar` | `core.util` | `back/bridge/calendar/service.py` |
| `bridge.cerebras` | `app.llm` | `back/bridge/cerebras/__init__.py` |
| `bridge.claude_agent` | `app.agent` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.claude_agent` | `app.harnesses` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.claude_agent` | `app.mcp` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.claude_agent` | `app.skill` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.claude_agent` | `bridge.harness` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.claude_agent` | `core.params` | `back/bridge/claude_agent/harness_provider.py` |
| `bridge.codex` | `app.agent` | `back/bridge/codex/harness_provider.py`, `back/bridge/codex/runtime_credentials.py` |
| `bridge.codex` | `app.harnesses` | `back/bridge/codex/harness_provider.py`, `back/bridge/codex/runtime_credentials.py` |
| `bridge.codex` | `app.llm` | `back/bridge/codex/runtime_credentials.py` |
| `bridge.codex` | `app.mcp` | `back/bridge/codex/harness_provider.py`, `back/bridge/codex/runtime_credentials.py` |
| `bridge.codex` | `app.skill` | `back/bridge/codex/harness_provider.py` |
| `bridge.codex` | `bridge.harness` | `back/bridge/codex/harness_provider.py` |
| `bridge.codex` | `core.authorize` | `back/bridge/codex/router.py` |
| `bridge.codex` | `core.params` | `back/bridge/codex/harness_provider.py` |
| `bridge.cohere` | `app.llm` | `back/bridge/cohere/__init__.py` |
| `bridge.deepseek` | `app.llm` | `back/bridge/deepseek/__init__.py`, `back/bridge/deepseek/parameters.py` |
| `bridge.deepseek_harness` | `app.agent` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `app.harnesses` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `app.llm` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `app.mcp` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `app.skill` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `bridge.harness` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.deepseek_harness` | `core.params` | `back/bridge/deepseek_harness/harness_provider.py` |
| `bridge.elevenlabs` | `app.llm` | `back/bridge/elevenlabs/__init__.py`, `back/bridge/elevenlabs/multimedia.py`, `back/bridge/elevenlabs/resources.py`, `back/bridge/elevenlabs/speech.py`, `back/bridge/elevenlabs/transcription.py` |
| `bridge.elevenlabs` | `core.util` | `back/bridge/elevenlabs/resources.py`, `back/bridge/elevenlabs/speech.py`, `back/bridge/elevenlabs/transcription.py` |
| `bridge.fireworks` | `app.llm` | `back/bridge/fireworks/__init__.py`, `back/bridge/fireworks/image.py` |
| `bridge.google` | `app.llm` | `back/bridge/google/__init__.py`, `back/bridge/google/image.py`, `back/bridge/google/parameters.py`, `back/bridge/google/resources.py`, `back/bridge/google/speech.py` |
| `bridge.google` | `core.util` | `back/bridge/google/image.py`, `back/bridge/google/resources.py`, `back/bridge/google/speech.py` |
| `bridge.grav` | `core.i18n` | `back/bridge/grav/client.py` |
| `bridge.grav` | `core.util` | `back/bridge/grav/client.py` |
| `bridge.groq` | `app.llm` | `back/bridge/groq/__init__.py`, `back/bridge/groq/parameters.py` |
| `bridge.harness` | `core.authorize` | `back/bridge/harness/router.py` |
| `bridge.harness` | `core.i18n` | `back/bridge/harness/manager.py` |
| `bridge.harness` | `core.params` | `back/bridge/harness/compose.py`, `back/bridge/harness/configuration.py`, `back/bridge/harness/diagnostics.py`, `back/bridge/harness/manager.py`, `back/bridge/harness/router.py` |
| `bridge.harness` | `core.settings` | `back/bridge/harness/diagnostics.py`, `back/bridge/harness/distribution.py` |
| `bridge.harness` | `core.util` | `back/bridge/harness/compose.py`, `back/bridge/harness/diagnostics.py`, `back/bridge/harness/manager.py` |
| `bridge.hermes` | `app.agent` | `back/bridge/hermes/agent_driver.py`, `back/bridge/hermes/approvals.py`, `back/bridge/hermes/checkpoint_policy.py`, `back/bridge/hermes/config_service.py`, `back/bridge/hermes/driver.py`, `back/bridge/hermes/executor.py`, `back/bridge/hermes/harness_provider.py`, `back/bridge/hermes/harness_supervisor.py`, `back/bridge/hermes/kanban.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/media.py`, `back/bridge/hermes/prompt.py`, `back/bridge/hermes/router.py`, `back/bridge/hermes/session_binding.py`, `back/bridge/hermes/skill_sync.py` |
| `bridge.hermes` | `app.connection` | `back/bridge/hermes/manager.py` |
| `bridge.hermes` | `app.file_share` | `back/bridge/hermes/paths.py` |
| `bridge.hermes` | `app.harnesses` | `back/bridge/hermes/harness_provider.py` |
| `bridge.hermes` | `app.llm` | `back/bridge/hermes/executor.py`, `back/bridge/hermes/kanban.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/media.py` |
| `bridge.hermes` | `app.mcp` | `back/bridge/hermes/manager.py`, `back/bridge/hermes/router.py` |
| `bridge.hermes` | `app.memory` | `back/bridge/hermes/router.py`, `back/bridge/hermes/schemas.py` |
| `bridge.hermes` | `app.messenger` | `back/bridge/hermes/approvals.py`, `back/bridge/hermes/executor.py`, `back/bridge/hermes/media.py` |
| `bridge.hermes` | `app.process` | `back/bridge/hermes/prompt.py` |
| `bridge.hermes` | `app.skill` | `back/bridge/hermes/prompt.py`, `back/bridge/hermes/skill_sync.py` |
| `bridge.hermes` | `app.tools` | `back/bridge/hermes/manager.py`, `back/bridge/hermes/prompt.py` |
| `bridge.hermes` | `bridge.harness` | `back/bridge/hermes/manager.py` |
| `bridge.hermes` | `core.authorize` | `back/bridge/hermes/router.py` |
| `bridge.hermes` | `core.database` | `back/bridge/hermes/agent_driver.py`, `back/bridge/hermes/config_service.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/media.py`, `back/bridge/hermes/models.py`, `back/bridge/hermes/session_binding.py`, `back/bridge/hermes/skill_sync.py` |
| `bridge.hermes` | `core.i18n` | `back/bridge/hermes/client.py`, `back/bridge/hermes/config_service.py`, `back/bridge/hermes/executor.py`, `back/bridge/hermes/kanban.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/router.py` |
| `bridge.hermes` | `core.params` | `back/bridge/hermes/executor.py`, `back/bridge/hermes/harness_provider.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/prompt.py`, `back/bridge/hermes/session_binding.py` |
| `bridge.hermes` | `core.util` | `back/bridge/hermes/client.py`, `back/bridge/hermes/config_service.py`, `back/bridge/hermes/executor.py`, `back/bridge/hermes/harness_provider.py`, `back/bridge/hermes/kanban.py`, `back/bridge/hermes/manager.py`, `back/bridge/hermes/session_binding.py` |
| `bridge.huggingface` | `app.llm` | `back/bridge/huggingface/__init__.py` |
| `bridge.mail` | `app.agent` | `back/bridge/mail/connection_service.py`, `back/bridge/mail/dbadmin.py`, `back/bridge/mail/router.py`, `back/bridge/mail/service.py` |
| `bridge.mail` | `app.connection` | `back/bridge/mail/connection_service.py`, `back/bridge/mail/dbadmin.py`, `back/bridge/mail/router.py` |
| `bridge.mail` | `app.file_share` | `back/bridge/mail/__init__.py`, `back/bridge/mail/file_transport.py`, `back/bridge/mail/service.py` |
| `bridge.mail` | `app.messenger` | `back/bridge/mail/__init__.py`, `back/bridge/mail/messenger.py`, `back/bridge/mail/service.py` |
| `bridge.mail` | `app.tools` | `back/bridge/mail/connection_service.py`, `back/bridge/mail/mcp.py` |
| `bridge.mail` | `core.authorize` | `back/bridge/mail/assertions.py`, `back/bridge/mail/router.py` |
| `bridge.mail` | `core.database` | `back/bridge/mail/models.py`, `back/bridge/mail/service.py` |
| `bridge.mail` | `core.dbadmin` | `back/bridge/mail/dbadmin.py` |
| `bridge.mail` | `core.i18n` | `back/bridge/mail/messenger.py` |
| `bridge.mail` | `core.user` | `back/bridge/mail/connection_service.py`, `back/bridge/mail/router.py`, `back/bridge/mail/service.py` |
| `bridge.mail` | `core.util` | `back/bridge/mail/service.py` |
| `bridge.mammouth` | `app.llm` | `back/bridge/mammouth/__init__.py`, `back/bridge/mammouth/image.py`, `back/bridge/mammouth/multimedia.py`, `back/bridge/mammouth/protocol.py`, `back/bridge/mammouth/resources.py` |
| `bridge.mammouth` | `core.util` | `back/bridge/mammouth/image.py`, `back/bridge/mammouth/multimedia.py`, `back/bridge/mammouth/resources.py` |
| `bridge.matrix` | `app.agent` | `back/bridge/matrix/voice_listener.py` |
| `bridge.matrix` | `app.connection` | `back/bridge/matrix/client.py`, `back/bridge/matrix/voice_listener.py`, `back/bridge/matrix/voice_provider.py` |
| `bridge.matrix` | `app.messenger` | `back/bridge/matrix/__init__.py`, `back/bridge/matrix/client.py`, `back/bridge/matrix/messenger.py`, `back/bridge/matrix/voice_listener.py`, `back/bridge/matrix/voice_provider.py` |
| `bridge.matrix` | `app.tools` | `back/bridge/matrix/voice_listener.py`, `back/bridge/matrix/voice_provider.py` |
| `bridge.matrix` | `app.voice` | `back/bridge/matrix/__init__.py`, `back/bridge/matrix/call.py`, `back/bridge/matrix/voice_listener.py`, `back/bridge/matrix/voice_provider.py` |
| `bridge.matrix` | `core.database` | `back/bridge/matrix/voice_listener.py` |
| `bridge.matrix` | `core.i18n` | `back/bridge/matrix/client.py` |
| `bridge.matrix` | `core.params` | `back/bridge/matrix/client.py`, `back/bridge/matrix/messenger.py`, `back/bridge/matrix/voice_listener.py` |
| `bridge.matrix` | `core.util` | `back/bridge/matrix/call.py`, `back/bridge/matrix/client.py`, `back/bridge/matrix/messenger.py`, `back/bridge/matrix/voice_listener.py` |
| `bridge.mistral` | `app.llm` | `back/bridge/mistral/__init__.py` |
| `bridge.models_dev` | `app.llm` | `back/bridge/models_dev/__init__.py`, `back/bridge/models_dev/service.py` |
| `bridge.models_dev` | `core.util` | `back/bridge/models_dev/service.py` |
| `bridge.n8n` | `app.process` | `back/bridge/n8n/__init__.py`, `back/bridge/n8n/engine.py`, `back/bridge/n8n/errors.py` |
| `bridge.n8n` | `core.authorize` | `back/bridge/n8n/router.py` |
| `bridge.n8n` | `core.i18n` | `back/bridge/n8n/client.py`, `back/bridge/n8n/engine.py` |
| `bridge.n8n` | `core.params` | `back/bridge/n8n/configuration.py`, `back/bridge/n8n/engine.py` |
| `bridge.nextcloud` | `app.agent` | `back/bridge/nextcloud/call_listener.py` |
| `bridge.nextcloud` | `app.connection` | `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/voice_provider.py` |
| `bridge.nextcloud` | `app.file_share` | `back/bridge/nextcloud/__init__.py`, `back/bridge/nextcloud/file_share.py` |
| `bridge.nextcloud` | `app.messenger` | `back/bridge/nextcloud/__init__.py`, `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/client.py`, `back/bridge/nextcloud/credentials.py`, `back/bridge/nextcloud/messenger.py`, `back/bridge/nextcloud/voice_provider.py` |
| `bridge.nextcloud` | `app.tools` | `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/voice_provider.py` |
| `bridge.nextcloud` | `app.voice` | `back/bridge/nextcloud/__init__.py`, `back/bridge/nextcloud/call.py`, `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/voice_provider.py` |
| `bridge.nextcloud` | `core.database` | `back/bridge/nextcloud/call_listener.py` |
| `bridge.nextcloud` | `core.i18n` | `back/bridge/nextcloud/call.py`, `back/bridge/nextcloud/client.py`, `back/bridge/nextcloud/credentials.py`, `back/bridge/nextcloud/file_share.py`, `back/bridge/nextcloud/messenger.py`, `back/bridge/nextcloud/signaling.py`, `back/bridge/nextcloud/voice_provider.py` |
| `bridge.nextcloud` | `core.params` | `back/bridge/nextcloud/call.py`, `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/messenger.py` |
| `bridge.nextcloud` | `core.util` | `back/bridge/nextcloud/call.py`, `back/bridge/nextcloud/call_listener.py`, `back/bridge/nextcloud/client.py`, `back/bridge/nextcloud/file_share.py`, `back/bridge/nextcloud/messenger.py`, `back/bridge/nextcloud/signaling.py` |
| `bridge.nvidia` | `app.llm` | `back/bridge/nvidia/__init__.py` |
| `bridge.ollama` | `app.llm` | `back/bridge/ollama/__init__.py`, `back/bridge/ollama/services.py` |
| `bridge.ollama` | `core.i18n` | `back/bridge/ollama/services.py` |
| `bridge.ollama` | `core.util` | `back/bridge/ollama/services.py` |
| `bridge.one_bot` | `app.connection` | `back/bridge/one_bot/messenger.py`, `back/bridge/one_bot/router.py` |
| `bridge.one_bot` | `app.messenger` | `back/bridge/one_bot/__init__.py`, `back/bridge/one_bot/client.py`, `back/bridge/one_bot/messenger.py`, `back/bridge/one_bot/router.py` |
| `bridge.one_bot` | `core.database` | `back/bridge/one_bot/router.py` |
| `bridge.one_bot` | `core.i18n` | `back/bridge/one_bot/client.py`, `back/bridge/one_bot/messenger.py` |
| `bridge.one_bot` | `core.util` | `back/bridge/one_bot/client.py`, `back/bridge/one_bot/messenger.py` |
| `bridge.openai` | `app.llm` | `back/bridge/openai/__init__.py`, `back/bridge/openai/codex.py`, `back/bridge/openai/codex_oauth.py`, `back/bridge/openai/codex_quota.py`, `back/bridge/openai/image.py`, `back/bridge/openai/parameters.py`, `back/bridge/openai/realtime.py`, `back/bridge/openai/resources.py` |
| `bridge.openai` | `core.database` | `back/bridge/openai/codex_oauth.py` |
| `bridge.openai` | `core.i18n` | `back/bridge/openai/codex_oauth.py`, `back/bridge/openai/codex_quota.py` |
| `bridge.openai` | `core.util` | `back/bridge/openai/codex_oauth.py`, `back/bridge/openai/codex_quota.py`, `back/bridge/openai/codex_responses.py`, `back/bridge/openai/image.py`, `back/bridge/openai/realtime.py` |
| `bridge.openrouter` | `app.llm` | `back/bridge/openrouter/__init__.py`, `back/bridge/openrouter/decisions.py`, `back/bridge/openrouter/image.py`, `back/bridge/openrouter/multimedia.py`, `back/bridge/openrouter/resources.py`, `back/bridge/openrouter/transcription.py` |
| `bridge.openrouter` | `core.util` | `back/bridge/openrouter/decisions.py`, `back/bridge/openrouter/image.py`, `back/bridge/openrouter/multimedia.py`, `back/bridge/openrouter/transcription.py`, `back/bridge/openrouter/usage.py` |
| `bridge.perplexity` | `app.llm` | `back/bridge/perplexity/__init__.py` |
| `bridge.sunoapi` | `app.llm` | `back/bridge/sunoapi/__init__.py`, `back/bridge/sunoapi/media.py` |
| `bridge.sunoapi` | `core.util` | `back/bridge/sunoapi/media.py` |
| `bridge.telegram` | `app.messenger` | `back/bridge/telegram/__init__.py`, `back/bridge/telegram/client.py`, `back/bridge/telegram/messenger.py` |
| `bridge.telegram` | `core.params` | `back/bridge/telegram/messenger.py` |
| `bridge.telegram` | `core.util` | `back/bridge/telegram/client.py`, `back/bridge/telegram/messenger.py` |
| `bridge.together` | `app.llm` | `back/bridge/together/__init__.py` |
| `bridge.whatsapp` | `app.connection` | `back/bridge/whatsapp/router.py` |
| `bridge.whatsapp` | `app.messenger` | `back/bridge/whatsapp/__init__.py`, `back/bridge/whatsapp/client.py`, `back/bridge/whatsapp/messenger.py`, `back/bridge/whatsapp/router.py` |
| `bridge.whatsapp` | `app.tools` | `back/bridge/whatsapp/router.py` |
| `bridge.whatsapp` | `core.authorize` | `back/bridge/whatsapp/router.py` |
| `bridge.whatsapp` | `core.params` | `back/bridge/whatsapp/messenger.py`, `back/bridge/whatsapp/router.py` |
| `bridge.whatsapp` | `core.util` | `back/bridge/whatsapp/client.py`, `back/bridge/whatsapp/messenger.py`, `back/bridge/whatsapp/router.py` |
| `bridge.xai` | `app.llm` | `back/bridge/xai/__init__.py`, `back/bridge/xai/parameters.py`, `back/bridge/xai/responses.py` |
| `core.api` | `core.authorize` | `back/core/api.py` |
| `core.api` | `core.database` | `back/core/api.py` |
| `core.api` | `core.logging` | `back/core/api.py` |
| `core.api` | `core.observability` | `back/core/api.py` |
| `core.api` | `core.params` | `back/core/api.py` |
| `core.api` | `core.rate_limit` | `back/core/api.py` |
| `core.api` | `core.user` | `back/core/api.py` |
| `core.api` | `core.util` | `back/core/api.py` |
| `core.authorize` | `core.database` | `back/core/authorize/admin_guard.py`, `back/core/authorize/guard_provider.py`, `back/core/authorize/model_scanner.py`, `back/core/authorize/models.py`, `back/core/authorize/router.py`, `back/core/authorize/update_admin_role.py` |
| `core.authorize` | `core.dbadmin` | `back/core/authorize/dbadmin.py`, `back/core/authorize/update_admin_role.py` |
| `core.authorize` | `core.i18n` | `back/core/authorize/admin_guard.py`, `back/core/authorize/guard_provider.py`, `back/core/authorize/router.py` |
| `core.authorize` | `core.user` | `back/core/authorize/admin_guard.py`, `back/core/authorize/assertions.py`, `back/core/authorize/authorize_service.py`, `back/core/authorize/guard_provider.py`, `back/core/authorize/logic.py`, `back/core/authorize/models.py`, `back/core/authorize/router.py`, `back/core/authorize/schemas.py` |
| `core.database` | `core.user` | `back/core/database/history.py` |
| `core.database` | `core.util` | `back/core/database/vector.py` |
| `core.dbadmin` | `core.database` | `back/core/dbadmin/_internal/atlas.py`, `back/core/dbadmin/_internal/target.py`, `back/core/dbadmin/actions.py`, `back/core/dbadmin/journal.py`, `back/core/dbadmin/models.py`, `back/core/dbadmin/orchestrator.py`, `back/core/dbadmin/snapshot.py` |
| `core.i18n` | `core.params` | `back/core/i18n/i18n_service.py` |
| `core.i18n` | `core.user` | `back/core/i18n/i18n_service.py` |
| `core.logging` | `core.i18n` | `back/core/logging.py` |
| `core.logging` | `core.secrets` | `back/core/logging.py` |
| `core.observability` | `core.database` | `back/core/observability.py` |
| `core.observability` | `core.params` | `back/core/observability.py` |
| `core.observability` | `core.util` | `back/core/observability.py` |
| `core.params` | `core.authorize` | `back/core/params/router.py` |
| `core.params` | `core.database` | `back/core/params/internal_secrets.py`, `back/core/params/models.py`, `back/core/params/params_service.py` |
| `core.params` | `core.dbadmin` | `back/core/params/dbadmin.py`, `back/core/params/params_service.py` |
| `core.params` | `core.i18n` | `back/core/params/router.py` |
| `core.params` | `core.secrets` | `back/core/params/internal_secrets.py`, `back/core/params/params_service.py` |
| `core.params` | `core.settings` | `back/core/params/middleware.py`, `back/core/params/runtime_settings.py` |
| `core.params` | `core.util` | `back/core/params/dbadmin.py`, `back/core/params/params_service.py` |
| `core.preview` | `core.secrets` | `back/core/preview/pdf.py` |
| `core.preview` | `core.settings` | `back/core/preview/pdf.py`, `back/core/preview/thumbnails.py` |
| `core.preview` | `core.user` | `back/core/preview/web.py` |
| `core.preview` | `core.util` | `back/core/preview/pdf.py` |
| `core.rate_limit` | `core.params` | `back/core/rate_limit.py` |
| `core.team` | `core.authorize` | `back/core/team/router.py` |
| `core.team` | `core.database` | `back/core/team/models.py`, `back/core/team/router.py`, `back/core/team/service.py` |
| `core.team` | `core.user` | `back/core/team/service.py` |
| `core.user` | `core.authorize` | `back/core/user/authContextMiddleware.py`, `back/core/user/auth_service.py`, `back/core/user/router.py`, `back/core/user/user_service.py` |
| `core.user` | `core.database` | `back/core/user/auth_service.py`, `back/core/user/help_service.py`, `back/core/user/mfa_service.py`, `back/core/user/models.py`, `back/core/user/refresh_session_service.py`, `back/core/user/router.py`, `back/core/user/token_service.py`, `back/core/user/user_service.py` |
| `core.user` | `core.i18n` | `back/core/user/auth_service.py`, `back/core/user/router.py`, `back/core/user/user_service.py` |
| `core.user` | `core.params` | `back/core/user/user_service.py` |
| `core.user` | `core.rate_limit` | `back/core/user/router.py` |
| `core.user` | `core.secrets` | `back/core/user/authContextMiddleware.py`, `back/core/user/auth_service.py`, `back/core/user/mfa_service.py`, `back/core/user/refresh_session_service.py`, `back/core/user/router.py` |
| `core.user` | `core.util` | `back/core/user/mfa_service.py`, `back/core/user/models.py`, `back/core/user/token_service.py` |

## Dépendances frontend inter-modules

| Source | Cible | Fichiers |
|---|---|---|
| `app/agent` | `app/harnesses` | `front/app/agent/pages/index.vue` |
| `app/agent` | `app/llm` | `front/app/agent/pages/index.vue` |
| `app/agent` | `core/api` | `front/app/agent/components/AgentSelect.vue`, `front/app/agent/composables/useHarnessLogs.ts`, `front/app/agent/pages/index.vue`, `front/app/agent/richContent.ts`, `front/app/agent/services/agentSelectionService.ts`, `front/app/agent/services/agentService.ts`, `front/app/agent/services/mcpTokenService.ts`, `front/app/agent/services/teamService.ts`, `front/app/agent/stores/agentStore.ts` |
| `app/agent` | `core/authorize` | `front/app/agent/components/AgentSelect.vue`, `front/app/agent/navigation.ts`, `front/app/agent/pages/index.vue` |
| `app/agent` | `core/navigation` | `front/app/agent/navigation.ts`, `front/app/agent/pages/index.vue` |
| `app/agent` | `core/params` | `front/app/agent/pages/index.vue` |
| `app/agent` | `core/team` | `front/app/agent/components/TeamAgentMembers.vue`, `front/app/agent/pages/index.vue`, `front/app/agent/team.ts` |
| `app/agent` | `core/util` | `front/app/agent/composables/useHarnessLogs.ts`, `front/app/agent/pages/index.vue`, `front/app/agent/richContent.ts` |
| `app/browser` | `app/connection` | `front/app/browser/stores/browserSettingsStore.ts` |
| `app/browser` | `core/api` | `front/app/browser/services/browserService.ts` |
| `app/browser` | `core/authorize` | `front/app/browser/navigation.ts`, `front/app/browser/stores/browserSettingsStore.ts` |
| `app/browser` | `core/navigation` | `front/app/browser/navigation.ts`, `front/app/browser/pages/settings.vue` |
| `app/browser` | `core/params` | `front/app/browser/pages/settings.vue`, `front/app/browser/settingsFields.ts` |
| `app/browser` | `core/user` | `front/app/browser/stores/browserSettingsStore.ts` |
| `app/browser` | `core/util` | `front/app/browser/pages/settings.vue` |
| `app/chat` | `app/agent` | `front/app/chat/components/RoomCreateDialog.vue` |
| `app/chat` | `app/conversation` | `front/app/chat/components/AgentExecutionTrace.vue` |
| `app/chat` | `app/task` | `front/app/chat/components/AgentExecutionTrace.vue`, `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/components/CompactTaskOperations.vue`, `front/app/chat/liveState.ts`, `front/app/chat/runtimeState.ts`, `front/app/chat/types.ts` |
| `app/chat` | `app/topic` | `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/components/Composer.vue`, `front/app/chat/components/MessageTimeline.vue`, `front/app/chat/components/RoomCreateDialog.vue`, `front/app/chat/components/RoomPreferencesDialog.vue` |
| `app/chat` | `core/api` | `front/app/chat/availability.ts`, `front/app/chat/components/AgentExecutionTrace.vue`, `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/components/ChatIdentityMappings.vue`, `front/app/chat/components/ChatNotificationBootstrap.vue`, `front/app/chat/components/ConversationDocumentsPanel.vue`, `front/app/chat/components/ConversationProcessesPanel.vue`, `front/app/chat/components/MessageTimeline.vue`, `front/app/chat/pages/index.vue`, `front/app/chat/services/chatService.ts`, `front/app/chat/stores/chat.ts`, `front/app/chat/stores/inbox.ts` |
| `app/chat` | `core/authorize` | `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/navigation.ts`, `front/app/chat/pages/index.vue`, `front/app/chat/stores/chat.ts` |
| `app/chat` | `core/navigation` | `front/app/chat/navigation.ts` |
| `app/chat` | `core/params` | `front/app/chat/settings.ts` |
| `app/chat` | `core/user` | `front/app/chat/components/ChatProfilePreferences.vue`, `front/app/chat/components/MessageResourcePreviews.vue` |
| `app/chat` | `core/util` | `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/components/ChatDocumentPane.vue`, `front/app/chat/components/ChatDocumentSearchDialog.vue`, `front/app/chat/components/ConversationDocumentDialog.vue`, `front/app/chat/components/ConversationDocumentsPanel.vue`, `front/app/chat/components/ConversationProcessDialog.vue`, `front/app/chat/components/MarkdownAttachmentPreview.vue`, `front/app/chat/components/MessageResourcePreviews.vue`, `front/app/chat/components/MessageTimeline.vue`, `front/app/chat/components/SafeMessageContent.vue`, `front/app/chat/pages/index.vue` |
| `app/chat` | `core/websocket` | `front/app/chat/components/AgentExecutionTrace.vue`, `front/app/chat/components/AgentTasksPanel.vue`, `front/app/chat/components/ConversationDocumentsPanel.vue`, `front/app/chat/components/ConversationProcessesPanel.vue`, `front/app/chat/components/MessageResourcePreviews.vue`, `front/app/chat/pages/index.vue`, `front/app/chat/stores/chat.ts`, `front/app/chat/stores/inbox.ts` |
| `app/connection` | `app/agent` | `front/app/connection/components/AuthorizationManager.vue`, `front/app/connection/components/ConnectionForm.vue`, `front/app/connection/components/ConnectionList.vue`, `front/app/connection/pages/mail.vue` |
| `app/connection` | `app/console` | `front/app/connection/components/ConnectionForm.vue` |
| `app/connection` | `app/tools` | `front/app/connection/components/AuthorizationManager.vue`, `front/app/connection/components/ConnectionForm.vue`, `front/app/connection/components/ConnectionList.vue` |
| `app/connection` | `core/api` | `front/app/connection/availability.ts`, `front/app/connection/components/CalendarConnectionEditor.vue`, `front/app/connection/services/calendarService.ts`, `front/app/connection/services/connectionService.ts`, `front/app/connection/services/mailService.ts` |
| `app/connection` | `core/authorize` | `front/app/connection/components/AuthorizationManager.vue`, `front/app/connection/components/CalendarConnectionEditor.vue`, `front/app/connection/components/ConnectionForm.vue`, `front/app/connection/components/ConnectionList.vue`, `front/app/connection/navigation.ts` |
| `app/connection` | `core/navigation` | `front/app/connection/navigation.ts`, `front/app/connection/pages/mail.vue` |
| `app/connection` | `core/util` | `front/app/connection/components/ConnectionForm.vue`, `front/app/connection/pages/mail.vue` |
| `app/console` | `core/api` | `front/app/console/services/consoleService.ts` |
| `app/console` | `core/authorize` | `front/app/console/navigation.ts`, `front/app/console/pages/executor.vue` |
| `app/console` | `core/navigation` | `front/app/console/navigation.ts`, `front/app/console/pages/executor.vue` |
| `app/console` | `core/util` | `front/app/console/pages/executor.vue` |
| `app/conversation` | `app/agent` | `front/app/conversation/components/ConversationHistory.vue`, `front/app/conversation/components/ConversationRoundDetail.vue` |
| `app/conversation` | `app/lab` | `front/app/conversation/components/ConversationRoundDetail.vue` |
| `app/conversation` | `app/llm` | `front/app/conversation/components/ConversationExecutionDetails.vue`, `front/app/conversation/components/ConversationHistory.vue`, `front/app/conversation/components/ConversationRoundDetail.vue`, `front/app/conversation/services/conversationService.ts`, `front/app/conversation/types.ts` |
| `app/conversation` | `app/task` | `front/app/conversation/components/ConversationExecutionDetails.vue`, `front/app/conversation/components/ConversationRoundDetail.vue`, `front/app/conversation/types.ts` |
| `app/conversation` | `app/topic` | `front/app/conversation/components/ConversationHistory.vue`, `front/app/conversation/components/ConversationRoundDetail.vue` |
| `app/conversation` | `core/api` | `front/app/conversation/components/ConversationRoundDetail.vue`, `front/app/conversation/components/DeliveryResolution.vue`, `front/app/conversation/services/conversationService.ts` |
| `app/conversation` | `core/authorize` | `front/app/conversation/components/ConversationRoundDetail.vue` |
| `app/conversation` | `core/util` | `front/app/conversation/components/ConversationExecutionDetails.vue`, `front/app/conversation/components/ConversationHistory.vue`, `front/app/conversation/components/ConversationRoundDetail.vue` |
| `app/dream` | `app/llm` | `front/app/dream/pages/index.vue`, `front/app/dream/types.ts` |
| `app/dream` | `core/api` | `front/app/dream/services/dreamService.ts` |
| `app/dream` | `core/authorize` | `front/app/dream/navigation.ts` |
| `app/dream` | `core/navigation` | `front/app/dream/navigation.ts`, `front/app/dream/pages/index.vue` |
| `app/dream` | `core/util` | `front/app/dream/pages/index.vue` |
| `app/dream` | `core/websocket` | `front/app/dream/pages/index.vue` |
| `app/goal` | `app/agent` | `front/app/goal/pages/index.vue` |
| `app/goal` | `core/api` | `front/app/goal/pages/index.vue`, `front/app/goal/services/goalService.ts`, `front/app/goal/stores/goalStore.ts` |
| `app/goal` | `core/authorize` | `front/app/goal/navigation.ts`, `front/app/goal/pages/index.vue` |
| `app/goal` | `core/navigation` | `front/app/goal/navigation.ts`, `front/app/goal/pages/index.vue` |
| `app/goal` | `core/user` | `front/app/goal/pages/index.vue`, `front/app/goal/stores/goalStore.ts` |
| `app/goal` | `core/util` | `front/app/goal/pages/index.vue`, `front/app/goal/richContent.ts` |
| `app/goal` | `core/websocket` | `front/app/goal/stores/goalStore.ts` |
| `app/harnesses` | `core/api` | `front/app/harnesses/services/harnessService.ts`, `front/app/harnesses/services/managerService.ts` |
| `app/harnesses` | `core/authorize` | `front/app/harnesses/components/HarnessCatalogGrid.vue`, `front/app/harnesses/components/HarnessEditor.vue`, `front/app/harnesses/components/HarnessManagedProviders.vue`, `front/app/harnesses/components/HarnessManagerConfiguration.vue`, `front/app/harnesses/components/HarnessPreferences.vue` |
| `app/harnesses` | `core/params` | `front/app/harnesses/components/HarnessEditor.vue`, `front/app/harnesses/components/HarnessManagedProviders.vue`, `front/app/harnesses/components/HarnessPipelineSettings.vue`, `front/app/harnesses/components/HarnessPreferences.vue`, `front/app/harnesses/components/TaskExecutionSettings.vue`, `front/app/harnesses/managedSettings.ts`, `front/app/harnesses/runtimeSettings.ts`, `front/app/harnesses/settings.ts` |
| `app/harnesses` | `core/util` | `front/app/harnesses/components/HarnessEditor.vue`, `front/app/harnesses/components/HarnessExecutionSettings.vue`, `front/app/harnesses/components/HarnessManagerConfiguration.vue` |
| `app/incident` | `core/api` | `front/app/incident/services/incidentService.ts` |
| `app/incident` | `core/authorize` | `front/app/incident/navigation.ts`, `front/app/incident/pages/index.vue` |
| `app/incident` | `core/navigation` | `front/app/incident/navigation.ts`, `front/app/incident/pages/index.vue` |
| `app/incident` | `core/util` | `front/app/incident/pages/index.vue` |
| `app/index` | `app/agent` | `front/app/index/components/DashboardAgentTable.vue`, `front/app/index/components/DashboardLiveActivity.vue` |
| `app/index` | `app/llm` | `front/app/index/components/DashboardLiveActivity.vue` |
| `app/index` | `app/onboarding` | `front/app/index/components/HomeActionCenter.vue`, `front/app/index/pages/index.vue`, `front/app/index/pages/welcome.vue` |
| `app/index` | `app/task` | `front/app/index/components/DashboardLiveActivity.vue` |
| `app/index` | `core/api` | `front/app/index/services/dashboardService.ts`, `front/app/index/services/homeService.ts`, `front/app/index/stores/dashboardStore.ts` |
| `app/index` | `core/authorize` | `front/app/index/components/HomeActionCenter.vue`, `front/app/index/components/HomeConnected.vue`, `front/app/index/navigation.ts`, `front/app/index/stores/dashboardStore.ts` |
| `app/index` | `core/navigation` | `front/app/index/components/HomeActionCenter.vue`, `front/app/index/components/HomeConnected.vue`, `front/app/index/components/Sidebar.vue`, `front/app/index/navigation.ts` |
| `app/index` | `core/settings` | `front/app/index/components/HomePublic.vue`, `front/app/index/components/MainLayout.vue`, `front/app/index/components/Sidebar.vue`, `front/app/index/components/SidebarFooter.vue`, `front/app/index/environmentPresentation.ts`, `front/app/index/pages/about.vue` |
| `app/index` | `core/user` | `front/app/index/components/HomeActionCenter.vue`, `front/app/index/components/HomePublic.vue`, `front/app/index/components/MainLayout.vue`, `front/app/index/pages/index.vue`, `front/app/index/pages/welcome.vue`, `front/app/index/stores/dashboardStore.ts` |
| `app/index` | `core/util` | `front/app/index/components/DashboardLiveActivity.vue`, `front/app/index/components/HomeActionCenter.vue`, `front/app/index/components/HomeConnected.vue`, `front/app/index/environmentPresentation.ts`, `front/app/index/pages/about.vue`, `front/app/index/pages/license.vue` |
| `app/index` | `core/websocket` | `front/app/index/components/DashboardLiveActivity.vue` |
| `app/lab` | `app/task` | `front/app/lab/pages/ai-evaluations.vue` |
| `app/lab` | `core/api` | `front/app/lab/components/LabHumanReviewDialog.vue`, `front/app/lab/components/LabSyntheticDatasetDialog.vue`, `front/app/lab/components/LabWorkbench.vue`, `front/app/lab/services/dispatcherEvaluationService.ts`, `front/app/lab/services/evaluationService.ts`, `front/app/lab/services/labWorkbenchService.ts`, `front/app/lab/services/mechanismEvaluationService.ts` |
| `app/lab` | `core/authorize` | `front/app/lab/access.ts`, `front/app/lab/components/TaskLabCaptureMenu.vue`, `front/app/lab/pages/[section].vue`, `front/app/lab/pages/ai-evaluations.vue`, `front/app/lab/pages/index.vue` |
| `app/lab` | `core/navigation` | `front/app/lab/navigation.ts`, `front/app/lab/pages/ai-evaluations.vue`, `front/app/lab/pages/index.vue` |
| `app/lab` | `core/util` | `front/app/lab/components/LabResultsPanel.vue`, `front/app/lab/components/LabValueEditor.vue`, `front/app/lab/components/LabWorkbench.vue`, `front/app/lab/components/MemoryExtractionCaseEditor.vue`, `front/app/lab/pages/ai-evaluations.vue`, `front/app/lab/pages/index.vue`, `front/app/lab/textPresentation.ts` |
| `app/llm` | `app/agent` | `front/app/llm/components/LlmActivityPanel.vue`, `front/app/llm/components/LlmCall.vue` |
| `app/llm` | `app/task` | `front/app/llm/components/LlmCall.vue`, `front/app/llm/components/LlmCallDetails.vue`, `front/app/llm/presentation.ts` |
| `app/llm` | `core/api` | `front/app/llm/components/LlmCalls.vue`, `front/app/llm/services/llmCallService.ts`, `front/app/llm/services/llmProfileService.ts`, `front/app/llm/services/llmProviderService.ts`, `front/app/llm/services/personalLlmService.ts` |
| `app/llm` | `core/authorize` | `front/app/llm/components/ConfiguredLlmManager.vue`, `front/app/llm/components/CustomProviderDialog.vue`, `front/app/llm/components/LlmActivityPanel.vue`, `front/app/llm/components/LlmCalls.vue`, `front/app/llm/components/LlmUsageManager.vue`, `front/app/llm/components/ProviderConfigPanel.vue`, `front/app/llm/components/ProviderListPanel.vue`, `front/app/llm/components/ProviderModelsPanel.vue`, `front/app/llm/components/ProviderWorkspace.vue`, `front/app/llm/navigation.ts`, `front/app/llm/pages/index.vue` |
| `app/llm` | `core/navigation` | `front/app/llm/navigation.ts`, `front/app/llm/pages/index.vue` |
| `app/llm` | `core/user` | `front/app/llm/userTab.ts` |
| `app/llm` | `core/util` | `front/app/llm/components/ConfiguredLlmManager.vue`, `front/app/llm/components/LlmActivityPanel.vue`, `front/app/llm/components/LlmCall.vue`, `front/app/llm/components/LlmCallDetails.vue`, `front/app/llm/components/LlmCallTaskDetail.vue`, `front/app/llm/components/LlmCalls.vue`, `front/app/llm/components/LlmUsageManager.vue`, `front/app/llm/components/ProviderQuotaPanel.vue`, `front/app/llm/pages/index.vue`, `front/app/llm/useEditorVoice.ts` |
| `app/llm` | `core/websocket` | `front/app/llm/components/LlmActivityPanel.vue`, `front/app/llm/components/LlmCalls.vue` |
| `app/memory` | `app/agent` | `front/app/memory/components/DocumentEditor.vue`, `front/app/memory/components/DocumentHistoryDialog.vue`, `front/app/memory/components/DocumentLibraryPage.vue`, `front/app/memory/components/MemorySharingPanel.vue`, `front/app/memory/pages/contacts.vue`, `front/app/memory/pages/index.vue` |
| `app/memory` | `core/api` | `front/app/memory/components/DocumentAttachments.vue`, `front/app/memory/components/DocumentLibraryNavigation.vue`, `front/app/memory/components/DocumentThumbnail.vue`, `front/app/memory/pages/contacts.vue`, `front/app/memory/pages/index.vue`, `front/app/memory/richContent.ts`, `front/app/memory/services/contactService.ts`, `front/app/memory/services/memoryService.ts`, `front/app/memory/stores/documentIcons.ts` |
| `app/memory` | `core/authorize` | `front/app/memory/components/DocumentEditor.vue`, `front/app/memory/navigation.ts`, `front/app/memory/pages/contacts.vue`, `front/app/memory/pages/index.vue` |
| `app/memory` | `core/navigation` | `front/app/memory/components/DocumentLibraryPage.vue`, `front/app/memory/navigation.ts`, `front/app/memory/pages/contacts.vue`, `front/app/memory/pages/index.vue` |
| `app/memory` | `core/util` | `front/app/memory/components/DocumentApplication.vue`, `front/app/memory/components/DocumentApplicationBlock.vue`, `front/app/memory/components/DocumentAttachments.vue`, `front/app/memory/components/DocumentEditor.vue`, `front/app/memory/components/DocumentFolderSelect.vue`, `front/app/memory/components/DocumentHistoryDialog.vue`, `front/app/memory/components/DocumentLibraryPage.vue`, `front/app/memory/components/DocumentTagIcon.vue`, `front/app/memory/components/DocumentTagIconPicker.vue`, `front/app/memory/components/MemoryAttachmentButton.vue`, `front/app/memory/components/MemoryGraph.vue`, `front/app/memory/components/MemoryItemForm.vue`, `front/app/memory/components/MemoryItemHistory.vue`, `front/app/memory/components/MemorySharingPanel.vue`, `front/app/memory/documentEditor.ts`, `front/app/memory/documentFolders.ts`, `front/app/memory/pages/contacts.vue`, `front/app/memory/pages/index.vue`, `front/app/memory/richContent.ts`, `front/app/memory/services/memoryService.ts` |
| `app/memory` | `core/websocket` | `front/app/memory/components/DocumentApplication.vue`, `front/app/memory/components/DocumentEditor.vue`, `front/app/memory/components/DocumentLibraryNavigation.vue`, `front/app/memory/components/DocumentLibraryPage.vue`, `front/app/memory/components/DocumentThumbnail.vue`, `front/app/memory/components/MemoryGraph.vue`, `front/app/memory/components/MemorySearchTester.vue`, `front/app/memory/stores/memoryStore.ts` |
| `app/onboarding` | `core/api` | `front/app/onboarding/services/onboardingService.ts` |
| `app/onboarding` | `core/user` | `front/app/onboarding/components/WelcomePage.vue` |
| `app/process` | `app/agent` | `front/app/process/components/ProcessRunsPanel.vue`, `front/app/process/pages/index.vue` |
| `app/process` | `app/task` | `front/app/process/components/ProcessRunDetailContent.vue` |
| `app/process` | `core/api` | `front/app/process/services/processService.ts` |
| `app/process` | `core/authorize` | `front/app/process/navigation.ts`, `front/app/process/pages/index.vue` |
| `app/process` | `core/navigation` | `front/app/process/navigation.ts`, `front/app/process/pages/index.vue` |
| `app/process` | `core/util` | `front/app/process/components/ProcessRunDetailContent.vue`, `front/app/process/components/ProcessRunsPanel.vue`, `front/app/process/pages/index.vue` |
| `app/process` | `core/websocket` | `front/app/process/components/ProcessRunsPanel.vue` |
| `app/skill` | `app/agent` | `front/app/skill/components/LearnedSkillManager.vue`, `front/app/skill/components/SkillAuthorizationManager.vue` |
| `app/skill` | `core/api` | `front/app/skill/services/skillService.ts` |
| `app/skill` | `core/authorize` | `front/app/skill/components/LearnedSkillManager.vue`, `front/app/skill/components/SkillAuthorizationManager.vue`, `front/app/skill/navigation.ts`, `front/app/skill/pages/index.vue` |
| `app/skill` | `core/navigation` | `front/app/skill/navigation.ts`, `front/app/skill/pages/index.vue` |
| `app/skill` | `core/util` | `front/app/skill/components/LearnedSkillManager.vue`, `front/app/skill/pages/index.vue` |
| `app/task` | `app/agent` | `front/app/task/components/ActiveTaskNode.vue`, `front/app/task/components/ActiveTasksPanel.vue`, `front/app/task/components/TaskDetail.vue`, `front/app/task/components/TaskFormDialog.vue`, `front/app/task/services/taskService.ts`, `front/app/task/stores/taskStore.ts` |
| `app/task` | `app/conversation` | `front/app/task/pages/index.vue` |
| `app/task` | `app/lab` | `front/app/task/components/TaskDetail.vue` |
| `app/task` | `app/llm` | `front/app/task/components/ExecutionResult.vue`, `front/app/task/pages/index.vue`, `front/app/task/useTaskActivity.ts` |
| `app/task` | `app/memory` | `front/app/task/components/ExecutionMemoryPanel.vue`, `front/app/task/components/MemoryItemCard.vue` |
| `app/task` | `app/process` | `front/app/task/pages/index.vue` |
| `app/task` | `app/topic` | `front/app/task/components/ActiveTaskNode.vue`, `front/app/task/components/ActiveTasksPanel.vue`, `front/app/task/components/TaskDetail.vue` |
| `app/task` | `app/voice` | `front/app/task/pages/index.vue` |
| `app/task` | `core/api` | `front/app/task/components/TaskBudget.vue`, `front/app/task/components/TaskDetail.vue`, `front/app/task/pages/index.vue`, `front/app/task/richContent.ts`, `front/app/task/services/taskService.ts` |
| `app/task` | `core/authorize` | `front/app/task/components/TaskDetail.vue`, `front/app/task/components/TaskFormDialog.vue`, `front/app/task/navigation.ts`, `front/app/task/pages/index.vue` |
| `app/task` | `core/i18n` | `front/app/task/services/taskStatusService.ts` |
| `app/task` | `core/navigation` | `front/app/task/navigation.ts`, `front/app/task/pages/index.vue` |
| `app/task` | `core/user` | `front/app/task/components/TaskDetail.vue`, `front/app/task/stores/taskStore.ts` |
| `app/task` | `core/util` | `front/app/task/components/ActiveTaskNode.vue`, `front/app/task/components/ActiveTasksPanel.vue`, `front/app/task/components/BriefingResult.vue`, `front/app/task/components/DispatchResult.vue`, `front/app/task/components/ExecutionResult.vue`, `front/app/task/components/MemoryItemCard.vue`, `front/app/task/components/PlannerResult.vue`, `front/app/task/components/TaskDetail.vue`, `front/app/task/components/TaskFormDialog.vue`, `front/app/task/pages/index.vue`, `front/app/task/richContent.ts`, `front/app/task/services/taskStatusService.ts` |
| `app/task` | `core/websocket` | `front/app/task/stores/taskStore.ts`, `front/app/task/useTaskActivity.ts` |
| `app/tools` | `app/connection` | `front/app/tools/components/ToolsList.vue`, `front/app/tools/pages/index.vue` |
| `app/tools` | `core/api` | `front/app/tools/components/ToolsList.vue`, `front/app/tools/services/toolService.ts` |
| `app/tools` | `core/authorize` | `front/app/tools/components/ToolsList.vue`, `front/app/tools/navigation.ts` |
| `app/tools` | `core/navigation` | `front/app/tools/navigation.ts`, `front/app/tools/pages/index.vue` |
| `app/tools` | `core/util` | `front/app/tools/components/ToolsList.vue`, `front/app/tools/pages/index.vue` |
| `app/topic` | `core/api` | `front/app/topic/components/TopicBadge.vue`, `front/app/topic/components/TopicSelect.vue`, `front/app/topic/services/topicService.ts` |
| `app/topic` | `core/authorize` | `front/app/topic/components/TopicBadge.vue`, `front/app/topic/components/TopicSelect.vue`, `front/app/topic/navigation.ts`, `front/app/topic/pages/index.vue` |
| `app/topic` | `core/navigation` | `front/app/topic/navigation.ts`, `front/app/topic/pages/[id].vue`, `front/app/topic/pages/index.vue` |
| `app/topic` | `core/util` | `front/app/topic/components/TopicParticipants.vue`, `front/app/topic/pages/[id].vue`, `front/app/topic/pages/index.vue` |
| `app/voice` | `app/agent` | `front/app/voice/components/VoiceCallHistory.vue`, `front/app/voice/components/VoiceConversationDetail.vue` |
| `app/voice` | `app/lab` | `front/app/voice/components/VoiceConversationDetail.vue` |
| `app/voice` | `app/llm` | `front/app/voice/components/VoiceConversationDetail.vue`, `front/app/voice/services/voiceConversationService.ts`, `front/app/voice/types.ts` |
| `app/voice` | `app/task` | `front/app/voice/components/VoiceConversationDetail.vue`, `front/app/voice/types.ts` |
| `app/voice` | `app/topic` | `front/app/voice/components/VoiceCallHistory.vue`, `front/app/voice/components/VoiceConversationDetail.vue` |
| `app/voice` | `core/api` | `front/app/voice/services/voiceConversationService.ts` |
| `app/voice` | `core/authorize` | `front/app/voice/components/VoiceConversationDetail.vue` |
| `app/voice` | `core/util` | `front/app/voice/components/VoiceCallHistory.vue`, `front/app/voice/components/VoiceConversationDetail.vue` |
| `app/voice` | `core/websocket` | `front/app/voice/components/VoiceCallHistory.vue` |
| `bridge/hermes` | `app/agent` | `front/bridge/hermes/agentTab.ts` |
| `bridge/hermes` | `core/api` | `front/bridge/hermes/services/hermesService.ts` |
| `bridge/hermes` | `core/authorize` | `front/bridge/hermes/components/HermesAgentConfiguration.vue` |
| `bridge/hermes` | `core/params` | `front/bridge/hermes/settings.ts` |
| `bridge/hermes` | `core/util` | `front/bridge/hermes/components/HermesAgentConfiguration.vue` |
| `bridge/matrix` | `core/params` | `front/bridge/matrix/settings.ts` |
| `bridge/n8n` | `core/api` | `front/bridge/n8n/services/configurationService.ts` |
| `bridge/n8n` | `core/authorize` | `front/bridge/n8n/components/N8nSettingsPanel.vue` |
| `bridge/n8n` | `core/params` | `front/bridge/n8n/components/N8nSettingsPanel.vue`, `front/bridge/n8n/settings.ts` |
| `bridge/n8n` | `core/util` | `front/bridge/n8n/components/N8nSettingsPanel.vue` |
| `bridge/nextcloud` | `core/params` | `front/bridge/nextcloud/settings.ts` |
| `bridge/ollama` | `app/llm` | `front/bridge/ollama/llmProvider.ts` |
| `bridge/one_bot` | `core/params` | `front/bridge/one_bot/settings.ts` |
| `bridge/telegram` | `core/params` | `front/bridge/telegram/settings.ts` |
| `bridge/whatsapp` | `core/params` | `front/bridge/whatsapp/settings.ts` |
| `core/App` | `app/index` | `front/core/App.vue` |
| `core/App` | `core/authorize` | `front/core/App.vue` |
| `core/App` | `core/settings` | `front/core/App.vue` |
| `core/App` | `core/user` | `front/core/App.vue` |
| `core/api` | `core/i18n` | `front/core/api.ts` |
| `core/authorize` | `core/api` | `front/core/authorize/components/AssignmentManager.vue`, `front/core/authorize/services/authorize.service.ts`, `front/core/authorize/services/privilege.service.ts`, `front/core/authorize/stores/authorizeStore.ts` |
| `core/authorize` | `core/i18n` | `front/core/authorize/components/UserPreferencesMenu.vue`, `front/core/authorize/pages/profile.vue`, `front/core/authorize/presentation.ts` |
| `core/authorize` | `core/navigation` | `front/core/authorize/navigation.ts`, `front/core/authorize/pages/index.vue`, `front/core/authorize/pages/profile.vue` |
| `core/authorize` | `core/theme` | `front/core/authorize/components/UserPreferencesMenu.vue`, `front/core/authorize/pages/profile.vue` |
| `core/authorize` | `core/user` | `front/core/authorize/components/AssignmentManager.vue`, `front/core/authorize/components/AssignmentMenu.vue`, `front/core/authorize/components/UserPreferencesMenu.vue`, `front/core/authorize/pages/profile.vue`, `front/core/authorize/services/authorize.service.ts`, `front/core/authorize/stores/authorizeStore.ts`, `front/core/authorize/stores/privilegeStore.ts` |
| `core/authorize` | `core/util` | `front/core/authorize/components/AssignmentManager.vue`, `front/core/authorize/components/PrivilegeListManager.vue`, `front/core/authorize/components/RoleManager.vue`, `front/core/authorize/pages/index.vue`, `front/core/authorize/pages/profile.vue` |
| `core/main` | `app/index` | `front/core/main.ts` |
| `core/main` | `app/style` | `front/core/main.ts` |
| `core/main` | `core/App` | `front/core/main.ts` |
| `core/main` | `core/i18n` | `front/core/main.ts` |
| `core/navigation` | `core/authorize` | `front/core/navigation/composables/useNavigation.ts`, `front/core/navigation/index.ts` |
| `core/params` | `app/llm` | `front/core/params/components/LogCleanupPanel.vue` |
| `core/params` | `app/task` | `front/core/params/components/LogCleanupPanel.vue` |
| `core/params` | `core/api` | `front/core/params/services/configurationService.ts`, `front/core/params/services/logCleanupService.ts`, `front/core/params/services/paramsService.ts` |
| `core/params` | `core/authorize` | `front/core/params/components/BridgeSettingsPanel.vue`, `front/core/params/components/DreamSettingsPanel.vue`, `front/core/params/components/LogCleanupPanel.vue`, `front/core/params/components/MessagingSettingsPanel.vue`, `front/core/params/components/PreferencesSectionPage.vue`, `front/core/params/components/PromptSettingEditor.vue`, `front/core/params/components/SettingFieldControl.vue`, `front/core/params/navigation.ts` |
| `core/params` | `core/navigation` | `front/core/params/components/PreferencesMenuGrid.vue`, `front/core/params/components/PreferencesSectionPage.vue`, `front/core/params/navigation.ts`, `front/core/params/pages/index.vue` |
| `core/params` | `core/util` | `front/core/params/components/PreferencesMenuGrid.vue`, `front/core/params/components/PreferencesSectionPage.vue`, `front/core/params/components/PromptSettingEditor.vue`, `front/core/params/components/SettingFieldControl.vue`, `front/core/params/pages/harnesses/[provider].vue`, `front/core/params/pages/index.vue`, `front/core/params/settingsTypes.ts` |
| `core/team` | `core/api` | `front/core/team/components/TeamEditor.vue`, `front/core/team/services/teamService.ts` |
| `core/team` | `core/authorize` | `front/core/team/components/TeamEditor.vue`, `front/core/team/components/TeamManager.vue` |
| `core/team` | `core/navigation` | `front/core/team/navigation.ts` |
| `core/team` | `core/user` | `front/core/team/components/TeamEditor.vue`, `front/core/team/components/TeamHumanSummary.vue` |
| `core/team` | `core/util` | `front/core/team/pages/index.vue` |
| `core/user` | `core/api` | `front/core/user/services/authService.ts`, `front/core/user/services/helpService.ts`, `front/core/user/services/tokenService.ts`, `front/core/user/services/userService.ts`, `front/core/user/stores/authStore.ts`, `front/core/user/stores/helpStore.ts` |
| `core/user` | `core/authorize` | `front/core/user/components/UserAdminForm.vue`, `front/core/user/components/UserMenu.vue`, `front/core/user/pages/users.vue` |
| `core/user` | `core/i18n` | `front/core/user/stores/authStore.ts`, `front/core/user/stores/tokenStore.ts` |
| `core/user` | `core/navigation` | `front/core/user/navigation.ts`, `front/core/user/pages/tokens.vue`, `front/core/user/pages/users.vue` |
| `core/user` | `core/settings` | `front/core/user/pages/login.vue`, `front/core/user/pages/register.vue` |
| `core/user` | `core/util` | `front/core/user/components/UserAvatar.vue`, `front/core/user/components/UserMenu.vue`, `front/core/user/contextHelp.ts`, `front/core/user/pages/tokens.vue`, `front/core/user/pages/users.vue` |
| `core/websocket` | `core/api` | `front/core/websocket.ts` |

## Métriques de couplage des domaines backend

> Ces métriques portent sur les arêtes entre modules `app.*` et `bridge.*`.
> Le manifeste et la baseline d’architecture déterminent les régressions admises.

### Fan-out

| Module | Nombre | Dépendances |
|---|---:|---|
| `app.file_share` | 14 | `app.agent`, `app.connection`, `app.console`, `app.conversation`, `app.goal`, `app.image`, `app.memory`, `app.messenger`, `app.process`, `app.skill`, `app.task`, `app.tools`, `bridge.affine`, `bridge.grav` |
| `app.lab` | 14 | `app.agent`, `app.connection`, `app.conversation`, `app.dream`, `app.goal`, `app.llm`, `app.memory`, `app.messenger`, `app.process`, `app.skill`, `app.task`, `app.tools`, `app.topic`, `app.voice` |
| `app.dream` | 12 | `app.agent`, `app.connection`, `app.conversation`, `app.goal`, `app.llm`, `app.memory`, `app.messenger`, `app.process`, `app.skill`, `app.task`, `app.topic`, `app.voice` |
| `bridge.hermes` | 12 | `app.agent`, `app.connection`, `app.file_share`, `app.harnesses`, `app.llm`, `app.mcp`, `app.memory`, `app.messenger`, `app.process`, `app.skill`, `app.tools`, `bridge.harness` |
| `app.harness` | 9 | `app.agent`, `app.console`, `app.conversation`, `app.file_share`, `app.llm`, `app.messenger`, `app.process`, `app.skill`, `app.tools` |
| `app.memory` | 9 | `app.agent`, `app.conversation`, `app.goal`, `app.llm`, `app.process`, `app.task`, `app.tools`, `app.topic`, `app.voice` |
| `app.topic` | 9 | `app.agent`, `app.connection`, `app.conversation`, `app.llm`, `app.memory`, `app.messenger`, `app.process`, `app.task`, `app.tools` |
| `app.voice` | 9 | `app.agent`, `app.connection`, `app.conversation`, `app.llm`, `app.memory`, `app.messenger`, `app.process`, `app.task`, `app.tools` |
| `app.conversation` | 8 | `app.agent`, `app.connection`, `app.file_share`, `app.llm`, `app.messenger`, `app.process`, `app.task`, `app.tools` |
| `app.llm` | 8 | `app.agent`, `app.connection`, `app.conversation`, `app.mcp`, `app.messenger`, `app.process`, `app.task`, `app.tools` |
| `app.messenger` | 8 | `app.agent`, `app.connection`, `app.conversation`, `app.file_share`, `app.llm`, `app.memory`, `app.task`, `app.tools` |
| `app.tools` | 8 | `app.agent`, `app.connection`, `app.console`, `app.file_share`, `app.llm`, `app.messenger`, `app.task`, `app.util` |
| `app.onboarding` | 7 | `app.agent`, `app.connection`, `app.llm`, `app.messenger`, `app.process`, `app.skill`, `app.tools` |
| `app.audio` | 6 | `app.file_share`, `app.llm`, `app.messenger`, `app.task`, `app.tools`, `bridge.youtube` |
| `app.chat` | 6 | `app.agent`, `app.browser`, `app.conversation`, `app.messenger`, `app.topic`, `app.voice` |
| `app.goal` | 6 | `app.agent`, `app.connection`, `app.llm`, `app.messenger`, `app.task`, `app.tools` |
| `app.process` | 6 | `app.agent`, `app.console`, `app.file_share`, `app.llm`, `app.task`, `app.tools` |
| `bridge.codex` | 6 | `app.agent`, `app.harnesses`, `app.llm`, `app.mcp`, `app.skill`, `bridge.harness` |
| `bridge.deepseek_harness` | 6 | `app.agent`, `app.harnesses`, `app.llm`, `app.mcp`, `app.skill`, `bridge.harness` |
| `bridge.nextcloud` | 6 | `app.agent`, `app.connection`, `app.file_share`, `app.messenger`, `app.tools`, `app.voice` |
| `app.agent` | 5 | `app.llm`, `app.messenger`, `app.process`, `app.skill`, `app.tools` |
| `app.contact` | 5 | `app.agent`, `app.conversation`, `app.memory`, `app.messenger`, `app.task` |
| `app.multimedia` | 5 | `app.agent`, `app.file_share`, `app.llm`, `app.process`, `app.tools` |
| `app.task` | 5 | `app.agent`, `app.goal`, `app.llm`, `app.messenger`, `app.tools` |
| `bridge.calendar` | 5 | `app.agent`, `app.connection`, `app.file_share`, `app.process`, `app.tools` |
| `bridge.claude_agent` | 5 | `app.agent`, `app.harnesses`, `app.mcp`, `app.skill`, `bridge.harness` |
| `bridge.mail` | 5 | `app.agent`, `app.connection`, `app.file_share`, `app.messenger`, `app.tools` |
| `bridge.matrix` | 5 | `app.agent`, `app.connection`, `app.messenger`, `app.tools`, `app.voice` |
| `app.console` | 4 | `app.agent`, `app.connection`, `app.file_share`, `app.tools` |
| `app.webhook` | 4 | `app.agent`, `app.connection`, `app.task`, `app.tools` |
| `app.browser` | 3 | `app.connection`, `app.file_share`, `app.tools` |
| `app.dashboard` | 3 | `app.agent`, `app.llm`, `app.task` |
| `app.image` | 3 | `app.file_share`, `app.llm`, `app.tools` |
| `app.skill` | 3 | `app.agent`, `app.connection`, `app.tools` |
| `bridge.whatsapp` | 3 | `app.connection`, `app.messenger`, `app.tools` |
| `app.connection` | 2 | `app.agent`, `app.tools` |
| `app.mcp` | 2 | `app.agent`, `app.tools` |
| `bridge.one_bot` | 2 | `app.connection`, `app.messenger` |
| `app.harnesses` | 1 | `app.agent` |
| `bridge.anthropic` | 1 | `app.llm` |
| `bridge.azure_speech` | 1 | `app.llm` |
| `bridge.byteplus` | 1 | `app.llm` |
| `bridge.cerebras` | 1 | `app.llm` |
| `bridge.cohere` | 1 | `app.llm` |
| `bridge.deepseek` | 1 | `app.llm` |
| `bridge.elevenlabs` | 1 | `app.llm` |
| `bridge.fireworks` | 1 | `app.llm` |
| `bridge.google` | 1 | `app.llm` |
| `bridge.groq` | 1 | `app.llm` |
| `bridge.huggingface` | 1 | `app.llm` |
| `bridge.mammouth` | 1 | `app.llm` |
| `bridge.mistral` | 1 | `app.llm` |
| `bridge.models_dev` | 1 | `app.llm` |
| `bridge.n8n` | 1 | `app.process` |
| `bridge.nvidia` | 1 | `app.llm` |
| `bridge.ollama` | 1 | `app.llm` |
| `bridge.openai` | 1 | `app.llm` |
| `bridge.openrouter` | 1 | `app.llm` |
| `bridge.perplexity` | 1 | `app.llm` |
| `bridge.sunoapi` | 1 | `app.llm` |
| `bridge.telegram` | 1 | `app.messenger` |
| `bridge.together` | 1 | `app.llm` |
| `bridge.xai` | 1 | `app.llm` |

### Fan-in

| Module | Nombre | Dépendants |
|---|---:|---|
| `app.llm` | 43 | `app.agent`, `app.audio`, `app.conversation`, `app.dashboard`, `app.dream`, `app.goal`, `app.harness`, `app.image`, `app.lab`, `app.memory`, `app.messenger`, `app.multimedia`, `app.onboarding`, `app.process`, `app.task`, `app.tools`, `app.topic`, `app.voice`, `bridge.anthropic`, `bridge.azure_speech`, `bridge.byteplus`, `bridge.cerebras`, `bridge.codex`, `bridge.cohere`, `bridge.deepseek`, `bridge.deepseek_harness`, `bridge.elevenlabs`, `bridge.fireworks`, `bridge.google`, `bridge.groq`, `bridge.hermes`, `bridge.huggingface`, `bridge.mammouth`, `bridge.mistral`, `bridge.models_dev`, `bridge.nvidia`, `bridge.ollama`, `bridge.openai`, `bridge.openrouter`, `bridge.perplexity`, `bridge.sunoapi`, `bridge.together`, `bridge.xai` |
| `app.agent` | 33 | `app.chat`, `app.connection`, `app.console`, `app.contact`, `app.conversation`, `app.dashboard`, `app.dream`, `app.file_share`, `app.goal`, `app.harness`, `app.harnesses`, `app.lab`, `app.llm`, `app.mcp`, `app.memory`, `app.messenger`, `app.multimedia`, `app.onboarding`, `app.process`, `app.skill`, `app.task`, `app.tools`, `app.topic`, `app.voice`, `app.webhook`, `bridge.calendar`, `bridge.claude_agent`, `bridge.codex`, `bridge.deepseek_harness`, `bridge.hermes`, `bridge.mail`, `bridge.matrix`, `bridge.nextcloud` |
| `app.tools` | 29 | `app.agent`, `app.audio`, `app.browser`, `app.connection`, `app.console`, `app.conversation`, `app.file_share`, `app.goal`, `app.harness`, `app.image`, `app.lab`, `app.llm`, `app.mcp`, `app.memory`, `app.messenger`, `app.multimedia`, `app.onboarding`, `app.process`, `app.skill`, `app.task`, `app.topic`, `app.voice`, `app.webhook`, `bridge.calendar`, `bridge.hermes`, `bridge.mail`, `bridge.matrix`, `bridge.nextcloud`, `bridge.whatsapp` |
| `app.messenger` | 23 | `app.agent`, `app.audio`, `app.chat`, `app.contact`, `app.conversation`, `app.dream`, `app.file_share`, `app.goal`, `app.harness`, `app.lab`, `app.llm`, `app.onboarding`, `app.task`, `app.tools`, `app.topic`, `app.voice`, `bridge.hermes`, `bridge.mail`, `bridge.matrix`, `bridge.nextcloud`, `bridge.one_bot`, `bridge.telegram`, `bridge.whatsapp` |
| `app.connection` | 22 | `app.browser`, `app.console`, `app.conversation`, `app.dream`, `app.file_share`, `app.goal`, `app.lab`, `app.llm`, `app.messenger`, `app.onboarding`, `app.skill`, `app.tools`, `app.topic`, `app.voice`, `app.webhook`, `bridge.calendar`, `bridge.hermes`, `bridge.mail`, `bridge.matrix`, `bridge.nextcloud`, `bridge.one_bot`, `bridge.whatsapp` |
| `app.task` | 16 | `app.audio`, `app.contact`, `app.conversation`, `app.dashboard`, `app.dream`, `app.file_share`, `app.goal`, `app.lab`, `app.llm`, `app.memory`, `app.messenger`, `app.process`, `app.tools`, `app.topic`, `app.voice`, `app.webhook` |
| `app.process` | 15 | `app.agent`, `app.conversation`, `app.dream`, `app.file_share`, `app.harness`, `app.lab`, `app.llm`, `app.memory`, `app.multimedia`, `app.onboarding`, `app.topic`, `app.voice`, `bridge.calendar`, `bridge.hermes`, `bridge.n8n` |
| `app.file_share` | 14 | `app.audio`, `app.browser`, `app.console`, `app.conversation`, `app.harness`, `app.image`, `app.messenger`, `app.multimedia`, `app.process`, `app.tools`, `bridge.calendar`, `bridge.hermes`, `bridge.mail`, `bridge.nextcloud` |
| `app.conversation` | 11 | `app.chat`, `app.contact`, `app.dream`, `app.file_share`, `app.harness`, `app.lab`, `app.llm`, `app.memory`, `app.messenger`, `app.topic`, `app.voice` |
| `app.skill` | 10 | `app.agent`, `app.dream`, `app.file_share`, `app.harness`, `app.lab`, `app.onboarding`, `bridge.claude_agent`, `bridge.codex`, `bridge.deepseek_harness`, `bridge.hermes` |
| `app.memory` | 8 | `app.contact`, `app.dream`, `app.file_share`, `app.lab`, `app.messenger`, `app.topic`, `app.voice`, `bridge.hermes` |
| `app.voice` | 6 | `app.chat`, `app.dream`, `app.lab`, `app.memory`, `bridge.matrix`, `bridge.nextcloud` |
| `app.goal` | 5 | `app.dream`, `app.file_share`, `app.lab`, `app.memory`, `app.task` |
| `app.mcp` | 5 | `app.llm`, `bridge.claude_agent`, `bridge.codex`, `bridge.deepseek_harness`, `bridge.hermes` |
| `app.console` | 4 | `app.file_share`, `app.harness`, `app.process`, `app.tools` |
| `app.harnesses` | 4 | `bridge.claude_agent`, `bridge.codex`, `bridge.deepseek_harness`, `bridge.hermes` |
| `app.topic` | 4 | `app.chat`, `app.dream`, `app.lab`, `app.memory` |
| `bridge.harness` | 4 | `bridge.claude_agent`, `bridge.codex`, `bridge.deepseek_harness`, `bridge.hermes` |
| `app.browser` | 1 | `app.chat` |
| `app.dream` | 1 | `app.lab` |
| `app.image` | 1 | `app.file_share` |
| `app.util` | 1 | `app.tools` |
| `bridge.affine` | 1 | `app.file_share` |
| `bridge.grav` | 1 | `app.file_share` |
| `bridge.youtube` | 1 | `app.audio` |

### Cycles directs

- `app.agent` ↔ `app.llm`
- `app.agent` ↔ `app.messenger`
- `app.agent` ↔ `app.process`
- `app.agent` ↔ `app.skill`
- `app.agent` ↔ `app.tools`
- `app.connection` ↔ `app.tools`
- `app.console` ↔ `app.file_share`
- `app.console` ↔ `app.tools`
- `app.conversation` ↔ `app.file_share`
- `app.conversation` ↔ `app.llm`
- `app.conversation` ↔ `app.messenger`
- `app.file_share` ↔ `app.image`
- `app.file_share` ↔ `app.messenger`
- `app.file_share` ↔ `app.process`
- `app.file_share` ↔ `app.tools`
- `app.goal` ↔ `app.task`
- `app.llm` ↔ `app.messenger`
- `app.llm` ↔ `app.process`
- `app.llm` ↔ `app.task`
- `app.llm` ↔ `app.tools`
- `app.memory` ↔ `app.topic`
- `app.memory` ↔ `app.voice`
- `app.messenger` ↔ `app.task`
- `app.messenger` ↔ `app.tools`
- `app.task` ↔ `app.tools`

### Composantes fortement connexes

- `app.agent`, `app.connection`, `app.console`, `app.conversation`, `app.file_share`, `app.goal`, `app.image`, `app.llm`, `app.mcp`, `app.memory`, `app.messenger`, `app.process`, `app.skill`, `app.task`, `app.tools`, `app.topic`, `app.voice`

## Métriques de couplage des domaines frontend

> Ces métriques portent sur les imports entre modules `app/*` et `bridge/*`.

### Fan-out frontend

| Module | Nombre | Dépendances |
|---|---:|---|
| `app/task` | 8 | `app/agent`, `app/conversation`, `app/lab`, `app/llm`, `app/memory`, `app/process`, `app/topic`, `app/voice` |
| `app/conversation` | 5 | `app/agent`, `app/lab`, `app/llm`, `app/task`, `app/topic` |
| `app/voice` | 5 | `app/agent`, `app/lab`, `app/llm`, `app/task`, `app/topic` |
| `app/chat` | 4 | `app/agent`, `app/conversation`, `app/task`, `app/topic` |
| `app/index` | 4 | `app/agent`, `app/llm`, `app/onboarding`, `app/task` |
| `app/connection` | 3 | `app/agent`, `app/console`, `app/tools` |
| `app/agent` | 2 | `app/harnesses`, `app/llm` |
| `app/llm` | 2 | `app/agent`, `app/task` |
| `app/process` | 2 | `app/agent`, `app/task` |
| `app/browser` | 1 | `app/connection` |
| `app/dream` | 1 | `app/llm` |
| `app/goal` | 1 | `app/agent` |
| `app/lab` | 1 | `app/task` |
| `app/memory` | 1 | `app/agent` |
| `app/skill` | 1 | `app/agent` |
| `app/tools` | 1 | `app/connection` |
| `bridge/hermes` | 1 | `app/agent` |
| `bridge/ollama` | 1 | `app/llm` |

### Fan-in frontend

| Module | Nombre | Dépendants |
|---|---:|---|
| `app/agent` | 12 | `app/chat`, `app/connection`, `app/conversation`, `app/goal`, `app/index`, `app/llm`, `app/memory`, `app/process`, `app/skill`, `app/task`, `app/voice`, `bridge/hermes` |
| `app/llm` | 7 | `app/agent`, `app/conversation`, `app/dream`, `app/index`, `app/task`, `app/voice`, `bridge/ollama` |
| `app/task` | 7 | `app/chat`, `app/conversation`, `app/index`, `app/lab`, `app/llm`, `app/process`, `app/voice` |
| `app/topic` | 4 | `app/chat`, `app/conversation`, `app/task`, `app/voice` |
| `app/lab` | 3 | `app/conversation`, `app/task`, `app/voice` |
| `app/connection` | 2 | `app/browser`, `app/tools` |
| `app/conversation` | 2 | `app/chat`, `app/task` |
| `app/console` | 1 | `app/connection` |
| `app/harnesses` | 1 | `app/agent` |
| `app/memory` | 1 | `app/task` |
| `app/onboarding` | 1 | `app/index` |
| `app/process` | 1 | `app/task` |
| `app/tools` | 1 | `app/connection` |
| `app/voice` | 1 | `app/task` |

### Cycles directs frontend

- `app/agent` ↔ `app/llm`
- `app/connection` ↔ `app/tools`
- `app/conversation` ↔ `app/task`
- `app/lab` ↔ `app/task`
- `app/llm` ↔ `app/task`
- `app/process` ↔ `app/task`
- `app/task` ↔ `app/voice`

### Composantes fortement connexes frontend

- `app/agent`, `app/conversation`, `app/lab`, `app/llm`, `app/memory`, `app/process`, `app/task`, `app/voice`
- `app/connection`, `app/tools`

## Routes backend déclarées

> Les préfixes ajoutés lors de l’agrégation de routers ne peuvent pas tous être
> reconstruits statiquement ; `declared_path` décrit le préfixe local détecté.

| Méthode | Chemin déclaré | Module | Handler | RBAC local | Source |
|---|---|---|---|---:|---|
| POST | `/agent/openai/chat/completions` | `app.agent` | `agent_chat_completions` | oui | `back/app/agent/openai_router.py:77` |
| GET | `/agent/openai/models` | `app.agent` | `get_agent_models` | oui | `back/app/agent/openai_router.py:66` |
| GET | `/agents` | `app.agent` | `read_agents` | oui | `back/app/agent/router.py:203` |
| POST | `/agents` | `app.agent` | `create_agent` | oui | `back/app/agent/router.py:254` |
| GET | `/agents/drivers` | `app.agent` | `read_executor_drivers` | oui | `back/app/agent/router.py:171` |
| GET | `/agents/groups` | `app.agent` | `read_groups` | oui | `back/app/agent/router.py:114` |
| POST | `/agents/groups` | `app.agent` | `create_group` | oui | `back/app/agent/router.py:134` |
| DELETE | `/agents/groups/{id}` | `app.agent` | `delete_group` | oui | `back/app/agent/router.py:156` |
| GET | `/agents/groups/{id}` | `app.agent` | `read_group` | oui | `back/app/agent/router.py:123` |
| PUT | `/agents/groups/{id}` | `app.agent` | `update_group` | oui | `back/app/agent/router.py:143` |
| GET | `/agents/managers` | `app.agent` | `read_agent_managers` | oui | `back/app/agent/router.py:219` |
| GET | `/agents/selection` | `app.agent` | `read_agent_selection` | oui | `back/app/agent/router.py:46` |
| GET | `/agents/teams/agents` | `app.agent` | `agents` | oui | `back/app/agent/team_router.py:16` |
| PUT | `/agents/teams/{team_id}/members/{agent_id}` | `app.agent` | `update_membership` | oui | `back/app/agent/team_router.py:23` |
| GET | `/agents/titles` | `app.agent` | `read_titles` | oui | `back/app/agent/router.py:57` |
| POST | `/agents/titles` | `app.agent` | `create_title` | oui | `back/app/agent/router.py:77` |
| DELETE | `/agents/titles/{id}` | `app.agent` | `delete_title` | oui | `back/app/agent/router.py:99` |
| GET | `/agents/titles/{id}` | `app.agent` | `read_title` | oui | `back/app/agent/router.py:66` |
| PUT | `/agents/titles/{id}` | `app.agent` | `update_title` | oui | `back/app/agent/router.py:86` |
| GET | `/agents/{agent_id}/mcp-tokens` | `app.mcp` | `list_agent_mcp_tokens` | oui | `back/app/mcp/router.py:66` |
| POST | `/agents/{agent_id}/mcp-tokens` | `app.mcp` | `create_agent_mcp_token` | oui | `back/app/mcp/router.py:87` |
| DELETE | `/agents/{agent_id}/mcp-tokens/{token_id}` | `app.mcp` | `delete_agent_mcp_token` | oui | `back/app/mcp/router.py:137` |
| PUT | `/agents/{agent_id}/mcp-tokens/{token_id}` | `app.mcp` | `update_agent_mcp_token` | oui | `back/app/mcp/router.py:112` |
| DELETE | `/agents/{id}` | `app.agent` | `delete_agent` | oui | `back/app/agent/router.py:309` |
| GET | `/agents/{id}` | `app.agent` | `read_agent` | oui | `back/app/agent/router.py:242` |
| PUT | `/agents/{id}` | `app.agent` | `update_agent` | oui | `back/app/agent/router.py:282` |
| DELETE | `/agents/{id}/avatar` | `app.agent` | `delete_avatar` | oui | `back/app/agent/router.py:392` |
| GET | `/agents/{id}/avatar` | `app.agent` | `download_avatar` | oui | `back/app/agent/router.py:358` |
| POST | `/agents/{id}/avatar` | `app.agent` | `upload_avatar` | oui | `back/app/agent/router.py:323` |
| GET | `/api/docs` | `core.api` | `public_swagger_ui_html` | non | `back/core/api.py:235` |
| GET | `/api/health` | `core.api` | `health_check` | non | `back/core/api.py:266` |
| GET | `/api/health/live` | `core.api` | `liveness_check` | non | `back/core/api.py:271` |
| GET | `/api/health/ready` | `core.api` | `readiness_check` | non | `back/core/api.py:277` |
| GET | `/api/openapi.json` | `core.api` | `get_public_openapi_endpoint` | non | `back/core/api.py:229` |
| GET | `/auth/avatars/{avatar_key}` | `core.user` | `read_user_avatar` | non | `back/core/user/router.py:409` |
| POST | `/auth/keep-alive` | `core.user` | `keep_alive` | oui | `back/core/user/router.py:382` |
| POST | `/auth/login` | `core.user` | `login` | non | `back/core/user/router.py:207` |
| POST | `/auth/login-json` | `core.user` | `login_json` | non | `back/core/user/router.py:231` |
| POST | `/auth/logout` | `core.user` | `logout` | non | `back/core/user/router.py:324` |
| DELETE | `/auth/me` | `core.user` | `delete_user_me` | oui | `back/core/user/router.py:475` |
| GET | `/auth/me` | `core.user` | `read_users_me` | oui | `back/core/user/router.py:401` |
| PUT | `/auth/me` | `core.user` | `update_user_me` | oui | `back/core/user/router.py:516` |
| DELETE | `/auth/me/avatar` | `core.user` | `delete_user_avatar` | oui | `back/core/user/router.py:463` |
| POST | `/auth/me/avatar` | `core.user` | `upload_user_avatar` | oui | `back/core/user/router.py:426` |
| GET | `/auth/me/help-dismissals` | `core.user` | `list_help_dismissals` | oui | `back/core/user/router.py:495` |
| PUT | `/auth/me/help-dismissals/{help_key}` | `core.user` | `dismiss_help` | oui | `back/core/user/router.py:505` |
| GET | `/auth/me/tokens` | `core.user` | `list_my_tokens` | oui | `back/core/user/router.py:610` |
| POST | `/auth/me/tokens` | `core.user` | `create_my_token` | oui | `back/core/user/router.py:623` |
| DELETE | `/auth/me/tokens/{token_id}` | `core.user` | `delete_my_token` | oui | `back/core/user/router.py:663` |
| PUT | `/auth/me/tokens/{token_id}` | `core.user` | `update_my_token` | oui | `back/core/user/router.py:644` |
| POST | `/auth/mfa/confirm` | `core.user` | `confirm_mfa` | oui | `back/core/user/router.py:285` |
| POST | `/auth/mfa/disable` | `core.user` | `disable_mfa` | oui | `back/core/user/router.py:298` |
| POST | `/auth/mfa/recovery-codes` | `core.user` | `regenerate_mfa_recovery_codes` | oui | `back/core/user/router.py:311` |
| POST | `/auth/mfa/setup` | `core.user` | `setup_mfa` | oui | `back/core/user/router.py:273` |
| GET | `/auth/mfa/status` | `core.user` | `read_mfa_status` | oui | `back/core/user/router.py:260` |
| POST | `/auth/refresh` | `core.user` | `refresh_session` | non | `back/core/user/router.py:342` |
| POST | `/auth/register` | `core.user` | `register` | non | `back/core/user/router.py:132` |
| GET | `/auth/registration-status` | `core.user` | `registration_status` | non | `back/core/user/router.py:120` |
| GET | `/auth/users` | `core.user` | `list_users` | oui | `back/core/user/router.py:546` |
| POST | `/auth/users` | `core.user` | `create_user_endpoint` | oui | `back/core/user/router.py:560` |
| DELETE | `/auth/users/{user_id}` | `core.user` | `delete_user_endpoint` | oui | `back/core/user/router.py:594` |
| GET | `/auth/users/{user_id}` | `core.user` | `read_user` | oui | `back/core/user/router.py:571` |
| PUT | `/auth/users/{user_id}` | `core.user` | `update_user_endpoint` | oui | `back/core/user/router.py:580` |
| GET | `/authorize/assignments` | `core.authorize` | `list_assignments` | oui | `back/core/authorize/router.py:269` |
| POST | `/authorize/assignments` | `core.authorize` | `create_assignment` | oui | `back/core/authorize/router.py:321` |
| DELETE | `/authorize/assignments/{id}` | `core.authorize` | `delete_assignment` | oui | `back/core/authorize/router.py:345` |
| PUT | `/authorize/assignments/{id}/default` | `core.authorize` | `set_default_assignment` | oui | `back/core/authorize/router.py:399` |
| GET | `/authorize/my-privileges` | `core.authorize` | `get_my_privileges` | oui | `back/core/authorize/router.py:66` |
| GET | `/authorize/privilege-lists` | `core.authorize` | `list_privilege_lists` | oui | `back/core/authorize/router.py:451` |
| POST | `/authorize/privilege-lists` | `core.authorize` | `create_privilege_list` | oui | `back/core/authorize/router.py:462` |
| DELETE | `/authorize/privilege-lists/{id}` | `core.authorize` | `delete_privilege_list` | oui | `back/core/authorize/router.py:508` |
| PUT | `/authorize/privilege-lists/{id}` | `core.authorize` | `update_privilege_list` | oui | `back/core/authorize/router.py:487` |
| DELETE | `/authorize/privilege-lists/{id}/privileges` | `core.authorize` | `remove_privileges_from_list` | oui | `back/core/authorize/router.py:560` |
| POST | `/authorize/privilege-lists/{id}/privileges` | `core.authorize` | `add_privileges_to_list` | oui | `back/core/authorize/router.py:529` |
| GET | `/authorize/privileges` | `core.authorize` | `list_privileges` | oui | `back/core/authorize/router.py:59` |
| POST | `/authorize/privileges` | `core.authorize` | `create_privilege` | oui | `back/core/authorize/router.py:89` |
| DELETE | `/authorize/privileges/{id}` | `core.authorize` | `delete_privilege` | oui | `back/core/authorize/router.py:107` |
| GET | `/authorize/roles` | `core.authorize` | `list_roles` | oui | `back/core/authorize/router.py:131` |
| POST | `/authorize/roles` | `core.authorize` | `create_role` | oui | `back/core/authorize/router.py:150` |
| DELETE | `/authorize/roles/{id}` | `core.authorize` | `delete_role` | oui | `back/core/authorize/router.py:191` |
| GET | `/authorize/roles/{id}` | `core.authorize` | `get_role` | oui | `back/core/authorize/router.py:138` |
| PUT | `/authorize/roles/{id}` | `core.authorize` | `update_role` | oui | `back/core/authorize/router.py:168` |
| DELETE | `/authorize/roles/{role_id}/privileges` | `core.authorize` | `remove_privileges_from_role` | oui | `back/core/authorize/router.py:242` |
| POST | `/authorize/roles/{role_id}/privileges` | `core.authorize` | `add_privileges_to_role` | oui | `back/core/authorize/router.py:211` |
| POST | `/authorize/switch-role` | `core.authorize` | `switch_role` | oui | `back/core/authorize/router.py:366` |
| GET | `/authorize/users/{user_id}/assignments` | `core.authorize` | `get_user_assignments` | oui | `back/core/authorize/router.py:307` |
| GET | `/browser/status` | `app.browser` | `status` | oui | `back/app/browser/router.py:18` |
| GET | `/calendars` | `bridge.calendar` | `read_calendars` | oui | `back/bridge/calendar/router.py:54` |
| POST | `/calendars` | `bridge.calendar` | `create_calendar` | oui | `back/bridge/calendar/router.py:61` |
| DELETE | `/calendars/{calendar_id}` | `bridge.calendar` | `delete_calendar` | oui | `back/bridge/calendar/router.py:89` |
| PUT | `/calendars/{calendar_id}` | `bridge.calendar` | `update_calendar` | oui | `back/bridge/calendar/router.py:75` |
| POST | `/calendars/{calendar_id}/test` | `bridge.calendar` | `test_calendar` | oui | `back/bridge/calendar/router.py:97` |
| GET | `/chat/agents/{agent_id}/avatar` | `app.chat` | `read_agent_avatar` | oui | `back/app/chat/router.py:446` |
| GET | `/chat/emojis/frequent` | `app.chat` | `read_frequent_emojis` | oui | `back/app/chat/router.py:361` |
| POST | `/chat/emojis/usage` | `app.chat` | `create_emoji_usage` | oui | `back/app/chat/router.py:370` |
| POST | `/chat/html-previews` | `app.chat` | `create_standalone_html_preview` | oui | `back/app/chat/router.py:273` |
| GET | `/chat/html-previews/{ticket}` | `app.chat` | `read_standalone_html_preview` | non | `back/app/chat/router.py:288` |
| GET | `/chat/identities` | `app.chat` | `read_identity_mappings` | oui | `back/app/chat/router.py:380` |
| DELETE | `/chat/identities/{tool_id}` | `app.chat` | `delete_identity_mapping` | oui | `back/app/chat/router.py:410` |
| PUT | `/chat/identities/{tool_id}` | `app.chat` | `update_identity_mapping` | oui | `back/app/chat/router.py:389` |
| GET | `/chat/inbox` | `app.chat` | `read_inbox` | oui | `back/app/chat/router.py:322` |
| GET | `/chat/push/configuration` | `app.chat` | `read_push_configuration` | oui | `back/app/chat/router.py:328` |
| DELETE | `/chat/push/subscriptions` | `app.chat` | `remove_push_subscription` | oui | `back/app/chat/router.py:351` |
| POST | `/chat/push/subscriptions` | `app.chat` | `create_push_subscription` | oui | `back/app/chat/router.py:338` |
| GET | `/chat/recipients` | `app.chat` | `read_recipients` | oui | `back/app/chat/router.py:417` |
| GET | `/chat/rooms` | `app.chat` | `read_rooms` | oui | `back/app/chat/router.py:466` |
| POST | `/chat/rooms` | `app.chat` | `create_room` | oui | `back/app/chat/router.py:490` |
| GET | `/chat/rooms/{room_id}` | `app.chat` | `read_room` | oui | `back/app/chat/router.py:518` |
| PATCH | `/chat/rooms/{room_id}` | `app.chat` | `update_room_preferences` | oui | `back/app/chat/router.py:535` |
| GET | `/chat/rooms/{room_id}/activity` | `app.chat` | `read_activity` | oui | `back/app/chat/router.py:902` |
| GET | `/chat/rooms/{room_id}/activity/{round_id}` | `app.chat` | `read_activity_detail` | oui | `back/app/chat/router.py:917` |
| PATCH | `/chat/rooms/{room_id}/archive` | `app.chat` | `update_room_archive` | oui | `back/app/chat/router.py:553` |
| POST | `/chat/rooms/{room_id}/attachments` | `app.chat` | `create_attachment_message` | oui | `back/app/chat/router.py:1134` |
| POST | `/chat/rooms/{room_id}/calls` | `app.chat` | `start_call` | oui | `back/app/chat/router.py:1290` |
| GET | `/chat/rooms/{room_id}/calls/active` | `app.chat` | `read_active_call` | oui | `back/app/chat/router.py:1349` |
| GET | `/chat/rooms/{room_id}/calls/status` | `app.chat` | `read_voice_call_status` | oui | `back/app/chat/router.py:1263` |
| DELETE | `/chat/rooms/{room_id}/calls/{call_id}` | `app.chat` | `stop_call` | oui | `back/app/chat/router.py:1408` |
| POST | `/chat/rooms/{room_id}/calls/{call_id}/candidates` | `app.chat` | `add_call_candidate` | oui | `back/app/chat/router.py:1373` |
| GET | `/chat/rooms/{room_id}/commands` | `app.chat` | `read_room_commands` | oui | `back/app/chat/router.py:594` |
| POST | `/chat/rooms/{room_id}/dictation` | `app.chat` | `transcribe_dictation` | oui | `back/app/chat/router.py:1083` |
| GET | `/chat/rooms/{room_id}/documents` | `app.chat` | `read_room_documents` | oui | `back/app/chat/router.py:955` |
| POST | `/chat/rooms/{room_id}/documents` | `app.chat` | `create_room_document` | oui | `back/app/chat/router.py:985` |
| GET | `/chat/rooms/{room_id}/files/{file_id}` | `app.chat` | `download_file` | oui | `back/app/chat/router.py:1220` |
| GET | `/chat/rooms/{room_id}/interactions/{interaction_id}` | `app.chat` | `read_interaction` | oui | `back/app/chat/router.py:1031` |
| POST | `/chat/rooms/{room_id}/interactions/{interaction_id}/answer` | `app.chat` | `answer_interaction` | oui | `back/app/chat/router.py:1040` |
| GET | `/chat/rooms/{room_id}/messages` | `app.chat` | `read_messages` | oui | `back/app/chat/router.py:608` |
| POST | `/chat/rooms/{room_id}/messages` | `app.chat` | `create_message` | oui | `back/app/chat/router.py:1056` |
| GET | `/chat/rooms/{room_id}/messages/{message_id}/previews` | `app.chat` | `read_message_previews` | oui | `back/app/chat/router.py:758` |
| GET | `/chat/rooms/{room_id}/messages/{message_id}/previews/content` | `app.chat` | `read_message_preview_content` | oui | `back/app/chat/router.py:862` |
| GET | `/chat/rooms/{room_id}/messages/{message_id}/previews/image` | `app.chat` | `read_message_preview_image` | oui | `back/app/chat/router.py:809` |
| POST | `/chat/rooms/{room_id}/messages/{message_id}/speech` | `app.chat` | `read_message_speech` | oui | `back/app/chat/router.py:659` |
| PATCH | `/chat/rooms/{room_id}/messages/{message_id}/topic` | `app.chat` | `update_message_topic` | oui | `back/app/chat/router.py:727` |
| POST | `/chat/rooms/{room_id}/mute` | `app.chat` | `set_muted` | oui | `back/app/chat/router.py:1212` |
| GET | `/chat/rooms/{room_id}/processes` | `app.chat` | `read_room_processes` | oui | `back/app/chat/router.py:1013` |
| POST | `/chat/rooms/{room_id}/read` | `app.chat` | `mark_read` | oui | `back/app/chat/router.py:1204` |
| GET | `/chat/rooms/{room_id}/speech/status` | `app.chat` | `read_message_speech_status` | oui | `back/app/chat/router.py:633` |
| GET | `/chat/rooms/{room_id}/tasks` | `app.chat` | `read_room_tasks` | oui | `back/app/chat/router.py:934` |
| PATCH | `/chat/rooms/{room_id}/topic` | `app.chat` | `update_room_topic` | oui | `back/app/chat/router.py:570` |
| GET | `/chat/status` | `app.chat` | `read_status` | oui | `back/app/chat/router.py:312` |
| GET | `/chat/viewer-agents` | `app.chat` | `read_viewer_agents` | oui | `back/app/chat/router.py:439` |
| GET | `/codex/runtime-credential` | `bridge.codex` | `runtime_credential` | non | `back/bridge/codex/router.py:31` |
| GET | `/connections` | `app.connection` | `list_connections` | oui | `back/app/connection/router.py:182` |
| POST | `/connections` | `app.connection` | `create_connection` | oui | `back/app/connection/router.py:213` |
| GET | `/connections/find-by-param` | `app.connection` | `find_agents_by_param` | oui | `back/app/connection/router.py:84` |
| POST | `/connections/refresh-tools` | `app.connection` | `refresh_connections_and_tool_catalogs` | oui | `back/app/connection/router.py:142` |
| POST | `/connections/sync-integrated` | `app.connection` | `sync_integrated_connections` | oui | `back/app/connection/router.py:154` |
| POST | `/connections/test-mcp-tools` | `app.connection` | `test_mcp_tools` | oui | `back/app/connection/router.py:450` |
| DELETE | `/connections/{connection_id}` | `app.connection` | `delete_connection` | oui | `back/app/connection/router.py:289` |
| GET | `/connections/{connection_id}` | `app.connection` | `get_connection` | oui | `back/app/connection/router.py:207` |
| PATCH | `/connections/{connection_id}` | `app.connection` | `update_connection` | oui | `back/app/connection/router.py:245` |
| GET | `/connections/{connection_id}/functions` | `app.connection` | `list_connection_functions` | oui | `back/app/connection/router.py:510` |
| PUT | `/connections/{connection_id}/functions/{function_name}` | `app.connection` | `set_connection_function` | oui | `back/app/connection/router.py:519` |
| PUT | `/connections/{connection_id}/functions/{function_name}/global` | `app.connection` | `set_connection_function_global` | oui | `back/app/connection/router.py:530` |
| GET | `/connections/{connection_id}/params` | `app.connection` | `get_connection_params` | oui | `back/app/connection/router.py:305` |
| POST | `/connections/{connection_id}/params` | `app.connection` | `create_or_update_param` | oui | `back/app/connection/router.py:352` |
| POST | `/connections/{connection_id}/params/bulk` | `app.connection` | `create_or_update_params_bulk` | oui | `back/app/connection/router.py:377` |
| DELETE | `/connections/{connection_id}/params/{param_name}` | `app.connection` | `delete_param` | oui | `back/app/connection/router.py:434` |
| GET | `/connections/{connection_id}/params/{param_name}` | `app.connection` | `get_single_param` | oui | `back/app/connection/router.py:325` |
| PATCH | `/connections/{connection_id}/params/{param_name}` | `app.connection` | `update_connection_param` | oui | `back/app/connection/router.py:402` |
| POST | `/console/connections/{connection_id}/generate-key` | `app.console` | `generate_connection_key` | oui | `back/app/console/router.py:84` |
| POST | `/console/connections/{connection_id}/install-helper` | `app.console` | `install_connection_galaris_exec` | oui | `back/app/console/router.py:113` |
| POST | `/console/connections/{connection_id}/test` | `app.console` | `test_connection` | oui | `back/app/console/router.py:95` |
| POST | `/console/embedded/provision` | `app.console` | `provision_embedded` | oui | `back/app/console/router.py:131` |
| POST | `/console/executor/action` | `app.console` | `executor_action` | oui | `back/app/console/router.py:177` |
| GET | `/console/executor/availability` | `app.console` | `executor_availability` | oui | `back/app/console/router.py:160` |
| GET | `/console/executor/status` | `app.console` | `executor_status` | oui | `back/app/console/router.py:166` |
| POST | `/console/host-key/scan` | `app.console` | `scan_host_key` | oui | `back/app/console/router.py:65` |
| GET | `/contacts` | `app.contact` | `read_contacts` | oui | `back/app/contact/router.py:44` |
| DELETE | `/contacts/{contact_item_id}` | `app.contact` | `forget_contact` | oui | `back/app/contact/router.py:80` |
| POST | `/contacts/{source_contact_item_id}/merge` | `app.contact` | `merge_contacts` | oui | `back/app/contact/router.py:61` |
| GET | `/conversations/messages` | `app.conversation` | `read_conversation_messages` | oui | `back/app/conversation/router.py:30` |
| DELETE | `/conversations/rounds/{round_id}` | `app.conversation` | `delete_conversation_round` | oui | `back/app/conversation/router.py:139` |
| GET | `/conversations/rounds/{round_id}` | `app.conversation` | `read_conversation_round` | oui | `back/app/conversation/router.py:73` |
| GET | `/conversations/rounds/{round_id}/dataset` | `app.conversation` | `export_conversation_round` | oui | `back/app/conversation/router.py:101` |
| POST | `/conversations/rounds/{round_id}/delivery-resolution` | `app.conversation` | `resolve_conversation_delivery` | oui | `back/app/conversation/router.py:114` |
| PUT | `/conversations/rounds/{round_id}/topic` | `app.conversation` | `update_conversation_round_topic` | oui | `back/app/conversation/router.py:79` |
| GET | `/dashboard` | `app.dashboard` | `read_dashboard` | oui | `back/app/dashboard/router.py:17` |
| GET | `/definitions` | `app.process` | `read_definitions` | oui | `back/app/process/router.py:125` |
| POST | `/definitions` | `app.process` | `create_definition` | oui | `back/app/process/router.py:138` |
| POST | `/definitions/sync` | `app.process` | `sync_definitions` | oui | `back/app/process/router.py:149` |
| DELETE | `/definitions/{process_id}` | `app.process` | `delete_definition` | oui | `back/app/process/router.py:183` |
| GET | `/definitions/{process_id}` | `app.process` | `read_definition` | oui | `back/app/process/router.py:161` |
| PUT | `/definitions/{process_id}` | `app.process` | `update_definition` | oui | `back/app/process/router.py:167` |
| GET | `/dream/overview` | `app.dream` | `read_dream_overview` | oui | `back/app/dream/router.py:46` |
| GET | `/dream/receipts` | `app.dream` | `read_dream_receipts` | oui | `back/app/dream/router.py:53` |
| GET | `/dream/receipts/{receipt_id}` | `app.dream` | `read_dream_receipt` | oui | `back/app/dream/router.py:109` |
| GET | `/dream/runtime` | `app.dream` | `read_dream_runtime` | oui | `back/app/dream/router.py:39` |
| GET | `/dream/topic-assignment` | `app.dream` | `read_topic_assignment` | oui | `back/app/dream/router.py:85` |
| GET | `/evaluation/candidates` | `app.lab` | `read_candidates` | oui | `back/app/lab/router.py:189` |
| GET | `/evaluation/config` | `app.lab` | `read_config` | oui | `back/app/lab/router.py:183` |
| GET | `/evaluation/dispatcher/candidates` | `app.lab` | `read_dispatcher_candidates` | oui | `back/app/lab/router.py:351` |
| DELETE | `/evaluation/dispatcher/cases/{case_id}` | `app.lab` | `delete_dispatcher_case` | oui | `back/app/lab/router.py:396` |
| PATCH | `/evaluation/dispatcher/cases/{case_id}` | `app.lab` | `update_dispatcher_case` | oui | `back/app/lab/router.py:385` |
| POST | `/evaluation/dispatcher/cases/{case_id}/duplicate` | `app.lab` | `duplicate_dispatcher_case` | oui | `back/app/lab/router.py:407` |
| POST | `/evaluation/dispatcher/cases/{case_id}/generate-expected` | `app.lab` | `generate_dispatcher_expected` | oui | `back/app/lab/router.py:436` |
| POST | `/evaluation/dispatcher/cases/{case_id}/restore-source` | `app.lab` | `restore_dispatcher_case` | oui | `back/app/lab/router.py:416` |
| GET | `/evaluation/dispatcher/datasets` | `app.lab` | `read_dispatcher_datasets` | oui | `back/app/lab/router.py:269` |
| POST | `/evaluation/dispatcher/datasets` | `app.lab` | `create_dispatcher_dataset` | oui | `back/app/lab/router.py:279` |
| DELETE | `/evaluation/dispatcher/datasets/{dataset_id}` | `app.lab` | `delete_dispatcher_dataset` | oui | `back/app/lab/router.py:318` |
| PATCH | `/evaluation/dispatcher/datasets/{dataset_id}` | `app.lab` | `update_dispatcher_dataset` | oui | `back/app/lab/router.py:287` |
| GET | `/evaluation/dispatcher/datasets/{dataset_id}/cases` | `app.lab` | `read_dispatcher_cases` | oui | `back/app/lab/router.py:325` |
| POST | `/evaluation/dispatcher/datasets/{dataset_id}/cases` | `app.lab` | `create_dispatcher_case` | oui | `back/app/lab/router.py:338` |
| POST | `/evaluation/dispatcher/datasets/{dataset_id}/cases/from-task` | `app.lab` | `import_dispatcher_case` | oui | `back/app/lab/router.py:369` |
| GET | `/evaluation/dispatcher/datasets/{dataset_id}/runs` | `app.lab` | `read_dispatcher_runs` | oui | `back/app/lab/router.py:464` |
| POST | `/evaluation/dispatcher/datasets/{dataset_id}/runs` | `app.lab` | `start_dispatcher_run` | oui | `back/app/lab/router.py:453` |
| GET | `/evaluation/dispatcher/runs/{run_id}` | `app.lab` | `read_dispatcher_run` | oui | `back/app/lab/router.py:476` |
| POST | `/evaluation/dispatcher/runs/{run_id}/analyze` | `app.lab` | `analyze_dispatcher_run` | oui | `back/app/lab/router.py:485` |
| POST | `/evaluation/dispatcher/runs/{run_id}/cancel` | `app.lab` | `cancel_dispatcher_run` | oui | `back/app/lab/router.py:498` |
| GET | `/evaluation/executor-prompts/defaults` | `app.lab` | `read_executor_prompt_defaults` | oui | `back/app/lab/router.py:513` |
| GET | `/evaluation/mechanisms` | `app.lab` | `read_mechanisms` | oui | `back/app/lab/router.py:519` |
| PATCH | `/evaluation/memory_extraction/datasets/{dataset_id}/configuration` | `app.lab` | `update_memory_extraction_dataset_configuration` | oui | `back/app/lab/router.py:620` |
| GET | `/evaluation/memory_extraction/prompt-default` | `app.lab` | `read_memory_extraction_prompt_default` | oui | `back/app/lab/router.py:303` |
| PATCH | `/evaluation/planner/datasets/{dataset_id}/configuration` | `app.lab` | `update_planner_dataset_configuration` | oui | `back/app/lab/router.py:639` |
| GET | `/evaluation/planner/prompt-default` | `app.lab` | `read_planner_prompt_default` | oui | `back/app/lab/router.py:312` |
| GET | `/evaluation/tasks` | `app.lab` | `read_lab_tasks` | oui | `back/app/lab/router.py:203` |
| POST | `/evaluation/tasks` | `app.lab` | `add_lab_task` | oui | `back/app/lab/router.py:214` |
| DELETE | `/evaluation/tasks/{task_id}` | `app.lab` | `remove_lab_task` | oui | `back/app/lab/router.py:229` |
| POST | `/evaluation/tasks/{task_id}/analyze` | `app.lab` | `analyze_task` | oui | `back/app/lab/router.py:253` |
| GET | `/evaluation/tasks/{task_id}/diagnoses` | `app.lab` | `read_task_diagnoses` | oui | `back/app/lab/router.py:240` |
| POST | `/evaluation/topic-classification/datasets/{dataset_id}/cases/from-message-range` | `app.lab` | `import_topic_messages` | oui | `back/app/lab/router.py:582` |
| PATCH | `/evaluation/topic-classification/datasets/{dataset_id}/configuration` | `app.lab` | `update_topic_dataset_configuration` | oui | `back/app/lab/router.py:601` |
| GET | `/evaluation/topic-classification/message-agents` | `app.lab` | `read_topic_message_agents` | oui | `back/app/lab/router.py:528` |
| GET | `/evaluation/topic-classification/message-people` | `app.lab` | `read_topic_message_people` | oui | `back/app/lab/router.py:538` |
| GET | `/evaluation/topic-classification/message-preview` | `app.lab` | `preview_topic_messages` | oui | `back/app/lab/router.py:552` |
| GET | `/evaluation/{mechanism}/candidates` | `app.lab` | `read_mechanism_candidates` | oui | `back/app/lab/router.py:751` |
| DELETE | `/evaluation/{mechanism}/cases/{case_id}` | `app.lab` | `delete_mechanism_case` | oui | `back/app/lab/router.py:873` |
| PATCH | `/evaluation/{mechanism}/cases/{case_id}` | `app.lab` | `update_mechanism_case` | oui | `back/app/lab/router.py:855` |
| POST | `/evaluation/{mechanism}/cases/{case_id}/duplicate` | `app.lab` | `duplicate_mechanism_case` | oui | `back/app/lab/router.py:887` |
| POST | `/evaluation/{mechanism}/cases/{case_id}/generate-expected` | `app.lab` | `generate_mechanism_expected` | oui | `back/app/lab/router.py:929` |
| POST | `/evaluation/{mechanism}/cases/{case_id}/restore-source` | `app.lab` | `restore_mechanism_case` | oui | `back/app/lab/router.py:904` |
| GET | `/evaluation/{mechanism}/datasets` | `app.lab` | `read_mechanism_datasets` | oui | `back/app/lab/router.py:658` |
| POST | `/evaluation/{mechanism}/datasets` | `app.lab` | `create_mechanism_dataset` | oui | `back/app/lab/router.py:673` |
| POST | `/evaluation/{mechanism}/datasets/synthetic` | `app.lab` | `generate_synthetic_dataset` | oui | `back/app/lab/router.py:89` |
| DELETE | `/evaluation/{mechanism}/datasets/{dataset_id}` | `app.lab` | `delete_mechanism_dataset` | oui | `back/app/lab/router.py:702` |
| PATCH | `/evaluation/{mechanism}/datasets/{dataset_id}` | `app.lab` | `update_mechanism_dataset` | oui | `back/app/lab/router.py:684` |
| GET | `/evaluation/{mechanism}/datasets/{dataset_id}/cases` | `app.lab` | `read_mechanism_cases` | oui | `back/app/lab/router.py:715` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/cases` | `app.lab` | `create_mechanism_case` | oui | `back/app/lab/router.py:733` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/cases/from-execution` | `app.lab` | `import_executor_execution_case` | oui | `back/app/lab/router.py:829` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/cases/from-source` | `app.lab` | `import_mechanism_case` | oui | `back/app/lab/router.py:774` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/cases/from-task` | `app.lab` | `import_mechanism_task_case` | oui | `back/app/lab/router.py:804` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/preview` | `app.lab` | `preview_lab_input` | oui | `back/app/lab/router.py:130` |
| GET | `/evaluation/{mechanism}/datasets/{dataset_id}/runs` | `app.lab` | `read_mechanism_runs` | oui | `back/app/lab/router.py:972` |
| POST | `/evaluation/{mechanism}/datasets/{dataset_id}/runs` | `app.lab` | `start_mechanism_run` | oui | `back/app/lab/router.py:951` |
| DELETE | `/evaluation/{mechanism}/runs/{run_id}` | `app.lab` | `delete_mechanism_run` | oui | `back/app/lab/router.py:1000` |
| GET | `/evaluation/{mechanism}/runs/{run_id}` | `app.lab` | `read_mechanism_run` | oui | `back/app/lab/router.py:988` |
| POST | `/evaluation/{mechanism}/runs/{run_id}/analyze` | `app.lab` | `analyze_mechanism_run` | oui | `back/app/lab/router.py:1014` |
| POST | `/evaluation/{mechanism}/runs/{run_id}/cancel` | `app.lab` | `cancel_mechanism_run` | oui | `back/app/lab/router.py:1032` |
| GET | `/evaluation/{mechanism}/runs/{run_id}/human-review` | `app.lab` | `read_human_review` | oui | `back/app/lab/router.py:104` |
| POST | `/evaluation/{mechanism}/runs/{run_id}/human-review` | `app.lab` | `submit_human_review` | oui | `back/app/lab/router.py:117` |
| POST | `/evaluation/{mechanism}/runs/{run_id}/rejudge` | `app.lab` | `rejudge_benchmark` | oui | `back/app/lab/router.py:143` |
| POST | `/evaluation/{mechanism}/runs/{run_id}/resume` | `app.lab` | `resume_benchmark` | oui | `back/app/lab/router.py:156` |
| GET | `/file-share/bridges` | `app.file_share` | `list_bridges` | oui | `back/app/file_share/router.py:14` |
| GET | `/goals` | `app.goal` | `read_goals` | oui | `back/app/goal/router.py:84` |
| POST | `/goals` | `app.goal` | `create_goal` | oui | `back/app/goal/router.py:174` |
| GET | `/goals/referrers/messenger` | `app.goal` | `search_messenger_referrers` | oui | `back/app/goal/router.py:104` |
| GET | `/goals/settings` | `app.goal` | `read_goal_settings` | oui | `back/app/goal/router.py:119` |
| PATCH | `/goals/settings` | `app.goal` | `update_goal_settings` | oui | `back/app/goal/router.py:125` |
| GET | `/goals/tree` | `app.goal` | `read_goal_tree` | oui | `back/app/goal/router.py:142` |
| DELETE | `/goals/{goal_id}` | `app.goal` | `delete_goal` | oui | `back/app/goal/router.py:261` |
| GET | `/goals/{goal_id}` | `app.goal` | `read_goal` | oui | `back/app/goal/router.py:149` |
| PUT | `/goals/{goal_id}` | `app.goal` | `update_goal` | oui | `back/app/goal/router.py:188` |
| POST | `/goals/{goal_id}/complete` | `app.goal` | `complete_goal` | oui | `back/app/goal/router.py:235` |
| GET | `/goals/{goal_id}/cycles` | `app.goal` | `read_goal_cycles` | oui | `back/app/goal/router.py:156` |
| POST | `/goals/{goal_id}/pause` | `app.goal` | `pause_goal` | oui | `back/app/goal/router.py:209` |
| POST | `/goals/{goal_id}/resume` | `app.goal` | `resume_goal` | oui | `back/app/goal/router.py:222` |
| POST | `/goals/{goal_id}/run-now` | `app.goal` | `run_goal_now` | oui | `back/app/goal/router.py:248` |
| GET | `/harness-manager/configuration` | `bridge.harness` | `read_configuration` | oui | `back/bridge/harness/router.py:27` |
| PUT | `/harness-manager/configuration` | `bridge.harness` | `update_configuration` | oui | `back/bridge/harness/router.py:33` |
| GET | `/harness-manager/diagnostics` | `bridge.harness` | `manager_diagnostics` | oui | `back/bridge/harness/router.py:21` |
| POST | `/harness-manager/environment` | `bridge.harness` | `manager_environment` | oui | `back/bridge/harness/router.py:46` |
| POST | `/harness-manager/generate-secret` | `bridge.harness` | `generate_secret` | oui | `back/bridge/harness/router.py:39` |
| POST | `/harness-manager/installation.zip` | `bridge.harness` | `installation_archive` | oui | `back/bridge/harness/router.py:84` |
| GET | `/harness-manager/release` | `bridge.harness` | `release_manifest` | oui | `back/bridge/harness/router.py:72` |
| GET | `/harness-manager/release.zip` | `bridge.harness` | `release_archive` | oui | `back/bridge/harness/router.py:78` |
| GET | `/harness-manager/updates/archive/{digest}.zip` | `bridge.harness` | `update_archive` | non | `back/bridge/harness/router.py:113` |
| GET | `/harness-manager/updates/manifest` | `bridge.harness` | `update_manifest` | non | `back/bridge/harness/router.py:105` |
| DELETE | `/harnesses/agents/{id}` | `app.harnesses` | `select_internal_harness` | oui | `back/app/harnesses/router.py:234` |
| GET | `/harnesses/agents/{id}` | `app.harnesses` | `read_agent_harness` | oui | `back/app/harnesses/router.py:201` |
| PUT | `/harnesses/agents/{id}` | `app.harnesses` | `install_agent_harness` | oui | `back/app/harnesses/router.py:214` |
| POST | `/harnesses/agents/{id}/actions/{action}` | `app.harness` | `run_harness_action` | oui | `back/app/harness/router.py:60` |
| POST | `/harnesses/agents/{id}/actions/{action}` | `app.harnesses` | `run_harness_action` | oui | `back/app/harnesses/router.py:338` |
| GET | `/harnesses/agents/{id}/logs` | `app.harness` | `harness_logs` | oui | `back/app/harness/router.py:74` |
| GET | `/harnesses/agents/{id}/logs` | `app.harnesses` | `harness_logs` | oui | `back/app/harnesses/router.py:367` |
| POST | `/harnesses/agents/{id}/refresh` | `app.harness` | `refresh_harness` | oui | `back/app/harness/router.py:84` |
| GET | `/harnesses/agents/{id}/status` | `app.harness` | `harness_status` | oui | `back/app/harness/router.py:46` |
| GET | `/harnesses/agents/{id}/status` | `app.harnesses` | `harness_status` | oui | `back/app/harnesses/router.py:283` |
| GET | `/harnesses/agents/{id}/task-blockers` | `app.harnesses` | `harness_task_blockers` | oui | `back/app/harnesses/router.py:252` |
| POST | `/harnesses/agents/{id}/task-blockers/terminate-paused` | `app.harnesses` | `terminate_harness_paused_tasks` | oui | `back/app/harnesses/router.py:261` |
| GET | `/harnesses/catalog` | `app.harnesses` | `list_harness_catalogue` | oui | `back/app/harnesses/router.py:120` |
| POST | `/harnesses/catalog` | `app.harnesses` | `create_harness` | oui | `back/app/harnesses/router.py:132` |
| POST | `/harnesses/catalog/probe` | `app.harnesses` | `probe_harness` | oui | `back/app/harnesses/router.py:141` |
| DELETE | `/harnesses/catalog/{harness_id}` | `app.harnesses` | `delete_harness` | oui | `back/app/harnesses/router.py:182` |
| GET | `/harnesses/catalog/{harness_id}` | `app.harnesses` | `read_harness` | oui | `back/app/harnesses/router.py:150` |
| PUT | `/harnesses/catalog/{harness_id}` | `app.harnesses` | `update_harness` | oui | `back/app/harnesses/router.py:163` |
| GET | `/harnesses/execution-configurations` | `app.harnesses` | `read_execution_configurations` | oui | `back/app/harnesses/router.py:50` |
| PUT | `/harnesses/execution-configurations/{provider_code}` | `app.harnesses` | `save_execution_configuration` | oui | `back/app/harnesses/router.py:56` |
| GET | `/harnesses/providers` | `app.harnesses` | `list_harness_providers` | oui | `back/app/harnesses/router.py:97` |
| GET | `/healthz` | `bridge.codex` | `health` | non | `back/bridge/codex/default-agent/server.py:184` |
| GET | `/hermes/agents` | `bridge.hermes` | `hermes_list_agents` | oui | `back/bridge/hermes/router.py:115` |
| GET | `/hermes/configurations` | `bridge.hermes` | `list_hermes_configurations` | oui | `back/bridge/hermes/router.py:67` |
| PUT | `/hermes/configurations/{id}` | `bridge.hermes` | `update_hermes_configuration` | oui | `back/bridge/hermes/router.py:85` |
| GET | `/hermes/reachable` | `bridge.hermes` | `hermes_reachable` | oui | `back/bridge/hermes/router.py:104` |
| GET | `/incidents` | `app.incident` | `read_incidents` | oui | `back/app/incident/router.py:77` |
| DELETE | `/incidents/cleanup` | `app.incident` | `cleanup_incidents` | oui | `back/app/incident/router.py:143` |
| GET | `/incidents/patterns` | `app.incident` | `read_patterns` | oui | `back/app/incident/router.py:103` |
| PATCH | `/incidents/patterns/{pattern_id}` | `app.incident` | `patch_pattern` | oui | `back/app/incident/router.py:171` |
| GET | `/incidents/recent` | `app.incident` | `read_recent_incidents` | oui | `back/app/incident/router.py:127` |
| GET | `/incidents/{incident_id}` | `app.incident` | `read_incident` | oui | `back/app/incident/router.py:152` |
| POST | `/janus/openai/chat/completions` | `app.agent` | `janus_chat_completions` | oui | `back/app/agent/openai_router.py:179` |
| GET | `/janus/openai/models` | `app.agent` | `get_janus_models` | oui | `back/app/agent/openai_router.py:163` |
| GET | `/llm-calls` | `app.llm` | `read_calls` | oui | `back/app/llm/call_router.py:415` |
| DELETE | `/llm-calls/cleanup` | `app.llm` | `cleanup_calls` | oui | `back/app/llm/call_router.py:485` |
| GET | `/llm-calls/history` | `app.llm` | `read_call_history` | oui | `back/app/llm/call_router.py:458` |
| GET | `/llm-calls/retention/preview` | `app.llm` | `preview_call_retention` | oui | `back/app/llm/call_router.py:494` |
| GET | `/llm-calls/running` | `app.llm` | `read_running_calls` | oui | `back/app/llm/call_router.py:440` |
| DELETE | `/llm-calls/{call_id}` | `app.llm` | `delete_call` | oui | `back/app/llm/call_router.py:503` |
| GET | `/llm-calls/{call_id}` | `app.llm` | `read_call` | oui | `back/app/llm/call_router.py:522` |
| GET | `/llm-profiles` | `app.llm` | `list_profiles` | oui | `back/app/llm/profile_router.py:67` |
| POST | `/llm-profiles` | `app.llm` | `create_profile` | oui | `back/app/llm/profile_router.py:88` |
| DELETE | `/llm-profiles/{profile_id}` | `app.llm` | `delete_profile` | oui | `back/app/llm/profile_router.py:119` |
| GET | `/llm-profiles/{profile_id}` | `app.llm` | `get_profile` | oui | `back/app/llm/profile_router.py:78` |
| PUT | `/llm-profiles/{profile_id}` | `app.llm` | `update_profile` | oui | `back/app/llm/profile_router.py:100` |
| POST | `/llm-profiles/{profile_id}/use` | `app.llm` | `use_profile` | oui | `back/app/llm/profile_router.py:134` |
| GET | `/llm-providers` | `app.llm` | `list_providers` | oui | `back/app/llm/provider_router.py:257` |
| POST | `/llm-providers` | `app.llm` | `create_provider` | oui | `back/app/llm/provider_router.py:265` |
| GET | `/llm-providers/catalog` | `app.llm` | `get_provider_catalog` | oui | `back/app/llm/provider_router.py:279` |
| PUT | `/llm-providers/catalog/{catalog_code}` | `app.llm` | `configure_catalog_provider` | oui | `back/app/llm/provider_router.py:320` |
| GET | `/llm-providers/catalog/{catalog_code}/resources` | `app.llm` | `list_catalog_resources` | oui | `back/app/llm/provider_router.py:286` |
| POST | `/llm-providers/fetch-pricing` | `app.llm` | `fetch_pricing` | oui | `back/app/llm/provider_router.py:150` |
| GET | `/llm-providers/llms` | `app.llm` | `list_llms` | oui | `back/app/llm/provider_router.py:111` |
| POST | `/llm-providers/llms` | `app.llm` | `create_llm` | oui | `back/app/llm/provider_router.py:123` |
| DELETE | `/llm-providers/llms/{llm_id}` | `app.llm` | `delete_llm` | oui | `back/app/llm/provider_router.py:238` |
| GET | `/llm-providers/llms/{llm_id}` | `app.llm` | `get_llm` | oui | `back/app/llm/provider_router.py:190` |
| PUT | `/llm-providers/llms/{llm_id}` | `app.llm` | `update_llm` | oui | `back/app/llm/provider_router.py:205` |
| POST | `/llm-providers/test` | `app.llm` | `test_provider_connection` | oui | `back/app/llm/provider_router.py:337` |
| DELETE | `/llm-providers/{provider_id}` | `app.llm` | `delete_provider` | oui | `back/app/llm/provider_router.py:531` |
| GET | `/llm-providers/{provider_id}` | `app.llm` | `get_provider` | oui | `back/app/llm/provider_router.py:488` |
| PUT | `/llm-providers/{provider_id}` | `app.llm` | `update_provider` | oui | `back/app/llm/provider_router.py:507` |
| GET | `/llm-providers/{provider_id}/models` | `app.llm` | `list_provider_models` | oui | `back/app/llm/provider_router.py:546` |
| POST | `/llm-providers/{provider_id}/models/delete` | `app.llm` | `delete_model` | oui | `back/app/llm/provider_router.py:720` |
| POST | `/llm-providers/{provider_id}/models/pull` | `app.llm` | `pull_model` | oui | `back/app/llm/provider_router.py:681` |
| DELETE | `/llm-providers/{provider_id}/oauth` | `app.llm` | `disconnect_provider_authentication` | oui | `back/app/llm/provider_router.py:454` |
| POST | `/llm-providers/{provider_id}/oauth/device` | `app.llm` | `start_provider_device_login` | oui | `back/app/llm/provider_router.py:392` |
| POST | `/llm-providers/{provider_id}/oauth/device/poll` | `app.llm` | `poll_provider_device_login` | oui | `back/app/llm/provider_router.py:422` |
| GET | `/llm-providers/{provider_id}/quota` | `app.llm` | `get_provider_quota` | oui | `back/app/llm/provider_router.py:473` |
| GET | `/llm-providers/{provider_id}/resources` | `app.llm` | `list_provider_resources` | oui | `back/app/llm/provider_router.py:598` |
| GET | `/llm-providers/{provider_id}/transcription-models` | `app.llm` | `list_provider_transcription_models` | oui | `back/app/llm/provider_router.py:644` |
| POST | `/llm/anthropic/v1/messages` | `app.llm` | `anthropic_messages` | non | `back/app/llm/anthropic_router.py:228` |
| POST | `/llm/anthropic/v1/messages/count_tokens` | `app.llm` | `anthropic_count_tokens` | non | `back/app/llm/anthropic_router.py:202` |
| GET | `/llm/anthropic/v1/models` | `app.llm` | `anthropic_models` | non | `back/app/llm/anthropic_router.py:176` |
| GET | `/llm/me/options` | `app.llm` | `get_options` | oui | `back/app/llm/personal_router.py:56` |
| GET | `/llm/me/preferences` | `app.llm` | `get_preferences` | oui | `back/app/llm/personal_router.py:41` |
| PUT | `/llm/me/preferences` | `app.llm` | `put_preferences` | oui | `back/app/llm/personal_router.py:47` |
| POST | `/llm/me/speech` | `app.llm` | `speech` | oui | `back/app/llm/personal_router.py:122` |
| POST | `/llm/me/transcription` | `app.llm` | `transcribe` | oui | `back/app/llm/personal_router.py:85` |
| POST | `/llm/openai/chat/completions` | `app.llm` | `llm_completion` | non | `back/app/llm/call_router.py:189` |
| POST | `/llm/openai/inferences` | `app.llm` | `create_inference` | non | `back/app/llm/call_router.py:106` |
| GET | `/llm/openai/inferences/{inference_id}` | `app.llm` | `get_inference` | non | `back/app/llm/call_router.py:130` |
| POST | `/llm/openai/inferences/{inference_id}/commands` | `app.llm` | `command_inference` | non | `back/app/llm/call_router.py:136` |
| GET | `/llm/openai/inferences/{inference_id}/events` | `app.llm` | `inference_events` | non | `back/app/llm/call_router.py:150` |
| GET | `/llm/openai/models` | `app.llm` | `llm_models` | non | `back/app/llm/call_router.py:172` |
| POST | `/llm/openai/responses` | `app.llm` | `llm_responses` | non | `back/app/llm/call_router.py:306` |
| POST | `/llm/openai/responses/compact` | `app.llm` | `llm_responses` | non | `back/app/llm/call_router.py:306` |
| GET | `/llm/openai/runs/{agent_run_id}/usage` | `app.llm` | `llm_run_usage` | non | `back/app/llm/call_router.py:397` |
| GET | `/llm/users/{user_id}/preferences` | `app.llm` | `get_user_preferences` | oui | `back/app/llm/personal_router.py:68` |
| PUT | `/llm/users/{user_id}/preferences` | `app.llm` | `put_user_preferences` | oui | `back/app/llm/personal_router.py:75` |
| GET | `/mail/approvers` | `bridge.mail` | `list_mail_approvers` | oui | `back/bridge/mail/router.py:100` |
| POST | `/mail/connections/{connection_id}/test` | `bridge.mail` | `test_connection` | oui | `back/bridge/mail/router.py:167` |
| GET | `/mail/outbound` | `bridge.mail` | `list_outbound_mail` | oui | `back/bridge/mail/router.py:64` |
| GET | `/mail/outbound/agents` | `bridge.mail` | `list_outbound_mail_agents` | oui | `back/bridge/mail/router.py:87` |
| GET | `/mail/outbound/{delivery_id}` | `bridge.mail` | `read_outbound_mail` | oui | `back/bridge/mail/router.py:106` |
| POST | `/mail/outbound/{delivery_id}/approve` | `bridge.mail` | `approve_outbound_mail` | oui | `back/bridge/mail/router.py:123` |
| POST | `/mail/outbound/{delivery_id}/reject` | `bridge.mail` | `reject_outbound_mail` | oui | `back/bridge/mail/router.py:145` |
| GET | `/mail/status` | `bridge.mail` | `read_mail_status` | oui | `back/bridge/mail/router.py:53` |
| POST | `/memory/browse` | `app.memory` | `browse_memory` | oui | `back/app/memory/router.py:435` |
| POST | `/memory/documents` | `app.memory` | `create_managed_document` | oui | `back/app/memory/router.py:237` |
| GET | `/memory/documents/folders` | `app.memory` | `read_document_folders` | oui | `back/app/memory/router.py:790` |
| POST | `/memory/documents/icons/resolve` | `app.memory` | `resolve_document_icons` | oui | `back/app/memory/router.py:673` |
| GET | `/memory/documents/keywords` | `app.memory` | `read_document_keywords` | oui | `back/app/memory/router.py:637` |
| POST | `/memory/documents/library` | `app.memory` | `browse_managed_documents` | oui | `back/app/memory/router.py:656` |
| PUT | `/memory/documents/order` | `app.memory` | `reorder_personal_documents` | oui | `back/app/memory/router.py:692` |
| PUT | `/memory/documents/order/sort` | `app.memory` | `sort_personal_documents` | oui | `back/app/memory/router.py:703` |
| GET | `/memory/documents/owner-options` | `app.memory` | `read_document_owner_options` | oui | `back/app/memory/router.py:806` |
| GET | `/memory/documents/tag-icons` | `app.memory` | `read_personal_tag_icons` | oui | `back/app/memory/router.py:714` |
| POST | `/memory/documents/tag-icons` | `app.memory` | `upload_personal_tag_icon` | oui | `back/app/memory/router.py:720` |
| GET | `/memory/documents/tags` | `app.memory` | `read_personal_document_tags` | oui | `back/app/memory/router.py:738` |
| POST | `/memory/documents/tags` | `app.memory` | `create_personal_document_tag` | oui | `back/app/memory/router.py:745` |
| DELETE | `/memory/documents/tags/{tag_id}` | `app.memory` | `delete_personal_document_tag` | oui | `back/app/memory/router.py:763` |
| PUT | `/memory/documents/tags/{tag_id}` | `app.memory` | `update_personal_document_tag` | oui | `back/app/memory/router.py:754` |
| GET | `/memory/documents/{document_id}` | `app.memory` | `read_managed_document` | oui | `back/app/memory/router.py:1031` |
| PATCH | `/memory/documents/{document_id}` | `app.memory` | `update_human_document` | oui | `back/app/memory/router.py:1046` |
| GET | `/memory/documents/{document_id}/app-permissions` | `app.memory` | `read_app_permissions` | oui | `back/app/memory/router.py:117` |
| PUT | `/memory/documents/{document_id}/app-permissions/{app_key}/{alias}` | `app.memory` | `update_app_permission` | oui | `back/app/memory/router.py:126` |
| POST | `/memory/documents/{document_id}/apps/{app_id}/datasets/{alias}` | `app.memory` | `access_app_dataset` | oui | `back/app/memory/router.py:138` |
| GET | `/memory/documents/{document_id}/attachments` | `app.memory` | `list_document_attachments` | oui | `back/app/memory/router.py:1282` |
| POST | `/memory/documents/{document_id}/attachments` | `app.memory` | `add_document_attachment` | oui | `back/app/memory/router.py:1302` |
| DELETE | `/memory/documents/{document_id}/attachments/{attachment_id}` | `app.memory` | `delete_document_attachment` | oui | `back/app/memory/router.py:1405` |
| GET | `/memory/documents/{document_id}/attachments/{attachment_id}` | `app.memory` | `read_document_attachment` | oui | `back/app/memory/router.py:1374` |
| GET | `/memory/documents/{document_id}/attachments/{attachment_id}/info` | `app.memory` | `read_document_attachment_info` | oui | `back/app/memory/router.py:1356` |
| GET | `/memory/documents/{document_id}/attachments/{attachment_id}/thumbnail` | `app.memory` | `read_document_attachment_thumbnail` | oui | `back/app/memory/router.py:1323` |
| DELETE | `/memory/documents/{document_id}/collaborators/{agent_id}` | `app.memory` | `remove_managed_document_grant` | oui | `back/app/memory/router.py:1251` |
| PUT | `/memory/documents/{document_id}/collaborators/{agent_id}` | `app.memory` | `set_managed_document_grant` | oui | `back/app/memory/router.py:1217` |
| GET | `/memory/documents/{document_id}/content-revisions` | `app.memory` | `list_managed_document_content_revisions` | oui | `back/app/memory/router.py:854` |
| GET | `/memory/documents/{document_id}/content-revisions/{revision}` | `app.memory` | `read_managed_document_content_revision` | oui | `back/app/memory/router.py:881` |
| GET | `/memory/documents/{document_id}/content-revisions/{revision}/diff` | `app.memory` | `diff_managed_document_content_revision` | oui | `back/app/memory/router.py:906` |
| POST | `/memory/documents/{document_id}/content-revisions/{revision}/restore` | `app.memory` | `restore_managed_document_content_revision` | oui | `back/app/memory/router.py:931` |
| POST | `/memory/documents/{document_id}/export-bundle` | `app.memory` | `export_document_bundle` | oui | `back/app/memory/router.py:970` |
| POST | `/memory/documents/{document_id}/export-pdf` | `app.memory` | `export_managed_document_pdf` | oui | `back/app/memory/router.py:984` |
| PATCH | `/memory/documents/{document_id}/folder` | `app.memory` | `move_managed_document` | oui | `back/app/memory/router.py:1088` |
| PATCH | `/memory/documents/{document_id}/global-access` | `app.memory` | `set_managed_document_global_access` | oui | `back/app/memory/router.py:1188` |
| DELETE | `/memory/documents/{document_id}/grants/{agent_id}` | `app.memory` | `remove_document_grant` | oui | `back/app/memory/router.py:1464` |
| PUT | `/memory/documents/{document_id}/grants/{agent_id}` | `app.memory` | `set_document_grant` | oui | `back/app/memory/router.py:1431` |
| PUT | `/memory/documents/{document_id}/icon` | `app.memory` | `save_document_icon` | oui | `back/app/memory/router.py:681` |
| POST | `/memory/documents/{document_id}/link-card` | `app.memory` | `create_document_link_card` | oui | `back/app/memory/router.py:959` |
| PATCH | `/memory/documents/{document_id}/owner` | `app.memory` | `change_document_owner` | oui | `back/app/memory/router.py:1125` |
| GET | `/memory/documents/{document_id}/sharing` | `app.memory` | `read_document_sharing` | oui | `back/app/memory/router.py:1058` |
| PUT | `/memory/documents/{document_id}/sharing` | `app.memory` | `update_document_sharing` | oui | `back/app/memory/router.py:1067` |
| PUT | `/memory/documents/{document_id}/sharing-level` | `app.memory` | `update_document_sharing_level` | oui | `back/app/memory/router.py:1076` |
| PUT | `/memory/documents/{document_id}/tags` | `app.memory` | `move_personal_document` | oui | `back/app/memory/router.py:729` |
| DELETE | `/memory/documents/{document_id}/tags/{tag_id}` | `app.memory` | `remove_personal_document_tag` | oui | `back/app/memory/router.py:781` |
| PUT | `/memory/documents/{document_id}/tags/{tag_id}` | `app.memory` | `add_personal_document_tag` | oui | `back/app/memory/router.py:772` |
| POST | `/memory/documents/{document_id}/thumbnail` | `app.memory` | `read_document_thumbnail` | oui | `back/app/memory/router.py:1002` |
| GET | `/memory/duplicates/preview` | `app.memory` | `estimate_memory_duplicates` | oui | `back/app/memory/router.py:363` |
| GET | `/memory/filter-options` | `app.memory` | `read_memory_filter_options` | oui | `back/app/memory/router.py:474` |
| GET | `/memory/findings` | `app.memory` | `list_memory_findings` | oui | `back/app/memory/router.py:385` |
| POST | `/memory/findings/{finding_id}/apply` | `app.memory` | `apply_memory_finding` | oui | `back/app/memory/router.py:404` |
| POST | `/memory/findings/{finding_id}/dismiss` | `app.memory` | `dismiss_memory_finding` | oui | `back/app/memory/router.py:422` |
| POST | `/memory/goal-folders/reconcile` | `app.memory` | `launch_goal_folder_reconciliation` | oui | `back/app/memory/router.py:329` |
| POST | `/memory/graph/expand` | `app.memory` | `expand_memory_graph_node` | oui | `back/app/memory/router.py:514` |
| POST | `/memory/graph/roots` | `app.memory` | `list_memory_graph_roots` | oui | `back/app/memory/router.py:502` |
| POST | `/memory/items` | `app.memory` | `create_memory_item` | oui | `back/app/memory/router.py:219` |
| DELETE | `/memory/items/{item_id}` | `app.memory` | `forget_memory_item` | oui | `back/app/memory/router.py:620` |
| GET | `/memory/items/{item_id}` | `app.memory` | `get_memory_item` | oui | `back/app/memory/router.py:552` |
| PUT | `/memory/items/{item_id}` | `app.memory` | `update_memory_item` | oui | `back/app/memory/router.py:597` |
| DELETE | `/memory/items/{item_id}/grants/{agent_id}` | `app.memory` | `remove_memory_item_grant` | oui | `back/app/memory/router.py:1508` |
| PUT | `/memory/items/{item_id}/grants/{agent_id}` | `app.memory` | `set_memory_item_grant` | oui | `back/app/memory/router.py:1493` |
| GET | `/memory/items/{item_id}/links` | `app.memory` | `list_memory_links` | oui | `back/app/memory/router.py:1543` |
| GET | `/memory/items/{item_id}/revisions` | `app.memory` | `list_memory_revisions` | oui | `back/app/memory/router.py:582` |
| GET | `/memory/items/{item_id}/sharing` | `app.memory` | `read_item_sharing` | oui | `back/app/memory/router.py:526` |
| PUT | `/memory/items/{item_id}/sharing` | `app.memory` | `update_item_sharing` | oui | `back/app/memory/router.py:535` |
| GET | `/memory/link-reconciliation` | `app.memory` | `read_link_reconciliation_status` | oui | `back/app/memory/router.py:307` |
| POST | `/memory/link-reconciliation` | `app.memory` | `launch_link_reconciliation` | oui | `back/app/memory/router.py:319` |
| POST | `/memory/links` | `app.memory` | `create_memory_link` | oui | `back/app/memory/router.py:1525` |
| GET | `/memory/metrics` | `app.memory` | `read_memory_metrics` | oui | `back/app/memory/router.py:289` |
| POST | `/memory/provider/remember` | `bridge.hermes` | `hermes_provider_remember` | non | `back/bridge/hermes/router.py:192` |
| POST | `/memory/provider/search` | `bridge.hermes` | `hermes_provider_search` | non | `back/bridge/hermes/router.py:168` |
| POST | `/memory/recall` | `app.memory` | `recall_memory` | oui | `back/app/memory/router.py:490` |
| GET | `/memory/recent` | `app.memory` | `read_recent_memories` | oui | `back/app/memory/router.py:178` |
| GET | `/memory/retention/preview` | `app.memory` | `estimate_memory_retention` | oui | `back/app/memory/router.py:346` |
| POST | `/memory/search` | `app.memory` | `search_memory` | oui | `back/app/memory/router.py:462` |
| GET | `/messenger/bridges` | `app.messenger` | `list_messenger_bridges` | oui | `back/app/messenger/router.py:20` |
| GET | `/messenger/channels` | `app.messenger` | `list_enabled_messenger_channels` | oui | `back/app/messenger/router.py:68` |
| POST | `/messenger/configuration/test` | `app.messenger` | `test_messenger_configuration` | oui | `back/app/messenger/router.py:31` |
| GET | `/messenger/users` | `app.messenger` | `search_messenger_users` | oui | `back/app/messenger/router.py:41` |
| GET | `/metrics` | `app.process` | `read_metrics` | oui | `back/app/process/router.py:431` |
| POST | `/multimedia/callback/{run_id}/{token}` | `app.multimedia` | `acknowledge_callback` | non | `back/app/multimedia/router.py:54` |
| GET | `/multimedia/runs/{run_id}/deliveries` | `app.multimedia` | `list_deliveries` | oui | `back/app/multimedia/router.py:29` |
| POST | `/multimedia/runs/{run_id}/deliveries/{receipt_id}/resolve` | `app.multimedia` | `resolve_delivery` | oui | `back/app/multimedia/router.py:41` |
| GET | `/n8n/settings` | `bridge.n8n` | `read_settings` | oui | `back/bridge/n8n/router.py:14` |
| POST | `/n8n/test` | `bridge.n8n` | `check_connection` | oui | `back/bridge/n8n/router.py:20` |
| GET | `/onboarding/overview` | `app.onboarding` | `get_onboarding_overview` | oui | `back/app/onboarding/router.py:25` |
| GET | `/operations` | `app.process` | `read_process_operations` | oui | `back/app/process/router.py:114` |
| GET | `/params` | `core.params` | `read_params` | oui | `back/core/params/router.py:46` |
| PUT | `/params/{name}` | `core.params` | `update_param` | oui | `back/core/params/router.py:83` |
| GET | `/retention/preview` | `app.process` | `preview_retention` | oui | `back/app/process/router.py:79` |
| GET | `/runs` | `app.process` | `read_runs` | oui | `back/app/process/router.py:237` |
| POST | `/runs` | `app.process` | `create_run` | oui | `back/app/process/router.py:191` |
| DELETE | `/runs/{run_id}` | `app.process` | `delete_run` | oui | `back/app/process/router.py:293` |
| GET | `/runs/{run_id}` | `app.process` | `read_run` | oui | `back/app/process/router.py:283` |
| POST | `/runs/{run_id}/analyze` | `app.process` | `analyze_run` | oui | `back/app/process/router.py:318` |
| POST | `/runs/{run_id}/cancel` | `app.process` | `cancel_run` | oui | `back/app/process/router.py:328` |
| POST | `/runs/{run_id}/events` | `app.process` | `receive_event` | non | `back/app/process/router.py:361` |
| GET | `/runs/{run_id}/export` | `app.process` | `export_process_run` | oui | `back/app/process/router.py:86` |
| GET | `/runs/{run_id}/files/{file_id}` | `app.process` | `download_run_file` | non | `back/app/process/router.py:375` |
| POST | `/runs/{run_id}/refresh` | `app.process` | `refresh_run` | oui | `back/app/process/router.py:305` |
| POST | `/runs/{run_id}/retry` | `app.process` | `retry_run` | oui | `back/app/process/router.py:341` |
| POST | `/runtime-agents/{id}/sync-skills` | `app.harness` | `sync_harness_skills` | oui | `back/app/harness/router.py:99` |
| GET | `/skills` | `app.skill` | `list_skills` | oui | `back/app/skill/router.py:80` |
| POST | `/skills` | `app.skill` | `create_skill` | oui | `back/app/skill/router.py:346` |
| GET | `/skills/agents` | `app.skill` | `list_skill_agents` | oui | `back/app/skill/router.py:117` |
| GET | `/skills/authorizations` | `app.skill` | `list_skill_authorizations` | oui | `back/app/skill/router.py:132` |
| GET | `/skills/categories` | `app.skill` | `list_skill_categories` | oui | `back/app/skill/router.py:156` |
| POST | `/skills/categories` | `app.skill` | `create_skill_category` | oui | `back/app/skill/router.py:169` |
| DELETE | `/skills/categories/{category_id}` | `app.skill` | `delete_skill_category` | oui | `back/app/skill/router.py:199` |
| PUT | `/skills/categories/{category_id}` | `app.skill` | `update_skill_category` | oui | `back/app/skill/router.py:180` |
| PUT | `/skills/categories/{category_id}/authorization/agents/{agent_id}` | `app.skill` | `update_category_authorization` | oui | `back/app/skill/router.py:216` |
| POST | `/skills/import` | `app.skill` | `import_skill` | oui | `back/app/skill/router.py:98` |
| GET | `/skills/learned` | `app.skill` | `list_learned_skills` | oui | `back/app/skill/router.py:278` |
| GET | `/skills/learned/status` | `app.skill` | `get_learned_skill_status` | oui | `back/app/skill/router.py:302` |
| GET | `/skills/learned/{learned_skill_id}` | `app.skill` | `get_learned_skill` | oui | `back/app/skill/router.py:309` |
| PUT | `/skills/learned/{learned_skill_id}/suspension` | `app.skill` | `suspend_learned_skill` | oui | `back/app/skill/router.py:327` |
| POST | `/skills/rescan` | `app.skill` | `rescan_skills` | oui | `back/app/skill/router.py:86` |
| DELETE | `/skills/{skill_id}` | `app.skill` | `delete_skill` | oui | `back/app/skill/router.py:379` |
| GET | `/skills/{skill_id}` | `app.skill` | `get_skill` | oui | `back/app/skill/router.py:357` |
| PUT | `/skills/{skill_id}` | `app.skill` | `update_skill` | oui | `back/app/skill/router.py:363` |
| PUT | `/skills/{skill_id}/authorization/agents/{agent_id}` | `app.skill` | `update_agent_authorization` | oui | `back/app/skill/router.py:440` |
| PUT | `/skills/{skill_id}/authorization/global` | `app.skill` | `update_global_authorization` | oui | `back/app/skill/router.py:415` |
| PUT | `/skills/{skill_id}/category` | `app.skill` | `assign_skill_category` | oui | `back/app/skill/router.py:392` |
| GET | `/skills/{skill_id}/content` | `app.skill` | `read_skill_file` | oui | `back/app/skill/router.py:494` |
| GET | `/skills/{skill_id}/download` | `app.skill` | `download_skill` | oui | `back/app/skill/router.py:468` |
| GET | `/skills/{skill_id}/file` | `app.skill` | `download_skill_file` | oui | `back/app/skill/router.py:506` |
| GET | `/skills/{skill_id}/files` | `app.skill` | `list_skill_files` | oui | `back/app/skill/router.py:484` |
| GET | `/tasks` | `app.task` | `read_tasks` | oui | `back/app/task/router.py:58` |
| POST | `/tasks` | `app.task` | `create_task` | oui | `back/app/task/router.py:175` |
| GET | `/tasks/active` | `app.task` | `read_active_tasks` | oui | `back/app/task/router.py:137` |
| POST | `/tasks/activity` | `app.task` | `read_task_activity` | oui | `back/app/task/router.py:148` |
| DELETE | `/tasks/cleanup` | `app.task` | `cleanup_tasks` | oui | `back/app/task/router.py:285` |
| GET | `/tasks/recent` | `app.task` | `read_recent_tasks` | oui | `back/app/task/router.py:78` |
| DELETE | `/tasks/{task_id}` | `app.task` | `delete_task` | oui | `back/app/task/router.py:295` |
| GET | `/tasks/{task_id}` | `app.task` | `read_task` | oui | `back/app/task/router.py:155` |
| PUT | `/tasks/{task_id}` | `app.task` | `update_task` | oui | `back/app/task/router.py:199` |
| GET | `/tasks/{task_id}/budget` | `app.task` | `read_task_budget` | oui | `back/app/task/router.py:165` |
| POST | `/tasks/{task_id}/cancel` | `app.task` | `cancel_task` | oui | `back/app/task/router.py:253` |
| GET | `/tasks/{task_id}/children` | `app.task` | `read_task_children` | oui | `back/app/task/router.py:369` |
| POST | `/tasks/{task_id}/force-terminate` | `app.task` | `force_terminate_task` | oui | `back/app/task/router.py:268` |
| GET | `/tasks/{task_id}/full` | `app.task` | `read_task_full` | oui | `back/app/task/router.py:359` |
| POST | `/tasks/{task_id}/pause` | `app.task` | `pause_task` | oui | `back/app/task/router.py:326` |
| POST | `/tasks/{task_id}/restore` | `app.task` | `restore_task` | oui | `back/app/task/router.py:312` |
| POST | `/tasks/{task_id}/resume` | `app.task` | `resume_task` | oui | `back/app/task/router.py:340` |
| POST | `/tasks/{task_id}/retry` | `app.task` | `retry_task` | oui | `back/app/task/router.py:219` |
| POST | `/tasks/{task_id}/run` | `app.task` | `run_task` | oui | `back/app/task/router.py:385` |
| GET | `/teams` | `core.team` | `list_teams` | oui | `back/core/team/router.py:13` |
| POST | `/teams` | `core.team` | `create_team` | oui | `back/core/team/router.py:25` |
| GET | `/teams/humans` | `core.team` | `search_humans` | oui | `back/core/team/router.py:19` |
| DELETE | `/teams/{team_id}` | `core.team` | `delete_team` | oui | `back/core/team/router.py:49` |
| PUT | `/teams/{team_id}` | `core.team` | `update_team` | oui | `back/core/team/router.py:36` |
| GET | `/teams/{team_id}/humans` | `core.team` | `team_humans` | oui | `back/core/team/router.py:70` |
| PUT | `/teams/{team_id}/humans/{user_id}` | `core.team` | `set_human_membership` | oui | `back/core/team/router.py:79` |
| PUT | `/teams/{team_id}/position` | `core.team` | `move_team` | oui | `back/core/team/router.py:60` |
| GET | `/tools` | `app.process` | `read_process_tools` | oui | `back/app/process/router.py:99` |
| GET | `/tools` | `app.tools` | `list_tools` | oui | `back/app/tools/router.py:108` |
| POST | `/tools` | `app.tools` | `create_tool` | oui | `back/app/tools/router.py:199` |
| GET | `/tools/agents/{agent_id}/mcp-tools` | `app.tools` | `list_agent_mcp_tools` | oui | `back/app/tools/router.py:118` |
| POST | `/tools/import` | `app.tools` | `import_tool` | oui | `back/app/tools/router.py:289` |
| POST | `/tools/test-mcp` | `app.tools` | `test_mcp_connection` | oui | `back/app/tools/router.py:127` |
| GET | `/tools/{tool_code}/health` | `app.process` | `read_process_tool_health` | oui | `back/app/process/router.py:105` |
| DELETE | `/tools/{tool_id}` | `app.tools` | `delete_tool` | oui | `back/app/tools/router.py:251` |
| GET | `/tools/{tool_id}` | `app.tools` | `get_tool` | oui | `back/app/tools/router.py:147` |
| PUT | `/tools/{tool_id}` | `app.tools` | `update_tool` | oui | `back/app/tools/router.py:215` |
| PATCH | `/tools/{tool_id}/conversation-access` | `app.tools` | `update_conversation_access` | oui | `back/app/tools/router.py:231` |
| GET | `/tools/{tool_id}/export` | `app.tools` | `export_tool` | oui | `back/app/tools/router.py:266` |
| GET | `/tools/{tool_id}/global-params` | `app.tools` | `get_global_params` | oui | `back/app/tools/router.py:159` |
| PUT | `/tools/{tool_id}/global-params` | `app.tools` | `update_global_params` | oui | `back/app/tools/router.py:176` |
| GET | `/topics` | `app.topic` | `read_topics` | oui | `back/app/topic/router.py:39` |
| POST | `/topics` | `app.topic` | `create_topic` | oui | `back/app/topic/router.py:90` |
| GET | `/topics/conversation` | `app.topic` | `read_conversation_topics` | oui | `back/app/topic/router.py:57` |
| GET | `/topics/keywords` | `app.topic` | `read_topic_keywords` | oui | `back/app/topic/router.py:72` |
| GET | `/topics/refs` | `app.topic` | `read_topic_refs` | oui | `back/app/topic/router.py:80` |
| DELETE | `/topics/{topic_id}` | `app.topic` | `delete_topic` | oui | `back/app/topic/router.py:177` |
| GET | `/topics/{topic_id}` | `app.topic` | `read_topic` | oui | `back/app/topic/router.py:185` |
| PUT | `/topics/{topic_id}` | `app.topic` | `update_topic` | oui | `back/app/topic/router.py:133` |
| GET | `/topics/{topic_id}/content` | `app.topic` | `read_topic_content` | oui | `back/app/topic/router.py:116` |
| GET | `/topics/{topic_id}/memories` | `app.topic` | `read_topic_memories` | oui | `back/app/topic/router.py:103` |
| POST | `/topics/{topic_id}/merge` | `app.topic` | `merge_topic` | oui | `back/app/topic/router.py:145` |
| POST | `/topics/{topic_id}/split` | `app.topic` | `split_topic` | oui | `back/app/topic/router.py:163` |
| POST | `/v1/chat/completions` | `bridge.codex` | `chat_completions` | non | `back/bridge/codex/default-agent/server.py:258` |
| GET | `/v1/models` | `bridge.codex` | `models` | non | `back/bridge/codex/default-agent/server.py:189` |
| GET | `/voice/conversations` | `app.voice` | `read_voice_conversations` | oui | `back/app/voice/router.py:30` |
| DELETE | `/voice/conversations/turns/{turn_id}` | `app.voice` | `delete_voice_conversation_turn` | oui | `back/app/voice/router.py:132` |
| GET | `/voice/conversations/turns/{turn_id}` | `app.voice` | `read_voice_conversation_turn` | oui | `back/app/voice/router.py:87` |
| GET | `/voice/conversations/turns/{turn_id}/dataset` | `app.voice` | `export_voice_conversation_turn` | oui | `back/app/voice/router.py:119` |
| PUT | `/voice/conversations/turns/{turn_id}/topic` | `app.voice` | `update_voice_conversation_turn_topic` | oui | `back/app/voice/router.py:97` |
| GET | `/voice/conversations/{conversation_id}` | `app.voice` | `read_voice_conversation` | oui | `back/app/voice/router.py:147` |
| GET | `/whatsapp/webhook` | `bridge.whatsapp` | `verify_webhook` | non | `back/bridge/whatsapp/router.py:81` |
| POST | `/whatsapp/webhook` | `bridge.whatsapp` | `receive_webhook` | non | `back/bridge/whatsapp/router.py:253` |
| GET | `/whatsapp/webhook/{tool_id}` | `bridge.whatsapp` | `verify_tool_webhook` | non | `back/bridge/whatsapp/router.py:100` |
| POST | `/whatsapp/webhook/{tool_id}` | `bridge.whatsapp` | `receive_tool_webhook` | non | `back/bridge/whatsapp/router.py:261` |
| POST | `/workflows/{workflow_id}/runs/{engine_run_id}/sync` | `app.process` | `sync_engine_run` | oui | `back/app/process/router.py:216` |
| WEBSOCKET | `/ws/onebot/{platform}/{user_id}` | `bridge.one_bot` | `onebot_endpoint` | non | `back/bridge/one_bot/router.py:134` |

## Modèles SQLAlchemy

| Table | Classe | Module | Historisée | Clés étrangères | Source |
|---|---|---|---:|---|---|
| `agent_groups` | `Team` | `core.team` | oui | — | `back/core/team/models.py:10` |
| `agent_harnesses` | `AgentHarness` | `app.harnesses` | non | `agents.id`, `harnesses.id` | `back/app/harnesses/models.py:69` |
| `agent_mcp_tokens` | `AgentMcpToken` | `app.mcp` | non | `agents.id` | `back/app/mcp/models.py:17` |
| `agent_skill_categories` | `AgentSkillCategory` | `app.skill` | non | `agents.id`, `skill_categories.id` | `back/app/skill/models.py:115` |
| `agent_skills` | `AgentSkill` | `app.skill` | non | `agents.id`, `skills.id` | `back/app/skill/models.py:86` |
| `agent_teams` | `AgentTeam` | `app.agent` | non | `agent_groups.id`, `agents.id` | `back/app/agent/models.py:17` |
| `agents` | `Agent` | `app.agent` | oui | `agent_groups.id`, `harnesses.id`, `llm_profiles.id`, `memory_items.id`, `titles.id`, `users.id` | `back/app/agent/models.py:37` |
| `assignments` | `Assignment` | `core.authorize` | oui | `roles.id`, `users.id` | `back/core/authorize/models.py:69` |
| `calendar_feeds` | `CalendarFeed` | `bridge.calendar` | oui | `connections.id` | `back/bridge/calendar/models.py:15` |
| `calendar_triggers` | `CalendarTrigger` | `bridge.calendar` | non | `calendar_feeds.id`, `process_runs.id`, `tasks.id` | `back/bridge/calendar/models.py:60` |
| `chat_emoji_usages` | `ChatEmojiUsage` | `app.chat` | non | `users.id` | `back/app/chat/models.py:25` |
| `chat_push_deliveries` | `ChatPushDelivery` | `app.chat` | non | `chat_push_subscriptions.id`, `messenger_messages.id`, `messenger_rooms.id`, `users.id` | `back/app/chat/models.py:105` |
| `chat_push_subscriptions` | `ChatPushSubscription` | `app.chat` | non | `users.id` | `back/app/chat/models.py:62` |
| `connection_function_state` | `ConnectionFunctionState` | `app.connection` | non | `connections.id` | `back/app/connection/models.py:51` |
| `connection_params` | `ConnectionParam` | `app.connection` | non | `connections.id` | `back/app/connection/models.py:32` |
| `connections` | `Connection` | `app.connection` | non | `agents.id`, `tools.id` | `back/app/connection/models.py:6` |
| `conversation_delivery_resolutions` | `ConversationDeliveryResolution` | `app.conversation` | non | `conversation_rounds.id`, `users.id` | `back/app/conversation/models.py:27` |
| `conversation_notification_resolutions` | `ConversationNotificationResolution` | `app.conversation` | non | `conversation_process_links.id`, `conversation_task_links.id`, `users.id` | `back/app/conversation/models.py:39` |
| `conversation_process_links` | `ConversationProcessLink` | `app.conversation` | non | `conversation_rounds.id`, `messenger_messages.id`, `process_runs.id` | `back/app/conversation/models.py:313` |
| `conversation_round_attempts` | `ConversationRoundAttempt` | `app.conversation` | non | `conversation_rounds.id` | `back/app/conversation/models.py:235` |
| `conversation_round_messages` | `ConversationRoundMessage` | `app.conversation` | non | `conversation_rounds.id`, `messenger_messages.id` | `back/app/conversation/models.py:175` |
| `conversation_rounds` | `ConversationRound` | `app.conversation` | non | `conversation_rounds.id`, `memory_items.id`, `messenger_rooms.id`, `topics.id`, `users.id`, `voice_sessions.id` | `back/app/conversation/models.py:58` |
| `conversation_task_links` | `ConversationTaskLink` | `app.conversation` | non | `conversation_rounds.id`, `messenger_messages.id`, `tasks.id` | `back/app/conversation/models.py:265` |
| `dbadmin_action_revisions` | `DbAdminActionRevision` | `core.dbadmin` | non | `dbadmin_actions.key` | `back/core/dbadmin/models.py:86` |
| `dbadmin_actions` | `DbAdminActionRecord` | `core.dbadmin` | non | — | `back/core/dbadmin/models.py:59` |
| `dbadmin_issues` | `DbAdminIssueRecord` | `core.dbadmin` | non | `dbadmin_runs.id` | `back/core/dbadmin/models.py:36` |
| `dbadmin_runs` | `DbAdminRun` | `core.dbadmin` | non | — | `back/core/dbadmin/models.py:16` |
| `document_app_grants` | `DocumentAppGrant` | `app.memory` | oui | `memory_items.id`, `users.id` | `back/app/memory/models.py:95` |
| `document_app_write_budgets` | `DocumentAppWriteBudget` | `app.memory` | non | `memory_items.id`, `users.id` | `back/app/memory/models.py:113` |
| `document_attachments` | `DocumentAttachment` | `app.memory` | non | `memory_items.id` | `back/app/memory/models.py:138` |
| `document_icons` | `DocumentIcon` | `app.memory` | non | `memory_items.id`, `users.id` | `back/app/memory/models.py:83` |
| `document_list_positions` | `DocumentListPosition` | `app.memory` | non | `memory_items.id`, `users.id` | `back/app/memory/models.py:126` |
| `document_tag_assignments` | `DocumentTagAssignment` | `app.memory` | non | `document_tags.id`, `memory_items.id` | `back/app/memory/models.py:73` |
| `document_tag_icons` | `DocumentTagIcon` | `app.memory` | oui | `users.id` | `back/app/memory/models.py:62` |
| `document_tags` | `DocumentTag` | `app.memory` | oui | `document_tags.id`, `goals.id`, `memory_items.id`, `users.id` | `back/app/memory/models.py:35` |
| `document_team_grants` | `DocumentTeamGrant` | `app.memory` | non | `agent_groups.id`, `memory_items.id` | `back/app/memory/models.py:428` |
| `document_user_grants` | `DocumentUserGrant` | `app.memory` | non | `memory_items.id`, `users.id` | `back/app/memory/models.py:417` |
| `dream_receipts` | `DreamReceipt` | `app.dream` | non | — | `back/app/dream/models.py:26` |
| `failure_incident_traces` | `FailureIncidentTrace` | `app.incident` | non | `failure_incidents.id` | `back/app/incident/models.py:172` |
| `failure_incidents` | `FailureIncident` | `app.incident` | non | `agents.id`, `conversation_rounds.id`, `failure_incidents.id`, `failure_patterns.id`, `llm_calls.id`, `process_runs.id`, `task_attempts.id`, `tasks.id` | `back/app/incident/models.py:81` |
| `failure_patterns` | `FailurePattern` | `app.incident` | non | — | `back/app/incident/models.py:27` |
| `goal_cycle_triggers` | `GoalCycleTrigger` | `app.goal` | non | `goal_cycles.id`, `goals.id` | `back/app/goal/models.py:358` |
| `goal_cycles` | `GoalCycle` | `app.goal` | non | `goal_cycles.id`, `goals.id`, `llms.id`, `memory_items.id`, `tasks.id` | `back/app/goal/models.py:234` |
| `goals` | `Goal` | `app.goal` | oui | `agents.id`, `connections.id`, `goals.id`, `memory_items.id`, `users.id` | `back/app/goal/models.py:75` |
| `harness_execution_configurations` | `HarnessExecutionConfiguration` | `app.harnesses` | oui | — | `back/app/harnesses/models.py:18` |
| `harnesses` | `Harness` | `app.harnesses` | oui | — | `back/app/harnesses/models.py:29` |
| `hermes_agent_configs` | `HermesAgentConfig` | `bridge.hermes` | non | `agents.id` | `back/bridge/hermes/models.py:14` |
| `hermes_session_bindings` | `HermesSessionBinding` | `bridge.hermes` | non | `agents.id` | `back/bridge/hermes/models.py:73` |
| `lab_evaluation_cases` | `LabEvaluationCase` | `app.lab` | oui | `lab_evaluation_cases.id`, `lab_evaluation_datasets.id` | `back/app/lab/models.py:130` |
| `lab_evaluation_datasets` | `LabEvaluationDataset` | `app.lab` | oui | — | `back/app/lab/models.py:89` |
| `lab_evaluation_run_cases` | `LabEvaluationRunCase` | `app.lab` | oui | `lab_evaluation_cases.id`, `lab_evaluation_runs.id` | `back/app/lab/models.py:285` |
| `lab_evaluation_runs` | `LabEvaluationRun` | `app.lab` | oui | `lab_evaluation_datasets.id`, `llms.id` | `back/app/lab/models.py:191` |
| `lab_human_reviews` | `LabHumanReview` | `app.lab` | oui | `lab_evaluation_run_cases.id`, `lab_judgment_campaigns.id`, `users.id` | `back/app/lab/models.py:385` |
| `lab_judgment_campaigns` | `LabJudgmentCampaign` | `app.lab` | oui | `lab_evaluation_runs.id`, `llms.id` | `back/app/lab/models.py:333` |
| `lab_judgment_results` | `LabJudgmentResult` | `app.lab` | oui | `lab_evaluation_run_cases.id`, `lab_judgment_campaigns.id` | `back/app/lab/models.py:360` |
| `lab_task_diagnoses` | `LabTaskDiagnosis` | `app.lab` | oui | `tasks.id` | `back/app/lab/models.py:43` |
| `lab_tasks` | `LabTask` | `app.lab` | non | `tasks.id` | `back/app/lab/models.py:27` |
| `learned_skill_evidences` | `LearnedSkillEvidence` | `app.skill` | non | `learned_skills.id` | `back/app/skill/models.py:204` |
| `learned_skills` | `LearnedSkill` | `app.skill` | oui | `agents.id` | `back/app/skill/models.py:145` |
| `llm_call_events` | `LLMCallEvent` | `app.llm` | non | `llm_calls.id`, `llm_inferences.id` | `back/app/llm/models.py:58` |
| `llm_calls` | `LLMCall` | `app.llm` | non | `agents.id`, `conversation_rounds.id`, `llm_inference_attempts.id`, `llms.id`, `process_runs.id`, `task_attempts.id`, `tasks.id`, `users.id` | `back/app/llm/models.py:77` |
| `llm_inference_attempts` | `LLMInferenceAttempt` | `app.llm` | non | `llm_inferences.id` | `back/app/llm/models.py:30` |
| `llm_inference_commands` | `LLMInferenceCommand` | `app.llm` | non | `llm_inference_attempts.id`, `llm_inferences.id` | `back/app/llm/models.py:46` |
| `llm_inferences` | `LLMInference` | `app.llm` | non | `llm_inferences.id`, `users.id` | `back/app/llm/models.py:16` |
| `llm_profiles` | `LlmProfile` | `app.llm` | non | `llms.id` | `back/app/llm/profile_models.py:18` |
| `llm_providers` | `LLMProvider` | `app.llm` | oui | `users.id` | `back/app/llm/provider_models.py:9` |
| `llms` | `LLM` | `app.llm` | oui | `llm_providers.id` | `back/app/llm/provider_models.py:103` |
| `mail_outbound_deliveries` | `MailOutboundDelivery` | `bridge.mail` | non | `agents.id`, `connections.id`, `users.id` | `back/bridge/mail/models.py:28` |
| `memory_associations` | `MemoryAssociation` | `app.memory` | non | `memory_items.id` | `back/app/memory/models.py:957` |
| `memory_automation_jobs` | `MemoryAutomationJob` | `app.memory` | non | — | `back/app/memory/models.py:1139` |
| `memory_candidates` | `MemoryAcquisition` | `app.memory` | oui | `agents.id`, `memory_items.id`, `users.id` | `back/app/memory/models.py:871` |
| `memory_contact_identities` | `MemoryContactIdentity` | `app.memory` | non | `agents.id`, `memory_items.id`, `users.id` | `back/app/memory/models.py:677` |
| `memory_contact_items` | `MemoryContactItem` | `app.memory` | non | `agents.id`, `memory_items.id` | `back/app/memory/models.py:639` |
| `memory_context_edges` | `MemoryContextEdge` | `app.memory` | non | `memory_context_nodes.id`, `memory_items.id` | `back/app/memory/models.py:602` |
| `memory_context_nodes` | `MemoryContextNode` | `app.memory` | non | `agents.id` | `back/app/memory/models.py:547` |
| `memory_embedding_chunks` | `MemoryEmbeddingChunk` | `app.memory` | non | `memory_items.id` | `back/app/memory/models.py:1014` |
| `memory_embedding_manifests` | `MemoryEmbeddingManifest` | `app.memory` | non | `memory_items.id` | `back/app/memory/models.py:991` |
| `memory_findings` | `MemoryFinding` | `app.memory` | non | `memory_items.id`, `users.id` | `back/app/memory/models.py:1068` |
| `memory_item_grants` | `MemoryItemGrant` | `app.memory` | non | `agents.id`, `memory_items.id` | `back/app/memory/models.py:393` |
| `memory_items` | `MemoryItem` | `app.memory` | oui | `agents.id`, `topics.id`, `users.id` | `back/app/memory/models.py:153` |
| `memory_links` | `MemoryLink` | `app.memory` | oui | `agents.id`, `memory_items.id` | `back/app/memory/models.py:495` |
| `memory_revisions` | `MemoryRevision` | `app.memory` | non | `agents.id`, `memory_items.id`, `tasks.id` | `back/app/memory/models.py:439` |
| `memory_sources` | `MemorySource` | `app.memory` | non | `conversation_rounds.id`, `memory_items.id`, `tasks.id` | `back/app/memory/models.py:821` |
| `memory_topic_contact_items` | `MemoryTopicContactItem` | `app.memory` | non | `memory_items.id`, `memory_topic_contact_scopes.id` | `back/app/memory/models.py:782` |
| `memory_topic_contact_scopes` | `MemoryTopicContactScope` | `app.memory` | non | `agents.id`, `memory_items.id` | `back/app/memory/models.py:741` |
| `memory_usages` | `MemoryUsage` | `app.memory` | non | `agents.id`, `memory_items.id` | `back/app/memory/models.py:924` |
| `messenger_files` | `File` | `app.messenger` | oui | `connections.id` | `back/app/messenger/models.py:407` |
| `messenger_interactions` | `Interaction` | `app.messenger` | non | `connections.id` | `back/app/messenger/models.py:191` |
| `messenger_listener_state` | `ListenerState` | `app.messenger` | non | `connections.id` | `back/app/messenger/models.py:463` |
| `messenger_message_files` | `Attachment` | `app.messenger` | non | `messenger_files.id`, `messenger_messages.id` | `back/app/messenger/models.py:444` |
| `messenger_messages` | `Message` | `app.messenger` | oui | `connections.id`, `memory_items.id`, `messenger_rooms.id`, `messenger_users.id`, `topics.id`, `users.id` | `back/app/messenger/models.py:233` |
| `messenger_room_users` | `RoomUser` | `app.messenger` | non | `messenger_messages.id`, `messenger_rooms.id`, `messenger_users.id` | `back/app/messenger/models.py:138` |
| `messenger_rooms` | `Room` | `app.messenger` | oui | `connections.id`, `topics.id` | `back/app/messenger/models.py:62` |
| `messenger_users` | `MessengerUser` | `app.messenger` | oui | `agents.id`, `tools.id`, `users.id` | `back/app/messenger/models.py:95` |
| `multimedia_delivery_resolutions` | `MediaDeliveryResolution` | `app.multimedia` | non | `multimedia_output_receipts.id`, `users.id` | `back/app/multimedia/models.py:31` |
| `multimedia_output_receipts` | `MediaOutputReceipt` | `app.multimedia` | non | `process_runs.id` | `back/app/multimedia/models.py:13` |
| `params` | `Param` | `core.params` | non | — | `back/core/params/models.py:7` |
| `privilege_lists` | `PrivilegeList` | `core.authorize` | non | — | `back/core/authorize/models.py:41` |
| `privileges` | `Privilege` | `core.authorize` | non | `privilege_lists.id` | `back/core/authorize/models.py:22` |
| `process_definitions` | `ProcessDefinition` | `app.process` | oui | `agents.id`, `tools.id` | `back/app/process/models.py:25` |
| `process_run_events` | `ProcessRunEvent` | `app.process` | non | `process_runs.id` | `back/app/process/models.py:116` |
| `process_runs` | `ProcessRun` | `app.process` | oui | `agents.id`, `process_definitions.id`, `tasks.id` | `back/app/process/models.py:52` |
| `process_start_jobs` | `ProcessStartJob` | `app.process` | non | `process_runs.id` | `back/app/process/models.py:138` |
| `role_privileges` | `RolePrivilege` | `core.authorize` | non | `privileges.id`, `roles.id` | `back/core/authorize/models.py:11` |
| `roles` | `Role` | `core.authorize` | non | — | `back/core/authorize/models.py:53` |
| `skill_categories` | `SkillCategory` | `app.skill` | oui | — | `back/app/skill/models.py:31` |
| `skills` | `Skill` | `app.skill` | oui | `skill_categories.id` | `back/app/skill/models.py:52` |
| `task_amendments` | `TaskAmendment` | `app.task` | non | `tasks.id` | `back/app/task/models.py:257` |
| `task_attempts` | `TaskAttempt` | `app.task` | non | `tasks.id` | `back/app/task/models.py:290` |
| `tasks` | `Task` | `app.task` | oui | `agents.id`, `connections.id`, `goals.id`, `memory_items.id`, `messenger_messages.id`, `tasks.id`, `topics.id`, `users.id` | `back/app/task/models.py:79` |
| `team_audit` | `TeamAudit` | `core.team` | oui | — | `back/core/team/models.py:28` |
| `team_users` | `TeamUser` | `core.team` | non | `agent_groups.id`, `users.id` | `back/core/team/models.py:19` |
| `titles` | `Title` | `app.agent` | non | — | `back/app/agent/models.py:27` |
| `tool_function_state` | `ToolFunctionState` | `app.connection` | non | `tools.id` | `back/app/connection/models.py:75` |
| `tool_search_documents` | `ToolSearchDocument` | `app.tools` | non | — | `back/app/tools/models.py:61` |
| `tools` | `Tool` | `app.tools` | non | — | `back/app/tools/models.py:21` |
| `topics` | `Topic` | `app.topic` | oui | `memory_items.id` | `back/app/topic/models.py:15` |
| `user_help_dismissals` | `UserHelpDismissal` | `core.user` | non | `users.id` | `back/core/user/models.py:80` |
| `user_llm_preferences` | `UserLlmPreferences` | `app.llm` | non | `llm_profiles.id`, `llms.id`, `users.id` | `back/app/llm/profile_models.py:109` |
| `user_refresh_sessions` | `UserRefreshSession` | `core.user` | non | `users.id` | `back/core/user/models.py:119` |
| `user_tokens` | `UserToken` | `core.user` | non | `users.id` | `back/core/user/models.py:92` |
| `users` | `User` | `core.user` | non | — | `back/core/user/models.py:13` |
| `voice_sessions` | `VoiceConversationSession` | `app.voice` | oui | `messenger_rooms.id`, `users.id` | `back/app/voice/models.py:58` |

## Outils MCP natifs

| Nom | Namespace | Module | Handler | Source |
|---|---|---|---|---|
| `topic_create` | `` | `app.topic` | `mcp_topic_create` | `back/app/topic/mcp.py:143` |
| `topic_get` | `` | `app.topic` | `mcp_topic_get` | `back/app/topic/mcp.py:98` |
| `topic_item_move` | `` | `app.topic` | `mcp_topic_item_move` | `back/app/topic/mcp.py:198` |
| `topic_items_list` | `` | `app.topic` | `mcp_topic_items_list` | `back/app/topic/mcp.py:118` |
| `topic_list` | `` | `app.topic` | `mcp_topic_list` | `back/app/topic/mcp.py:69` |
| `topic_merge` | `` | `app.topic` | `mcp_topic_merge` | `back/app/topic/mcp.py:227` |
| `topic_split` | `` | `app.topic` | `mcp_topic_split` | `back/app/topic/mcp.py:248` |
| `topic_update` | `` | `app.topic` | `mcp_topic_update` | `back/app/topic/mcp.py:168` |
| `audio_transcribe` | `audio` | `app.audio` | `transcribe_audio_file` | `back/app/audio/mcp.py:289` |
| `browser_back` | `browser` | `app.browser` | `browser_back` | `back/app/browser/mcp.py:414` |
| `browser_click` | `browser` | `app.browser` | `browser_click` | `back/app/browser/mcp.py:348` |
| `browser_close` | `browser` | `app.browser` | `browser_close` | `back/app/browser/mcp.py:427` |
| `browser_content` | `browser` | `app.browser` | `browser_content` | `back/app/browser/mcp.py:269` |
| `browser_navigate` | `browser` | `app.browser` | `browser_navigate` | `back/app/browser/mcp.py:253` |
| `browser_open` | `browser` | `app.browser` | `browser_open` | `back/app/browser/mcp.py:220` |
| `browser_press` | `browser` | `app.browser` | `browser_press` | `back/app/browser/mcp.py:386` |
| `browser_screenshot` | `browser` | `app.browser` | `browser_screenshot` | `back/app/browser/mcp.py:314` |
| `browser_scroll` | `browser` | `app.browser` | `browser_scroll` | `back/app/browser/mcp.py:400` |
| `browser_type` | `browser` | `app.browser` | `browser_type` | `back/app/browser/mcp.py:362` |
| `calendar_create_event` | `calendar` | `bridge.calendar` | `calendar_create_event` | `back/bridge/calendar/mcp.py:132` |
| `calendar_delete_event` | `calendar` | `bridge.calendar` | `calendar_delete_event` | `back/bridge/calendar/mcp.py:192` |
| `calendar_events` | `calendar` | `bridge.calendar` | `calendar_events` | `back/bridge/calendar/mcp.py:49` |
| `calendar_find_free_slots` | `calendar` | `bridge.calendar` | `calendar_find_free_slots` | `back/bridge/calendar/mcp.py:98` |
| `calendar_is_available` | `calendar` | `bridge.calendar` | `calendar_is_available` | `back/bridge/calendar/mcp.py:75` |
| `calendar_list` | `calendar` | `bridge.calendar` | `calendar_list` | `back/bridge/calendar/mcp.py:37` |
| `calendar_update_event` | `calendar` | `bridge.calendar` | `calendar_update_event` | `back/bridge/calendar/mcp.py:162` |
| `console_exec` | `console` | `app.console` | `console_exec` | `back/app/console/mcp.py:50` |
| `console_poll` | `console` | `app.console` | `console_poll` | `back/app/console/mcp.py:98` |
| `console_start` | `console` | `app.console` | `console_start` | `back/app/console/mcp.py:77` |
| `console_status` | `console` | `app.console` | `console_status` | `back/app/console/mcp.py:35` |
| `console_stop` | `console` | `app.console` | `console_stop` | `back/app/console/mcp.py:127` |
| `console_write` | `console` | `app.console` | `console_write` | `back/app/console/mcp.py:112` |
| `conversation_choice_resolve` | `conversation` | `app.conversation` | `conversation_choice_resolve` | `back/app/conversation/mcp.py:912` |
| `conversation_process_start` | `conversation` | `app.conversation` | `conversation_process_start` | `back/app/conversation/mcp.py:1040` |
| `conversation_task_list` | `conversation` | `app.conversation` | `conversation_task_list` | `back/app/conversation/mcp.py:852` |
| `conversation_task_pause` | `conversation` | `app.conversation` | `conversation_task_pause` | `back/app/conversation/mcp.py:991` |
| `conversation_task_resume` | `conversation` | `app.conversation` | `conversation_task_resume` | `back/app/conversation/mcp.py:1002` |
| `conversation_task_retry` | `conversation` | `app.conversation` | `conversation_task_retry` | `back/app/conversation/mcp.py:1013` |
| `conversation_task_status` | `conversation` | `app.conversation` | `conversation_task_status` | `back/app/conversation/mcp.py:892` |
| `conversation_task_stop` | `conversation` | `app.conversation` | `conversation_task_stop` | `back/app/conversation/mcp.py:1024` |
| `conversation_task_submit` | `conversation` | `app.conversation` | `conversation_task_submit` | `back/app/conversation/mcp.py:591` |
| `document_show` | `conversation` | `app.conversation` | `document_show` | `back/app/conversation/mcp.py:107` |
| `file_append` | `file_sharing` | `app.file_share` | `append_file` | `back/app/file_share/mcp.py:289` |
| `file_copy` | `file_sharing` | `app.file_share` | `copy_file` | `back/app/file_share/mcp.py:344` |
| `file_create` | `file_sharing` | `app.file_share` | `create_file` | `back/app/file_share/mcp.py:228` |
| `file_delete` | `file_sharing` | `app.file_share` | `delete_file` | `back/app/file_share/mcp.py:403` |
| `file_edit` | `file_sharing` | `app.file_share` | `edit_file` | `back/app/file_share/mcp.py:310` |
| `file_info` | `file_sharing` | `app.file_share` | `file_info` | `back/app/file_share/mcp.py:120` |
| `file_list` | `file_sharing` | `app.file_share` | `list_files` | `back/app/file_share/mcp.py:92` |
| `file_move` | `file_sharing` | `app.file_share` | `move_file` | `back/app/file_share/mcp.py:375` |
| `file_read` | `file_sharing` | `app.file_share` | `read_file` | `back/app/file_share/mcp.py:191` |
| `file_schemes` | `file_sharing` | `app.file_share` | `file_schemes` | `back/app/file_share/mcp.py:71` |
| `file_search` | `file_sharing` | `app.file_share` | `search_files` | `back/app/file_share/mcp.py:150` |
| `file_write` | `file_sharing` | `app.file_share` | `write_file` | `back/app/file_share/mcp.py:260` |
| `agent_get` | `galaris` | `app.agent` | `get_agent` | `back/app/agent/mcp.py:38` |
| `agent_list` | `galaris` | `app.agent` | `list_agents` | `back/app/agent/mcp.py:19` |
| `goal_ask_referrer` | `galaris` | `app.goal` | `mcp_goal_ask_referrer` | `back/app/goal/mcp.py:130` |
| `goal_run_now` | `galaris` | `app.goal` | `mcp_goal_run_now` | `back/app/goal/mcp.py:443` |
| `goal_update_suivi` | `galaris` | `app.goal` | `mcp_goal_update_suivi` | `back/app/goal/mcp.py:269` |
| `process_analyze_run` | `galaris` | `app.process` | `process_analyze_run` | `back/app/process/mcp.py:156` |
| `process_get` | `galaris` | `app.process` | `process_get` | `back/app/process/mcp.py:60` |
| `process_get_run` | `galaris` | `app.process` | `process_get_run` | `back/app/process/mcp.py:141` |
| `process_list` | `galaris` | `app.process` | `process_list` | `back/app/process/mcp.py:51` |
| `process_list_runs` | `galaris` | `app.process` | `process_list_runs` | `back/app/process/mcp.py:121` |
| `process_start` | `galaris` | `app.process` | `process_start` | `back/app/process/mcp.py:86` |
| `task_get` | `galaris` | `app.task` | `mcp_get_task` | `back/app/task/mcp.py:90` |
| `task_run` | `galaris` | `app.task` | `mcp_run_task` | `back/app/task/mcp.py:176` |
| `task_stop` | `galaris` | `app.task` | `mcp_stop_task` | `back/app/task/mcp.py:155` |
| `tools_list` | `galaris` | `app.tools` | `list_mcp_tools` | `back/app/tools/mcp.py:60` |
| `conversation_round_get` | `galaris_admin` | `app.conversation` | `conversation_round_get` | `back/app/conversation/mcp.py:282` |
| `llm_call` | `galaris_admin` | `app.llm` | `mcp_llm_call` | `back/app/llm/mcp.py:30` |
| `llm_calls` | `galaris_admin` | `app.llm` | `mcp_llm_calls` | `back/app/llm/mcp.py:48` |
| `voice_turn_get` | `galaris_admin` | `app.voice` | `voice_turn_get` | `back/app/voice/mcp.py:53` |
| `goal_complete` | `goal_management` | `app.goal` | `mcp_goal_complete` | `back/app/goal/mcp.py:417` |
| `goal_create` | `goal_management` | `app.goal` | `mcp_goal_create` | `back/app/goal/mcp.py:156` |
| `goal_delete` | `goal_management` | `app.goal` | `mcp_goal_delete` | `back/app/goal/mcp.py:471` |
| `goal_pause` | `goal_management` | `app.goal` | `mcp_goal_pause` | `back/app/goal/mcp.py:369` |
| `goal_resume` | `goal_management` | `app.goal` | `mcp_goal_resume` | `back/app/goal/mcp.py:393` |
| `goal_update` | `goal_management` | `app.goal` | `mcp_goal_update` | `back/app/goal/mcp.py:304` |
| `image_generate` | `image` | `app.image` | `generate_image` | `back/app/image/mcp.py:123` |
| `image_read` | `image` | `app.image` | `describe_image` | `back/app/image/mcp.py:205` |
| `mail_connection_status` | `mail` | `bridge.mail` | `mail_connection_status` | `back/bridge/mail/mcp.py:21` |
| `mail_forward` | `mail` | `bridge.mail` | `mail_forward` | `back/bridge/mail/mcp.py:182` |
| `mail_get` | `mail` | `bridge.mail` | `mail_get` | `back/bridge/mail/mcp.py:86` |
| `mail_list_mailboxes` | `mail` | `bridge.mail` | `mail_list_mailboxes` | `back/bridge/mail/mcp.py:30` |
| `mail_move` | `mail` | `bridge.mail` | `mail_move` | `back/bridge/mail/mcp.py:242` |
| `mail_reply` | `mail` | `bridge.mail` | `mail_reply` | `back/bridge/mail/mcp.py:148` |
| `mail_search` | `mail` | `bridge.mail` | `mail_search` | `back/bridge/mail/mcp.py:42` |
| `mail_send` | `mail` | `bridge.mail` | `mail_send` | `back/bridge/mail/mcp.py:110` |
| `mail_set_flags` | `mail` | `bridge.mail` | `mail_set_flags` | `back/bridge/mail/mcp.py:219` |
| `mail_trash` | `mail` | `bridge.mail` | `mail_trash` | `back/bridge/mail/mcp.py:251` |
| `document_share` | `memory` | `app.memory` | `document_share` | `back/app/memory/mcp.py:356` |
| `memory_forget` | `memory` | `app.memory` | `memory_forget` | `back/app/memory/mcp.py:580` |
| `memory_remember` | `memory` | `app.memory` | `memory_remember` | `back/app/memory/mcp.py:475` |
| `memory_share` | `memory` | `app.memory` | `memory_share` | `back/app/memory/mcp.py:451` |
| `memory_sharing` | `memory` | `app.memory` | `memory_sharing` | `back/app/memory/mcp.py:423` |
| `memory_summarize` | `memory` | `app.memory` | `memory_summarize` | `back/app/memory/mcp.py:601` |
| `messenger_list_rooms` | `messenger` | `app.messenger` | `mcp_list_rooms` | `back/app/messenger/mcp.py:630` |
| `messenger_room_history` | `messenger` | `app.messenger` | `mcp_room_history` | `back/app/messenger/mcp.py:668` |
| `messenger_room_send_file` | `messenger` | `app.messenger` | `mcp_room_send_file` | `back/app/messenger/mcp.py:878` |
| `messenger_room_send_message` | `messenger` | `app.messenger` | `mcp_room_send_message` | `back/app/messenger/mcp.py:264` |
| `messenger_search_users` | `messenger` | `app.messenger` | `mcp_search_users` | `back/app/messenger/mcp.py:740` |
| `messenger_send_audio_message` | `messenger` | `app.messenger` | `mcp_send_audio_message` | `back/app/messenger/mcp.py:522` |
| `messenger_send_file_to_user` | `messenger` | `app.messenger` | `mcp_send_file_to_user` | `back/app/messenger/mcp.py:828` |
| `messenger_send_message_to_user` | `messenger` | `app.messenger` | `mcp_send_message_to_user` | `back/app/messenger/mcp.py:311` |
| `audio_read` | `multimedia` | `app.multimedia` | `audio_read` | `back/app/multimedia/mcp.py:13` |
| `music_generate` | `multimedia` | `app.multimedia` | `music_generate` | `back/app/multimedia/mcp.py:40` |
| `sound_generate` | `multimedia` | `app.multimedia` | `sound_generate` | `back/app/multimedia/mcp.py:33` |
| `video_generate` | `multimedia` | `app.multimedia` | `video_generate` | `back/app/multimedia/mcp.py:48` |
| `video_read` | `multimedia` | `app.multimedia` | `video_read` | `back/app/multimedia/mcp.py:18` |
| `process_admin_analyze_run` | `process_admin` | `app.process` | `process_admin_analyze_run` | `back/app/process/mcp.py:469` |
| `process_admin_cancel_run` | `process_admin` | `app.process` | `process_admin_cancel_run` | `back/app/process/mcp.py:441` |
| `process_admin_create` | `process_admin` | `app.process` | `process_admin_create` | `back/app/process/mcp.py:245` |
| `process_admin_delete` | `process_admin` | `app.process` | `process_admin_delete` | `back/app/process/mcp.py:322` |
| `process_admin_delete_run` | `process_admin` | `app.process` | `process_admin_delete_run` | `back/app/process/mcp.py:483` |
| `process_admin_engines` | `process_admin` | `app.process` | `process_admin_engines` | `back/app/process/mcp.py:168` |
| `process_admin_get` | `process_admin` | `app.process` | `process_admin_get` | `back/app/process/mcp.py:226` |
| `process_admin_get_run` | `process_admin` | `app.process` | `process_admin_get_run` | `back/app/process/mcp.py:407` |
| `process_admin_list` | `process_admin` | `app.process` | `process_admin_list` | `back/app/process/mcp.py:203` |
| `process_admin_list_runs` | `process_admin` | `app.process` | `process_admin_list_runs` | `back/app/process/mcp.py:378` |
| `process_admin_refresh_run` | `process_admin` | `app.process` | `process_admin_refresh_run` | `back/app/process/mcp.py:427` |
| `process_admin_retry_run` | `process_admin` | `app.process` | `process_admin_retry_run` | `back/app/process/mcp.py:455` |
| `process_admin_start` | `process_admin` | `app.process` | `process_admin_start` | `back/app/process/mcp.py:343` |
| `process_admin_sync` | `process_admin` | `app.process` | `process_admin_sync` | `back/app/process/mcp.py:187` |
| `process_admin_update` | `process_admin` | `app.process` | `process_admin_update` | `back/app/process/mcp.py:275` |
| `search_web` | `search` | `app.tools` | `search_web` | `back/app/tools/mcp.py:45` |
| `skill_read` | `skill_management` | `app.skill` | `mcp_skill_read` | `back/app/skill/mcp.py:43` |
| `skills_list` | `skill_management` | `app.skill` | `mcp_skills_list` | `back/app/skill/mcp.py:21` |
| `voice_call_list` | `voice` | `app.voice` | `mcp_list_voice_calls` | `back/app/voice/mcp.py:354` |
| `voice_call_start` | `voice` | `app.voice` | `mcp_start_voice_call` | `back/app/voice/mcp.py:297` |
| `voice_call_stop` | `voice` | `app.voice` | `mcp_stop_voice_call` | `back/app/voice/mcp.py:322` |

## Privilèges déclarés

| Constante | Module | Libellé | Source |
|---|---|---|---|
| `AGENT_ACCESS` | `app.agent` | privilege.AGENT_ACCESS | `back/app/agent/privileges.py:5` |
| `AGENT_API_ACCESS` | `app.agent` | privilege.AGENT_API_ACCESS | `back/app/agent/privileges.py:7` |
| `AGENT_EDIT` | `app.agent` | privilege.AGENT_EDIT | `back/app/agent/privileges.py:6` |
| `AGENT_MANAGE_ALL` | `app.agent` | privilege.AGENT_MANAGE_ALL | `back/app/agent/privileges.py:8` |
| `CHAT_ACCESS` | `app.chat` | privilege.CHAT_ACCESS | `back/app/chat/privileges.py:3` |
| `CHAT_CALL` | `app.chat` | privilege.CHAT_CALL | `back/app/chat/privileges.py:6` |
| `CHAT_IMPERSONATE` | `app.chat` | privilege.CHAT_IMPERSONATE | `back/app/chat/privileges.py:7` |
| `CHAT_MANAGE` | `app.chat` | privilege.CHAT_MANAGE | `back/app/chat/privileges.py:5` |
| `CHAT_SEND` | `app.chat` | privilege.CHAT_SEND | `back/app/chat/privileges.py:4` |
| `CONNECTION_ACCESS` | `app.connection` | privilege.CONNECTION_ACCESS | `back/app/connection/privileges.py:5` |
| `CONNECTION_EDIT` | `app.connection` | privilege.CONNECTION_EDIT | `back/app/connection/privileges.py:6` |
| `CONSOLE_ACCESS` | `app.console` | privilege.CONSOLE_ACCESS | `back/app/console/privileges.py:3` |
| `CONSOLE_ADMIN` | `app.console` | privilege.CONSOLE_ADMIN | `back/app/console/privileges.py:4` |
| `GOAL_ACCESS` | `app.goal` | privilege.GOAL_ACCESS | `back/app/goal/privileges.py:3` |
| `GOAL_EDIT` | `app.goal` | privilege.GOAL_EDIT | `back/app/goal/privileges.py:4` |
| `INCIDENT_ACCESS` | `app.incident` | privilege.INCIDENT_ACCESS | `back/app/incident/privileges.py:3` |
| `INCIDENT_EDIT` | `app.incident` | privilege.INCIDENT_EDIT | `back/app/incident/privileges.py:4` |
| `INCIDENT_PURGE` | `app.incident` | privilege.INCIDENT_PURGE | `back/app/incident/privileges.py:5` |
| `BRIEFING_EVALUATION_ACCESS` | `app.lab` | privilege.BRIEFING_EVALUATION_ACCESS | `back/app/lab/privileges.py:9` |
| `BRIEFING_EVALUATION_EDIT` | `app.lab` | privilege.BRIEFING_EVALUATION_EDIT | `back/app/lab/privileges.py:10` |
| `CONVERSATION_EXECUTOR_EVALUATION_ACCESS` | `app.lab` | privilege.CONVERSATION_EXECUTOR_EVALUATION_ACCESS | `back/app/lab/privileges.py:30` |
| `CONVERSATION_EXECUTOR_EVALUATION_EDIT` | `app.lab` | privilege.CONVERSATION_EXECUTOR_EVALUATION_EDIT | `back/app/lab/privileges.py:31` |
| `DISPATCHER_EVALUATION_ACCESS` | `app.lab` | privilege.DISPATCHER_EVALUATION_ACCESS | `back/app/lab/privileges.py:6` |
| `DISPATCHER_EVALUATION_EDIT` | `app.lab` | privilege.DISPATCHER_EVALUATION_EDIT | `back/app/lab/privileges.py:7` |
| `EVALUATION_ACCESS` | `app.lab` | privilege.EVALUATION_ACCESS | `back/app/lab/privileges.py:3` |
| `EVALUATION_EDIT` | `app.lab` | privilege.EVALUATION_EDIT | `back/app/lab/privileges.py:4` |
| `GOAL_TRACKING_EVALUATION_ACCESS` | `app.lab` | privilege.GOAL_TRACKING_EVALUATION_ACCESS | `back/app/lab/privileges.py:24` |
| `GOAL_TRACKING_EVALUATION_EDIT` | `app.lab` | privilege.GOAL_TRACKING_EVALUATION_EDIT | `back/app/lab/privileges.py:25` |
| `MEMORY_EXTRACTION_EVALUATION_ACCESS` | `app.lab` | privilege.MEMORY_EXTRACTION_EVALUATION_ACCESS | `back/app/lab/privileges.py:18` |
| `MEMORY_EXTRACTION_EVALUATION_EDIT` | `app.lab` | privilege.MEMORY_EXTRACTION_EVALUATION_EDIT | `back/app/lab/privileges.py:19` |
| `OUTCOME_REFLECTION_EVALUATION_ACCESS` | `app.lab` | privilege.OUTCOME_REFLECTION_EVALUATION_ACCESS | `back/app/lab/privileges.py:21` |
| `OUTCOME_REFLECTION_EVALUATION_EDIT` | `app.lab` | privilege.OUTCOME_REFLECTION_EVALUATION_EDIT | `back/app/lab/privileges.py:22` |
| `PLANNER_EVALUATION_ACCESS` | `app.lab` | privilege.PLANNER_EVALUATION_ACCESS | `back/app/lab/privileges.py:12` |
| `PLANNER_EVALUATION_EDIT` | `app.lab` | privilege.PLANNER_EVALUATION_EDIT | `back/app/lab/privileges.py:13` |
| `TASK_EXECUTOR_EVALUATION_ACCESS` | `app.lab` | privilege.TASK_EXECUTOR_EVALUATION_ACCESS | `back/app/lab/privileges.py:27` |
| `TASK_EXECUTOR_EVALUATION_EDIT` | `app.lab` | privilege.TASK_EXECUTOR_EVALUATION_EDIT | `back/app/lab/privileges.py:28` |
| `TOPIC_CLASSIFICATION_EVALUATION_ACCESS` | `app.lab` | privilege.TOPIC_CLASSIFICATION_EVALUATION_ACCESS | `back/app/lab/privileges.py:15` |
| `TOPIC_CLASSIFICATION_EVALUATION_EDIT` | `app.lab` | privilege.TOPIC_CLASSIFICATION_EVALUATION_EDIT | `back/app/lab/privileges.py:16` |
| `VOICE_EXECUTOR_EVALUATION_ACCESS` | `app.lab` | privilege.VOICE_EXECUTOR_EVALUATION_ACCESS | `back/app/lab/privileges.py:33` |
| `VOICE_EXECUTOR_EVALUATION_EDIT` | `app.lab` | privilege.VOICE_EXECUTOR_EVALUATION_EDIT | `back/app/lab/privileges.py:34` |
| `LLM_API_ACCESS` | `app.llm` | privilege.LLM_API_ACCESS | `back/app/llm/privileges.py:5` |
| `LLM_CALL_PURGE` | `app.llm` | privilege.LLM_CALL_PURGE | `back/app/llm/privileges.py:6` |
| `LLM_PROVIDER_ACCESS` | `app.llm` | privilege.LLM_PROVIDER_ACCESS | `back/app/llm/privileges.py:3` |
| `LLM_PROVIDER_EDIT` | `app.llm` | privilege.LLM_PROVIDER_EDIT | `back/app/llm/privileges.py:4` |
| `MCP_API_ACCESS` | `app.mcp` | privilege.MCP_API_ACCESS | `back/app/mcp/privileges.py:3` |
| `MEMORY_ACCESS` | `app.memory` | privilege.MEMORY_ACCESS | `back/app/memory/privileges.py:3` |
| `MEMORY_ADMIN` | `app.memory` | privilege.MEMORY_ADMIN | `back/app/memory/privileges.py:5` |
| `MEMORY_ASSIGN_ALL_USERS` | `app.memory` | privilege.MEMORY_ASSIGN_ALL_USERS | `back/app/memory/privileges.py:6` |
| `MEMORY_EDIT` | `app.memory` | privilege.MEMORY_EDIT | `back/app/memory/privileges.py:4` |
| `PROCESS_ADMIN` | `app.process` | privilege.PROCESS_ADMIN | `back/app/process/privileges.py:5` |
| `PROCESS_LAUNCH` | `app.process` | privilege.PROCESS_LAUNCH | `back/app/process/privileges.py:4` |
| `PROCESS_READ` | `app.process` | privilege.PROCESS_READ | `back/app/process/privileges.py:3` |
| `SKILL_ACCESS` | `app.skill` | privilege.SKILL_ACCESS | `back/app/skill/privileges.py:3` |
| `SKILL_ASSIGN` | `app.skill` | privilege.SKILL_ASSIGN | `back/app/skill/privileges.py:5` |
| `SKILL_EDIT` | `app.skill` | privilege.SKILL_EDIT | `back/app/skill/privileges.py:4` |
| `TASK_ACCESS` | `app.task` | privilege.TASK_ACCESS | `back/app/task/privileges.py:5` |
| `TASK_EDIT` | `app.task` | privilege.TASK_EDIT | `back/app/task/privileges.py:6` |
| `TASK_PURGE` | `app.task` | privilege.TASK_PURGE | `back/app/task/privileges.py:7` |
| `TOOL_ACCESS` | `app.tools` | privilege.TOOL_ACCESS | `back/app/tools/privileges.py:5` |
| `TOOL_EDIT` | `app.tools` | privilege.TOOL_EDIT | `back/app/tools/privileges.py:6` |
| `TOPIC_ACCESS` | `app.topic` | privilege.TOPIC_ACCESS | `back/app/topic/privileges.py:3` |
| `TOPIC_EDIT` | `app.topic` | privilege.TOPIC_EDIT | `back/app/topic/privileges.py:4` |
| `HERMES_ACCESS` | `bridge.hermes` | privilege.HERMES_ACCESS | `back/bridge/hermes/privileges.py:5` |
| `HERMES_EDIT` | `bridge.hermes` | privilege.HERMES_EDIT | `back/bridge/hermes/privileges.py:6` |
| `MANAGE_ASSIGNMENT` | `core.authorize` | privilege.MANAGE_ASSIGNMENT | `back/core/authorize/privileges.py:15` |
| `MANAGE_PRIVILEGE` | `core.authorize` | privilege.MANAGE_PRIVILEGE | `back/core/authorize/privileges.py:7` |
| `MANAGE_ROLE` | `core.authorize` | privilege.MANAGE_ROLE | `back/core/authorize/privileges.py:11` |
| `READ_ASSIGNMENT` | `core.authorize` | privilege.READ_ASSIGNMENT | `back/core/authorize/privileges.py:14` |
| `READ_PRIVILEGE` | `core.authorize` | privilege.READ_PRIVILEGE | `back/core/authorize/privileges.py:6` |
| `READ_ROLE` | `core.authorize` | privilege.READ_ROLE | `back/core/authorize/privileges.py:10` |
| `PARAMS_ACCESS` | `core.params` | privilege.PARAMS_ACCESS | `back/core/params/privileges.py:3` |
| `PARAMS_EDIT` | `core.params` | privilege.PARAMS_EDIT | `back/core/params/privileges.py:4` |
| `TEAM_ACCESS` | `core.team` | privilege.TEAM_ACCESS | `back/core/team/privileges.py:1` |
| `TEAM_EDIT` | `core.team` | privilege.TEAM_EDIT | `back/core/team/privileges.py:2` |
| `TEAM_MEMBERS_EDIT` | `core.team` | privilege.TEAM_MEMBERS_EDIT | `back/core/team/privileges.py:3` |
| `CREATE_USER` | `core.user` | privilege.CREATE_USER | `back/core/user/privileges.py:6` |
| `DELETE_USER` | `core.user` | privilege.DELETE_USER | `back/core/user/privileges.py:8` |
| `READ_USER` | `core.user` | privilege.READ_USER | `back/core/user/privileges.py:5` |
| `UPDATE_USER` | `core.user` | privilege.UPDATE_USER | `back/core/user/privileges.py:7` |

## Pages frontend

| Route indicative | Module | Source |
|---|---|---|
| `/agent` | `app/agent` | `front/app/agent/pages/index.vue` |
| `/authorize` | `core/authorize` | `front/core/authorize/pages/index.vue` |
| `/authorize/profile` | `core/authorize` | `front/core/authorize/pages/profile.vue` |
| `/browser/settings` | `app/browser` | `front/app/browser/pages/settings.vue` |
| `/chat` | `app/chat` | `front/app/chat/pages/index.vue` |
| `/connection/mail` | `app/connection` | `front/app/connection/pages/mail.vue` |
| `/console/executor` | `app/console` | `front/app/console/pages/executor.vue` |
| `/dream` | `app/dream` | `front/app/dream/pages/index.vue` |
| `/goal` | `app/goal` | `front/app/goal/pages/index.vue` |
| `/harnesses/:id` | `app/harnesses` | `front/app/harnesses/pages/[id].vue` |
| `/incident` | `app/incident` | `front/app/incident/pages/index.vue` |
| `/index` | `app/index` | `front/app/index/pages/index.vue` |
| `/index/:all(.*)*` | `app/index` | `front/app/index/pages/[...all].vue` |
| `/index/about` | `app/index` | `front/app/index/pages/about.vue` |
| `/index/dashboard` | `app/index` | `front/app/index/pages/dashboard.vue` |
| `/index/license` | `app/index` | `front/app/index/pages/license.vue` |
| `/index/welcome` | `app/index` | `front/app/index/pages/welcome.vue` |
| `/lab` | `app/lab` | `front/app/lab/pages/index.vue` |
| `/lab/:section` | `app/lab` | `front/app/lab/pages/[section].vue` |
| `/lab/ai-evaluations` | `app/lab` | `front/app/lab/pages/ai-evaluations.vue` |
| `/llm` | `app/llm` | `front/app/llm/pages/index.vue` |
| `/llm/calls` | `app/llm` | `front/app/llm/pages/calls.vue` |
| `/memory` | `app/memory` | `front/app/memory/pages/index.vue` |
| `/memory/contacts` | `app/memory` | `front/app/memory/pages/contacts.vue` |
| `/memory/documents` | `app/memory` | `front/app/memory/pages/documents.vue` |
| `/params` | `core/params` | `front/core/params/pages/index.vue` |
| `/params/:section` | `core/params` | `front/core/params/pages/[section].vue` |
| `/params/harnesses/:provider` | `core/params` | `front/core/params/pages/harnesses/[provider].vue` |
| `/process` | `app/process` | `front/app/process/pages/index.vue` |
| `/skill` | `app/skill` | `front/app/skill/pages/index.vue` |
| `/task` | `app/task` | `front/app/task/pages/index.vue` |
| `/team` | `core/team` | `front/core/team/pages/index.vue` |
| `/tools` | `app/tools` | `front/app/tools/pages/index.vue` |
| `/topic` | `app/topic` | `front/app/topic/pages/index.vue` |
| `/topic/:id` | `app/topic` | `front/app/topic/pages/[id].vue` |
| `/user/login` | `core/user` | `front/core/user/pages/login.vue` |
| `/user/register` | `core/user` | `front/core/user/pages/register.vue` |
| `/user/tokens` | `core/user` | `front/core/user/pages/tokens.vue` |
| `/user/users` | `core/user` | `front/core/user/pages/users.vue` |

## Configuration

- Settings déclarés : 27.
- Variables dans `.env.example` : 40.
- Settings sans entrée `.env.example` : —.
- Entrées `.env.example` sans champ direct dans `Settings` : `BROWSER_EXECUTOR_CPUS`, `BROWSER_EXECUTOR_MEMORY_LIMIT`, `DEV_DEBUGPY_PORT`, `DEV_HOST_USER_ID`, `POSTGRES_MODE`, `SSH_EXECUTOR_CPUS`, `SSH_EXECUTOR_MEMORY_LIMIT`, `TZ`, `WEBRTC_TURN_CPUS`, `WEBRTC_TURN_IMAGE`, `WEBRTC_TURN_MAX_PORT`, `WEBRTC_TURN_MEMORY_LIMIT`, `WEBRTC_TURN_MIN_PORT`.
