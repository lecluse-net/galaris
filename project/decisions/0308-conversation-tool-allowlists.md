# 0308 — Autorisations MCP par outil en conversation

Statut : accepté — 22 novembre 2026. Précise la projection de la décision
[0022](0022-conversation-control-plane.md).

## Décision

Le catalogue conversationnel exige une connexion active, une autorisation du nom exact
et de l'origine de l'outil pour le Service de cette connexion, et les droits effectifs.
Un outil natif et un outil externe de même nom ont des autorisations distinctes. La vérification
s'applique à la découverte et à l'appel, y compris lors d'une reprise. Les permissions
de fonction, les accords, les restrictions du runtime et les ACL continuent de s'appliquer.

Le logiciel impose la liste des outils admis par Service intégré. Leur fiche affiche en
lecture seule tous les outils du registre natif, y compris ceux exclus des conversations.
Pour un Service personnalisé, un
administrateur choisit chaque outil dans **Outils en conversation** sur la carte du Service.
La liste s'applique à tous les agents. L'exposition effective reste bornée par les outils
que la connexion fournit et par ses droits. La fiche du Service regroupe par nom les
outils MCP distants annoncés avec les paramètres partagés et via les connexions actives
du périmètre de l'administrateur s'il a le droit de consulter leurs outils. La découverte
est effectuée à la demande et traite les connexions par lots. Un outil absent peut être
ajouté par son nom MCP exact. Seule la liste d'autorisation du Service est persistée par
cette interface. La liste commence vide à la création
d'un Service, y compris par import, et lors de la mise à jour depuis l'ancien réglage global.
Ce réglage disparaît à la convergence du schéma.
Les Tasks suivent leur politique habituelle. Les demandes d'accord individuelles déjà émises
avec l'ancienne configuration peuvent nécessiter une nouvelle confirmation.
Les ressources et prompts MCP distants ne
sont pas montés en conversation. Une présentation interactive ouverte par un humain
revérifie l'accès à l'outil d'origine et les droits de sa ressource.

## Outils intégrés admis

| Service | Outils |
| --- | --- |
| Galaris | `documentation_catalog`, `documentation_search` |
| Agent | `agent_list`, `agent_get`, `team_list`, `team_members` |
| Contact | `contact_list`, `contact_get` |
| Tâches | `conversation_task_submit`, `conversation_task_list`, `conversation_task_status`, `conversation_task_pause`, `conversation_task_resume`, `conversation_task_retry`, `conversation_task_stop` |
| Processus | `process_list`, `process_get`, `process_list_runs`, `process_get_run`, `conversation_process_start`, `conversation_process_prepare`, `conversation_process_pending`, `conversation_process_respond` |
| Memory | `memory_remember`, `memory_forget`, `memory_summarize`, `memory_upcoming` |
| Documents | `document_show`, `document_sharing`, `document_share`, `document_revision_list`, `document_revision_compare`, `mindmap_create`, `mindmap_read`, `mindmap_add`, `mindmap_edit` |
| Partage de fichiers | `file_list`, `file_info`, `file_search`, `file_read`, `file_create`, `file_write`, `file_append`, `file_edit`, `file_rename`, `file_to_pdf` |
| Agenda | `calendar_list`, `calendar_events`, `calendar_event_get`, `calendar_is_available`, `calendar_find_free_slots`, `calendar_create_event`, `calendar_update_event`, `calendar_delete_event`, `calendar_actions`, `calendar_action_set` |
| Chat | `repository_show`, `conversation_choice_resolve`, `voice_call_stop`, `messenger_room_send_message`, `messenger_send_message_to_user`, `messenger_list_rooms`, `messenger_room_history`, `messenger_search_users` |
| Navigateur | `search_web` |
| Multimédia | `image_from_pdf` |

Les autres outils intégrés sont exclus du catalogue conversationnel. La voix native temps
réel utilise son propre sous-ensemble d'opérations conversationnelles, avec la vérification
d'autorisation à l'appel.
