# ADR 0020 — Dossiers thématiques globaux comme pivot de la mémoire

- Statut : Accepted
- Date : 2026-07-31
- Dernière mise à jour : 2026-08-28

## Contexte

Les souvenirs issus des Tasks et des conversations Voice étaient reliés par la structure des
Tasks et par un nœud représentant la room de messagerie. Ce pivot confondait le média utilisé avec
le sens durable de l’activité : une room peut contenir plusieurs thèmes, un même thème peut passer
par plusieurs canaux et plusieurs agents, et le canal ne doit pas devenir le centre du graphe.

## Décision

Le domaine `app.topic` possède les dossiers thématiques globaux de l’instance. Un `Topic` est
identifié par UUID, ne possède aucun agent propriétaire et expose un titre, un résumé, une
description et des mots-clés volontairement généralisés.

Chaque `Task` et chaque `VoiceConversationSession` possède au plus un `topic_id`, nullable tant que
Dream n’a pas exécuté le classement. Une conversation Messenger n’a pas de `topic_id` propre : ses
dossiers sont ceux des Tasks qui en sont issues, de sorte qu’une room peut en contenir plusieurs.
Cette relation dérivée est exposée par l’API Topic à partir de `(connection_id, room_id)`.

Dream exécute d’abord `topic.classify_task` ou
`topic.classify_voice_session`. Le modèle choisit parmi une liste bornée de dossiers globaux ou
en propose un nouveau. La décision structurée est checkpointée avant application et une
réutilisation ne peut désigner qu’un UUID présenté au modèle.

La politique de création qui remplace ce classement initial est décrite
par l'[ADR 0024](0024-governed-topic-creation.md).

Chaque Topic est projeté dans Memory sous forme d’un item `source_managed`, `read_only`, `public`
et sans `owner_agent_id`. Cette exception est bornée par une contrainte SQL ; les souvenirs
ordinaires et les projections privées conservent obligatoirement un propriétaire. Les sources
`task:*` et `conversation_round:*` sont reliées ensuite au Topic par le
réconciliateur déterministe d'`app.memory`. Les provenances peuvent être enregistrées pendant une
activité, mais la projection du lien attend son classement.

Un lien public vers un souvenir privé ne rend pas ce souvenir public. Les API de graphe et de liens
filtrent chaque nœud voisin avec les ACL du demandeur ; l’administration conserve une vue globale.
Les anciens nœuds de conversation et liens du projecteur `task_structure` sont supprimés lors de
la mise à niveau et ne sont plus produits.

Le Tool intégré `topic` constitue la façade d'administration agentique de ce domaine. Il expose le
catalogue et les items liés, la création et la modification révisionnelle, la fusion, la scission
par sélection hétérogène et la réaffectation d'un item exact. Les types réaffectables correspondent
aux porteurs canoniques du lien : Task, message, round texte, tour vocal, Memory et document. Les
mutations vérifient toujours le Topic source courant avant d'écrire et déplacent aussi les scopes
Topic/contact lorsqu'un nœud Memory est concerné.

La définition du Tool est une donnée permanente `app.tools` créée par DbAdmin. Aucune `Connection`
n'est créée automatiquement : un administrateur choisit explicitement les agents qui reçoivent
cette capacité globale. Chaque appel revérifie l'existence de cette connexion active.

## Conséquences

- Le sens durable est indépendant de Messenger, Voice et de l’agent qui a traité l’activité.
- Une Task ou session ne peut pas être simultanément répartie sur plusieurs dossiers.
- Un souvenir consolidé peut être relié à plusieurs Topics s’il provient de plusieurs épisodes.
- Les dossiers sont consultables par une API et une page globales protégées par `TOPIC_ACCESS`.
- Un agent ne peut administrer les dossiers que si le Tool `topic` lui a été explicitement connecté.
- Les métadonnées publiques d’un Topic ne doivent contenir aucun identifiant de transport,
  extrait privé ou nom de contact privé.
- Les conversations Voice sans texte exploitable restent non classées plutôt que de créer un
  dossier vide ou trompeur.

## Fusion et scission

La fusion conserve l'UUID cible, déplace les affectations et liens de la source puis supprime
logiquement celle-ci. La scission crée un nouvel UUID et déplace une sélection explicite d'items.
Les projections Memory et les scopes Topic/contact suivent les affectations déplacées.

## Preuves dans le code

`back/app/topic/`, `back/app/dream/mechanisms/topic_classification.py`,
`back/app/memory/link_reconciliation.py`, `back/app/task/models.py`,
`back/app/voice/models.py`, `back/app/memory/models.py`, `front/app/topic/` et leurs tests.
