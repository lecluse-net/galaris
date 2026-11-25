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
| Agent | `agent_list`, `agent_get`, `team_list`, `team_members`, `agent_team_list` |
| Contact | `contact_list`, `contact_get` |
| Tâches | `task_run`, `task_list`, `task_get`, `task_pause`, `task_resume`, `task_cancel` |
| Processus | `process_start_conversation`, `process_prepare`, `process_pending`, `process_respond` |
| Services | `services_list`, `service_connection_list` |
| Sujets | `topic_list`, `topic_items_list` |
| Memory | `memory_remember`, `memory_forget`, `memory_summarize`, `memory_upcoming` |
| Documents | `document_show`, `document_sharing`, `document_share` |
| Compétences | `skills_list`, `skill_read` |
| Partage de fichiers | `file_schemes`, `file_list`, `file_info`, `file_search`, `file_read`, `dataset_query` |
| Agenda | `calendar_list`, `calendar_events` |
| Chat | `chat_screenshot`, `chat_repository_show`, `chat_choice_resolve`, `voice_call_start`, `voice_call_stop`, `voice_call_list`, `messenger_room_send_message`, `messenger_send_message_to_user`, `messenger_list_rooms`, `messenger_room_history`, `messenger_search_users`, `messenger_send_audio_message`, `messenger_room_send_file`, `messenger_send_file_to_user` |
| Navigateur | `search_web` |
| Multimédia | `image_read`, `audio_read`, `audio_transcribe` |

Les autres outils intégrés sont exclus du catalogue conversationnel. La voix native temps
réel utilise son propre sous-ensemble d'opérations conversationnelles, avec la vérification
d'autorisation à l'appel.

`task_run`, `task_get` et `task_cancel` sont partagés avec le catalogue d'exécution. En
conversation, `task_run` admet le travail de fond sans `agent_id`. En exécution,
`agent_id` indique le collègue à qui déléguer. Le contexte injecté par le serveur sélectionne
les contrôles applicables. La fusion des permissions de fonction conserve la plus restrictive
des décisions effectives historiques par connexion.
